"""Ponte entre o embarcado e o modelo de risco: junta a previsao do ModeloRisco (chuva/mare/bairro)
com a ultima leitura do ultrassom (embarcado/dados/leituras.csv) em um unico nivel de alerta 0-3.

O modelo estima a propensao a alagar a partir de variaveis historicas; o sensor mede o nivel da agua agora.
Nao ha historico do sensor para virar feature, entao a combinacao e por regra: vale o maior dos dois niveis.
"""
import csv
from datetime import datetime
from pathlib import Path

CSV_PADRAO = Path(__file__).resolve().parent.parent / "embarcado" / "dados" / "leituras.csv"
# Nivel da agua (cm acima do fundo/referencia) que dispara os niveis 1, 2 e 3. VALORES PROVISORIOS:
# calibrar com a instalacao real do sensor.
LIMIARES_AGUA_CM = (5.0, 15.0, 30.0)
IDADE_MAX_S = 600          # leitura mais velha que isso e ignorada (sensor offline)


def ultima_leitura(arquivo=CSV_PADRAO, sensor_id=None, agora=None, idade_max_s=IDADE_MAX_S):
    """Ultima leitura valida e recente do CSV do coletor, ou None."""
    arquivo = Path(arquivo)
    if not arquivo.exists():
        return None
    agora = agora or datetime.now()
    with open(arquivo, newline="", encoding="utf-8") as f:
        linhas = [l for l in csv.DictReader(f) if sensor_id is None or l["sensor_id"] == sensor_id]
    for l in reversed(linhas):
        try:
            ts, dist = datetime.fromisoformat(l["timestamp"]), float(l["distancia_cm"])
        except (KeyError, ValueError):
            continue
        if (agora - ts).total_seconds() > idade_max_s:
            return None
        return {"timestamp": ts, "sensor_id": l["sensor_id"], "distancia_cm": dist}
    return None


def nivel_sensor(distancia_cm, altura_montagem_cm, limiares=LIMIARES_AGUA_CM):
    """Nivel 0-3 pela altura da agua = altura de montagem - distancia medida."""
    agua = max(altura_montagem_cm - distancia_cm, 0.0)
    return sum(agua >= l for l in limiares), agua


def avaliar(modelo, df_features, altura_montagem_cm, arquivo=CSV_PADRAO, sensor_id=None, agora=None):
    """Alerta combinado para uma linha de entrada do modelo (colunas de entrada_api, inclusive 'bairro')."""
    prob = float(modelo.prever(df_features)[0])
    nivel_modelo = int(modelo.nivel(df_features)[0])
    leitura = ultima_leitura(arquivo, sensor_id, agora)
    nivel_s, agua = (None, None)
    if leitura is not None:
        nivel_s, agua = nivel_sensor(leitura["distancia_cm"], altura_montagem_cm)
    nivel = max(nivel_modelo, nivel_s or 0)
    return {"nivel": nivel, "origem": "sensor" if (nivel_s or 0) > nivel_modelo else "modelo",
            "probabilidade_modelo": prob, "nivel_modelo": nivel_modelo,
            "nivel_sensor": nivel_s, "nivel_agua_cm": agua, "leitura": leitura}
