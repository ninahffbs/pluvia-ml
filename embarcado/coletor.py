import csv
import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

import armazenamento

ARQUIVO = Path(__file__).resolve().parent / "dados" / "leituras.csv"
TOPICO = "pluvia/+/leituras"
TOPICO_CAMERA = "pluvia/+/camera"
PASTA_IMAGENS = ARQUIVO.parent / "imagens"
# IP do computador que roda o Mosquitto no Docker (o mesmo MQTT_BROKER do secrets.h).
# Nao use 127.0.0.1/localhost: num PC com Mosquitto instalado no Windows,
# o coletor conecta nesse outro broker e nao recebe nada da ESP.
# Para trocar sem editar o arquivo: defina a variavel de ambiente PLUVIA_BROKER.
BROKER = os.environ.get("PLUVIA_BROKER", "192.168.100.10")
PORTA = 1883
BANCO = armazenamento.Banco()
ALTURA_CM = armazenamento.altura_montagem_cm()


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print("Conexao MQTT recusada:", reason_code)
        return
    print("Conectado ao broker:", reason_code)
    resultado, _ = client.subscribe([(TOPICO, 0), (TOPICO_CAMERA, 0)])
    if resultado != mqtt.MQTT_ERR_SUCCESS:
        print("Falha ao solicitar assinatura:", mqtt.error_string(resultado))
    else:
        print(f"Assinaturas solicitadas: {TOPICO} e {TOPICO_CAMERA}.")


def on_connect_fail(client, userdata):
    print(f"Nao foi possivel conectar a {BROKER}:{PORTA}. Tentando novamente.")


def on_message(client, userdata, msg):
    if mqtt.topic_matches_sub(TOPICO_CAMERA, msg.topic):
        salvar_imagem(msg)
        return
    try:
        dados = json.loads(msg.payload.decode("utf-8"))
        if not isinstance(dados, dict):
            raise ValueError("o payload deve ser um objeto JSON")
        sensor_id = dados.get("sensor_id")
        distancia = dados.get("distancia_cm")
        if not isinstance(sensor_id, str) or not sensor_id.strip():
            raise ValueError("sensor_id deve ser um texto nao vazio")
        if (
            isinstance(distancia, bool)
            or not isinstance(distancia, (int, float))
            or not 2 <= distancia <= 400
            or not math.isfinite(distancia)
        ):
            raise ValueError("distancia_cm deve ser um numero entre 2 e 400")
    except (UnicodeDecodeError, ValueError) as erro:
        print(f"Mensagem ignorada em {msg.topic}: {erro}")
        return

    ts = datetime.now().isoformat(timespec="seconds")
    try:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        with open(ARQUIVO, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if f.tell() == 0:
                w.writerow(["timestamp", "sensor_id", "distancia_cm"])
            w.writerow([ts, sensor_id, distancia])
    except OSError as erro:
        print(f"Erro ao salvar leitura em {ARQUIVO}: {erro}")
        return
    BANCO.gravar_leitura(sensor_id, distancia, altura_cm=ALTURA_CM)
    print(ts, dados)


def salvar_imagem(msg):
    # JPEG binario em topico proprio; nao tentar decodificar como JSON.
    if not msg.payload.startswith(b"\xff\xd8") or not msg.payload.endswith(b"\xff\xd9"):
        print(f"Imagem JPEG invalida em {msg.topic}")
        return
    if len(msg.payload) > 2 * 1024 * 1024:
        print("Imagem ignorada: limite de 2 MB excedido.")
        return
    sensor = msg.topic.split("/")[1]
    if not sensor or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in sensor):
        print("Identificador invalido no topico da camera.")
        return
    try:
        pasta = PASTA_IMAGENS / sensor
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg")
        destino.write_bytes(msg.payload)
        BANCO.gravar_foto(sensor, destino, len(msg.payload))
        print(f"Foto salva: {destino} ({len(msg.payload)} bytes)")
    except OSError as erro:
        print(f"Erro ao salvar foto: {erro}")


def main():
    logging.basicConfig(level=logging.WARNING)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.enable_logger()
    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    try:
        print(f"Conectando a {BROKER}:{PORTA}. CSV: {ARQUIVO}")
        client.connect_async(BROKER, PORTA)
        client.loop_forever(retry_first_connection=True)
    except KeyboardInterrupt:
        print("\nColetor encerrado.")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()