"""Simula uma ESP32-CAM: publica leituras de nivel (e uma foto, se houver JPEG) e mostra o risco devolvido.

Serve para testar o receptor sem a placa.
Uso:  python embarcado/simular_sensor.py --sensor esp32cam-01 --niveis 5 20 40 60 --foto exemplo.jpg
"""
import argparse
import json
import time

import paho.mqtt.client as mqtt

PREFIXO = "pluvia/sensor"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--porta", type=int, default=1883)
    ap.add_argument("--sensor", default="esp32cam-01")
    ap.add_argument("--altura", type=float, default=150.0, help="altura do sensor acima do fundo (cm)")
    ap.add_argument("--niveis", type=float, nargs="+", default=[5, 20, 40, 60], help="niveis de agua a enviar (cm)")
    ap.add_argument("--foto", help="JPEG a publicar no topico de foto")
    ap.add_argument("--pausa", type=float, default=1.0)
    args = ap.parse_args()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"simulador-{args.sensor}")
    c.will_set(f"{PREFIXO}/{args.sensor}/status", "offline", qos=1, retain=True)
    c.on_message = lambda _c, _u, m: m.payload and print("  risco:", m.payload.decode())   # vazio = sem retido
    c.connect(args.host, args.porta)
    c.subscribe(f"{PREFIXO}/{args.sensor}/risco", qos=1)
    c.loop_start()
    c.publish(f"{PREFIXO}/{args.sensor}/status", "online", qos=1, retain=True)
    inicio = time.time()
    for nivel in args.niveis:
        leitura = {"ts": int(time.time()), "distancia_cm": args.altura - nivel, "nivel_agua_cm": nivel,
                   "rssi": -60, "uptime_s": int(time.time() - inicio)}
        print("leitura:", leitura)
        c.publish(f"{PREFIXO}/{args.sensor}/leitura", json.dumps(leitura), qos=1).wait_for_publish()
        time.sleep(args.pausa)
    if args.foto:
        with open(args.foto, "rb") as f:
            c.publish(f"{PREFIXO}/{args.sensor}/foto", f.read(), qos=0).wait_for_publish()
        print("foto enviada:", args.foto)
        time.sleep(args.pausa)
    c.loop_stop()
    c.disconnect()


if __name__ == "__main__":
    main()
