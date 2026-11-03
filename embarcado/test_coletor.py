import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('coletor', Path(__file__).resolve().parent / 'coletor.py')
coletor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coletor)

class ColetorTest(unittest.TestCase):
    def test_leituras_invalidas_nao_interrompem_csv(self):
        with tempfile.TemporaryDirectory() as pasta, patch.object(coletor, 'ARQUIVO', Path(pasta) / 'leituras.csv'):
            coletor.ARQUIVO.touch()
            for payload in [b'{}', b'[]', b'\xff', b'{"sensor_id":"x","distancia_cm":NaN}', b'{"sensor_id":"x","distancia_cm":true}', b'{"sensor_id":"x","distancia_cm":7.5}', b'{"sensor_id":"x","distancia_cm":8}']:
                coletor.on_message(None, None, SimpleNamespace(topic='pluvia/sensor01/leituras', payload=payload))
            with coletor.ARQUIVO.open(newline='') as arquivo:
                linhas = list(csv.reader(arquivo))
            self.assertEqual(len(linhas), 3)
            self.assertEqual(linhas[0], ['timestamp', 'sensor_id', 'distancia_cm'])
            self.assertEqual(linhas[1][1:], ['x', '7.5'])

    def test_camera_salva_binario_e_rejeita_payload_invalido(self):
        with tempfile.TemporaryDirectory() as pasta, patch.object(coletor, 'PASTA_IMAGENS', Path(pasta)):
            # Fixture de transporte: testa preservacao dos bytes, nao decodificacao JPEG.
            imagem = b'\xff\xd8\x00\x80\xff\xd9'
            for topico, payload in [('pluvia/sensor01/camera', imagem), ('pluvia/sensor01/camera', b'{}'), ('pluvia/../camera', imagem)]:
                coletor.on_message(None, None, SimpleNamespace(topic=topico, payload=payload))
            arquivos = list(Path(pasta).rglob('*.jpg'))
            self.assertEqual(len(arquivos), 1)
            self.assertEqual(arquivos[0].read_bytes(), imagem)
            self.assertEqual(arquivos[0].parent.name, 'sensor01')

if __name__ == '__main__':
    unittest.main()
