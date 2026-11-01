"""Receptor MQTT da ESP32-CAM: grava leituras e fotos e devolve o nivel de risco para a placa.

Topicos (<id> = sensor_id configurado no firmware):
  pluvia/sensor/<id>/leitura   placa -> servidor  JSON {"ts", "distancia_cm", "nivel_agua_cm", "rssi", "uptime_s"}
  pluvia/sensor/<id>/foto      placa -> servidor  JPEG binario
  pluvia/sensor/<id>/status    placa -> servidor  "online" / "offline" (retido; "offline" e o testamento da conexao)
  pluvia/sensor/<id>/risco     servidor -> placa  JSON {"nivel", "nivel_sensor", "nivel_modelo", "intervalo_leitura_s",
                                                         "intervalo_foto_s"} (retido: a placa recebe ao reconectar)
  pluvia/sensor/<id>/comando   servidor -> placa  "foto" (tira uma foto agora)

O nivel publicado e o maior entre o nivel medido (agua no ponto, pelos limiares do sensor) e o nivel previsto pelo
modelo para o bairro no dia. O modelo so entra quando ha uma linha do dia em features_dia.csv (gerado pelo pipeline);
sem ela, nivel_modelo = null e vale so a medida local.

Uso:  python embarcado/receptor.py --config embarcado/sensores.json
"""
import argparse
import datetime as dt
import json
import logging
import sqlite3
import sys
from pathlib import Path

import paho.mqtt.client as mqtt

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))                     # o joblib do modelo precisa de modelo.py e preparacao.py

PREFIXO = "pluvia/sensor"
FUSO_RECIFE = dt.timezone(dt.timedelta(hours=-3))         # America/Recife, sem horario de verao
# quanto maior o risco, mais frequente a leitura e a foto (segundos)
INTERVALOS = {0: (300, 1800), 1: (120, 600), 2: (60, 300), 3: (30, 120)}

log = logging.getLogger("receptor")


# ------------------------------------------------------------------ armazenamento (espelha leituras_sensor do schema.sql)
class Armazem:
    def __init__(self, caminho_db, pasta_fotos):
        self.pasta_fotos = Path(pasta_fotos)
        self.db = sqlite3.connect(str(caminho_db), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS leituras_sensor (
              leitura_id    INTEGER PRIMARY KEY AUTOINCREMENT,
              sensor_id     TEXT NOT NULL,
              bairro        TEXT,
              ts_utc        TEXT NOT NULL,
              nivel_agua_cm REAL,
              distancia_cm  REAL,
              rssi          INTEGER,
              nivel_risco   INTEGER
            );
            CREATE TABLE IF NOT EXISTS fotos_sensor (
              foto_id   INTEGER PRIMARY KEY AUTOINCREMENT,
              sensor_id TEXT NOT NULL,
              ts_utc    TEXT NOT NULL,
              caminho   TEXT NOT NULL,
              bytes     INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_leituras ON leituras_sensor (sensor_id, ts_utc);
        """)

    def gravar_leitura(self, sensor_id, bairro, ts, d, nivel_risco):
        self.db.execute("INSERT INTO leituras_sensor (sensor_id, bairro, ts_utc, nivel_agua_cm, distancia_cm, rssi, "
                        "nivel_risco) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (sensor_id, bairro, ts.isoformat(), d.get("nivel_agua_cm"), d.get("distancia_cm"),
                         d.get("rssi"), nivel_risco))
        self.db.commit()

    def gravar_foto(self, sensor_id, ts, jpeg):
        pasta = self.pasta_fotos / sensor_id
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / f"{ts.strftime('%Y%m%dT%H%M%SZ')}.jpg"
        caminho.write_bytes(jpeg)
        self.db.execute("INSERT INTO fotos_sensor (sensor_id, ts_utc, caminho, bytes) VALUES (?, ?, ?, ?)",
                        (sensor_id, ts.isoformat(), str(caminho), len(jpeg)))
        self.db.commit()
        return caminho


# ------------------------------------------------------------------ nivel previsto pelo modelo
class RiscoModelo:
    """Carrega o ModeloRisco (joblib) e as features do dia por bairro; recarrega o CSV quando ele muda."""

    def __init__(self, caminho_modelo, caminho_features):
        self.modelo = None
        self.caminho_features = Path(caminho_features) if caminho_features else None
        self._mtime, self._features = None, None
        if caminho_modelo and Path(caminho_modelo).exists():
            import joblib
            self.modelo = joblib.load(caminho_modelo)
            log.info("modelo carregado: %s (%s)", caminho_modelo, self.modelo.nome)
        else:
            log.warning("modelo nao encontrado (%s): so o nivel medido sera usado", caminho_modelo)

    def _features_atuais(self):
        if self.caminho_features is None or not self.caminho_features.exists():
            return None
        mtime = self.caminho_features.stat().st_mtime
        if mtime != self._mtime:
            import pandas as pd
            self._features = pd.read_csv(self.caminho_features, parse_dates=["data"])
            self._mtime = mtime
            log.info("features do dia recarregadas: %d linhas", len(self._features))
        return self._features

    def nivel(self, bairro, agora_utc):
        if self.modelo is None:
            return None
        f = self._features_atuais()
        if f is None:
            return None
        hoje = agora_utc.astimezone(FUSO_RECIFE).date()
        linha = f[(f["bairro"] == bairro) & (f["data"].dt.date == hoje)]
        if linha.empty:
            return None
        faltando = [c for c in self.modelo.features if c not in linha.columns]
        if faltando:
            log.error("features_dia sem as colunas %s: modelo ignorado", faltando)
            return None
        return int(self.modelo.nivel(linha.tail(1))[0])


def nivel_sensor(nivel_agua_cm, limiares_cm):
    """0..3 pelo numero de limiares ultrapassados; sem medida valida, 0."""
    if nivel_agua_cm is None:
        return 0
    return sum(nivel_agua_cm >= l for l in limiares_cm)


# ------------------------------------------------------------------ servico
class Receptor:
    def __init__(self, config, armazem, risco_modelo):
        self.sensores = config["sensores"]
        self.armazem, self.risco_modelo = armazem, risco_modelo
        self.cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.get("client_id", "pluvia-receptor"))
        if config.get("usuario"):
            self.cliente.username_pw_set(config["usuario"], config.get("senha"))
        self.cliente.on_connect = self._ao_conectar
        self.cliente.on_message = self._ao_receber
        self.host, self.porta = config.get("host", "localhost"), int(config.get("porta", 1883))

    def _ao_conectar(self, cliente, _userdata, _flags, codigo, _props):
        if codigo.is_failure:
            log.error("falha ao conectar no broker: %s", codigo)
            return
        cliente.subscribe([(f"{PREFIXO}/+/leitura", 1), (f"{PREFIXO}/+/foto", 0), (f"{PREFIXO}/+/status", 1)])
        log.info("conectado em %s:%d", self.host, self.porta)

    def _ao_receber(self, _cliente, _userdata, msg):
        partes = msg.topic.split("/")
        if len(partes) != 4:
            return
        sensor_id, tipo = partes[2], partes[3]
        if sensor_id not in self.sensores:
            log.warning("sensor desconhecido %s (adicione em sensores.json)", sensor_id)
            return
        try:
            if tipo == "leitura":
                self.tratar_leitura(sensor_id, json.loads(msg.payload))
            elif tipo == "foto":
                self.tratar_foto(sensor_id, msg.payload)
            elif tipo == "status":
                log.info("%s esta %s", sensor_id, msg.payload.decode(errors="replace"))
        except Exception:
            log.exception("erro tratando %s", msg.topic)

    def tratar_leitura(self, sensor_id, d):
        cfg = self.sensores[sensor_id]
        agora = dt.datetime.now(dt.timezone.utc)
        ts = dt.datetime.fromtimestamp(d["ts"], dt.timezone.utc) if d.get("ts") else agora   # ts=0: placa sem NTP
        n_sensor = nivel_sensor(d.get("nivel_agua_cm"), cfg["limiares_cm"])
        n_modelo = self.risco_modelo.nivel(cfg["bairro"], agora)
        nivel = max(n_sensor, n_modelo or 0)
        self.armazem.gravar_leitura(sensor_id, cfg["bairro"], ts, d, nivel)
        leitura_s, foto_s = INTERVALOS[nivel]
        resposta = {"nivel": nivel, "nivel_sensor": n_sensor, "nivel_modelo": n_modelo,
                    "intervalo_leitura_s": leitura_s, "intervalo_foto_s": foto_s}
        self.cliente.publish(f"{PREFIXO}/{sensor_id}/risco", json.dumps(resposta), qos=1, retain=True)
        log.info("%s: agua=%s cm -> nivel %d (sensor %d, modelo %s)", sensor_id, d.get("nivel_agua_cm"), nivel,
                 n_sensor, n_modelo)
        return resposta

    def tratar_foto(self, sensor_id, jpeg):
        if not jpeg.startswith(b"\xff\xd8"):
            log.warning("%s: foto ignorada (nao e JPEG, %d bytes)", sensor_id, len(jpeg))
            return None
        caminho = self.armazem.gravar_foto(sensor_id, dt.datetime.now(dt.timezone.utc), jpeg)
        log.info("%s: foto salva em %s (%d KB)", sensor_id, caminho, len(jpeg) // 1024)
        return caminho

    def pedir_foto(self, sensor_id):
        self.cliente.publish(f"{PREFIXO}/{sensor_id}/comando", "foto", qos=1)

    def rodar(self):
        self.cliente.connect(self.host, self.porta, keepalive=60)
        self.cliente.loop_forever(retry_first_connection=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(RAIZ / "embarcado" / "sensores.json"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = json.loads(Path(args.config).read_text())
    base = Path(args.config).resolve().parent
    dados = base / config.get("pasta_dados", "dados")
    dados.mkdir(parents=True, exist_ok=True)
    modelo = config.get("modelo")
    features = config.get("features_dia")
    receptor = Receptor(config, Armazem(dados / "embarcado.db", dados / "fotos"),
                        RiscoModelo(base / modelo if modelo else None, base / features if features else None))
    receptor.rodar()


if __name__ == "__main__":
    main()
