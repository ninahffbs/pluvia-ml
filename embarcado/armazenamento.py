"""Persistencia opcional das leituras e fotos no PostgreSQL (tabelas leituras_sensor e fotos_sensor do schema.sql).

Ativado pela variavel PLUVIA_DB_URL (ex.: postgresql://user:senha@host/pluvia). Sem ela, ou sem o pacote
psycopg, o coletor continua gravando so o CSV e os JPEGs. A altura de montagem do sensor (PLUVIA_ALTURA_CM)
permite calcular nivel_agua_cm = altura - distancia; sem ela a coluna fica NULL.
"""
import os
from datetime import datetime, timezone

DB_URL = os.environ.get("PLUVIA_DB_URL")


def altura_montagem_cm():
    try:
        return float(os.environ["PLUVIA_ALTURA_CM"])
    except (KeyError, ValueError):
        return None


def nivel_agua_cm(distancia_cm, altura_cm):
    if altura_cm is None:
        return None
    return round(altura_cm - distancia_cm, 2)


class Banco:
    def __init__(self, url=DB_URL, conectar=None):
        self.url, self._conectar, self._conn = url, conectar, None

    @property
    def ativo(self):
        return bool(self.url)

    def _conexao(self):
        if self._conn is None or getattr(self._conn, "closed", False):
            if self._conectar is None:
                import psycopg
                self._conectar = psycopg.connect
            self._conn = self._conectar(self.url, autocommit=True)
        return self._conn

    def _executar(self, sql, params):
        if not self.ativo:
            return False
        try:
            self._conexao().execute(sql, params)
            return True
        except Exception as erro:  # banco fora do ar nao pode derrubar o coletor
            print(f"Erro ao gravar no banco: {erro}")
            self._conn = None
            return False

    def gravar_leitura(self, sensor_id, distancia_cm, ts=None, altura_cm=None):
        ts = ts or datetime.now(timezone.utc)
        return self._executar(
            "INSERT INTO leituras_sensor (sensor_id, ts_utc, distancia_cm, nivel_agua_cm) VALUES (%s, %s, %s, %s)",
            (sensor_id, ts, distancia_cm, nivel_agua_cm(distancia_cm, altura_cm)))

    def gravar_foto(self, sensor_id, caminho, tamanho, ts=None):
        ts = ts or datetime.now(timezone.utc)
        return self._executar(
            "INSERT INTO fotos_sensor (sensor_id, ts_utc, caminho, bytes) VALUES (%s, %s, %s, %s)",
            (sensor_id, ts, str(caminho), tamanho))
