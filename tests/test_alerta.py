import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "embarcado"))
import alerta
import armazenamento

AGORA = datetime(2026, 1, 1, 12, 0, 0)


def csv_com(pasta, linhas):
    p = Path(pasta) / "leituras.csv"
    p.write_text("timestamp,sensor_id,distancia_cm\n" + "".join(linhas), encoding="utf-8")
    return p


def modelo(nivel):
    return SimpleNamespace(prever=lambda df: np.array([0.1]), nivel=lambda df: np.array([nivel]))


class AlertaTest(unittest.TestCase):
    def test_sensor_eleva_alerta(self):
        with tempfile.TemporaryDirectory() as d:
            p = csv_com(d, ["2026-01-01T11:59:00,PLUVIA_01,70\n"])
            r = alerta.avaliar(modelo(0), None, 100, p, agora=AGORA)
        self.assertEqual((r["nivel"], r["origem"], r["nivel_agua_cm"]), (3, "sensor", 30))

    def test_modelo_prevalece_se_maior(self):
        with tempfile.TemporaryDirectory() as d:
            p = csv_com(d, ["2026-01-01T11:59:00,PLUVIA_01,99\n"])
            r = alerta.avaliar(modelo(2), None, 100, p, agora=AGORA)
        self.assertEqual((r["nivel"], r["origem"]), (2, "modelo"))

    def test_leitura_velha_ou_ausente_e_ignorada(self):
        with tempfile.TemporaryDirectory() as d:
            p = csv_com(d, ["2026-01-01T10:00:00,PLUVIA_01,50\n"])
            self.assertIsNone(alerta.ultima_leitura(p, agora=AGORA))
            self.assertIsNone(alerta.ultima_leitura(Path(d) / "nao_existe.csv", agora=AGORA))
            self.assertEqual(alerta.avaliar(modelo(1), None, 100, p, agora=AGORA)["nivel"], 1)

    def test_filtra_por_sensor(self):
        with tempfile.TemporaryDirectory() as d:
            p = csv_com(d, ["2026-01-01T11:59:00,A,10\n", "2026-01-01T11:59:30,B,20\n"])
            self.assertEqual(alerta.ultima_leitura(p, "A", AGORA)["distancia_cm"], 10)


class BancoTest(unittest.TestCase):
    def test_grava_leitura_e_calcula_nivel(self):
        chamadas = []
        conn = SimpleNamespace(execute=lambda sql, p: chamadas.append((sql, p)))
        b = armazenamento.Banco("postgresql://x", conectar=lambda url, autocommit: conn)
        self.assertTrue(b.gravar_leitura("S", 30.0, altura_cm=100))
        self.assertTrue(b.gravar_foto("s1", "a.jpg", 10))
        self.assertEqual(chamadas[0][1][2:], (30.0, 70.0))
        self.assertIn("fotos_sensor", chamadas[1][0])

    def test_inativo_e_falha_nao_levantam(self):
        self.assertFalse(armazenamento.Banco(None).gravar_leitura("S", 1.0))
        def falha(url, autocommit):
            raise RuntimeError("fora do ar")
        self.assertFalse(armazenamento.Banco("x", conectar=falha).gravar_leitura("S", 1.0))


if __name__ == "__main__":
    unittest.main()
