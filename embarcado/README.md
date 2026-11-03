# Pluvia — ESP32-CAM e ultrassom

Configuracao preparada para **AI Thinker ESP32-CAM / OV2640**, conforme a placa `esp32cam` do PlatformIO.

Trazido do branch `camera` de [Sofia1653/Pluvia](https://github.com/Sofia1653/Pluvia/tree/camera) (commit `7a40e99`). O firmware fica em `embarcado/firmware/` (projeto PlatformIO) e o coletor em `embarcado/coletor.py`.

## Configurar e executar

1. Copie `embarcado/firmware/include/secrets.example.h` para `embarcado/firmware/include/secrets.h`.
2. Preencha o nome e a senha do Wi-Fi de 2,4 GHz. Configure `MQTT_BROKER` com o IPv4 do computador na mesma rede da placa. O exemplo usa `172.26.68.103`, observado nesta maquina; confira novamente com `ipconfig` se a rede mudar. Nao use `127.0.0.1` no ESP32.
3. Inicie o broker com `mosquitto -c embarcado/mosquitto.conf -v` (use apenas uma instancia na porta 1883). A rede precisa permitir acesso da placa ao computador nessa porta.
4. Compile e grave com PlatformIO, dentro de `embarcado/firmware`: `pio run -t upload`. Abra o Monitor Serial a **9600 baud**. O codigo imprime o resultado da camera, o IP, a conexao MQTT e cada envio.
5. Instale a dependencia Python, se necessario: `python -m pip install "paho-mqtt>=2,<3"`.
6. No computador do broker, execute `PLUVIA_BROKER=<ip do broker> python embarcado/coletor.py`. Reinicie o coletor se ele ja estava aberto antes da atualizacao.

`embarcado/firmware/include/secrets.h` ja esta ignorado pelo Git. Sem esse arquivo, o firmware compila com valores de exemplo e nao conectara ao Wi-Fi ate serem preenchidos.

## Ligacoes do ultrassom

O firmware preserva **TRIG no GPIO14** e **ECHO no GPIO15**, com GND comum. Esses pinos sao compartilhados com microSD: este projeto nao inicializa o cartao; use sem cartao inserido.

Se o sensor for HC-SR04 de 5 V, alimente conforme sua especificacao e use divisor resistivo/conversor para reduzir ECHO a 3,3 V antes do GPIO15. Por exemplo: ECHO → 1 kohm → GPIO15 → 2 kohm → GND. Nao conecte ECHO de 5 V diretamente ao ESP32. Use fonte estavel apropriada para a ESP32-CAM; resets durante fotos podem indicar alimentacao insuficiente.

## Dados recebidos

- A cada 2 segundos: JSON em `pluvia/sensor01/leituras`, com `sensor_id` e `distancia_cm`; gravado em `embarcado/dados/leituras.csv`.
- A cada 10 segundos: foto JPEG 320x240 em `pluvia/sensor01/camera`; gravada em `embarcado/dados/imagens/sensor01/`, com data e hora no nome. Sao fotos periodicas, sem streaming de video ou classificacao de imagem.
- Distancias fora de 2–400 cm ou sem eco sao descartadas e informadas no Serial. A camera continua enviando mesmo sem leitura valida do ultrassom.
- Se a camera nao inicializar, o ultrassom continua funcionando. Confira o cabo da camera/modelo da placa e reinicie apos corrigir.

As fotos se acumulam em disco; remova ou arquive conforme necessario. O timestamp e o horario local do computador coletor.

## Diagnostico

- `Wi-Fi desconectado`: confira credenciais, rede de 2,4 GHz e sinal.
- `Falha MQTT`: confira IP do broker, porta 1883, firewall e acesso entre os dispositivos.
- Coletor conectado, mas sem dados: confira no Serial se a placa informa `MQTT conectado` e `publicado`.
- `Ultrassom sem leitura valida`: confira pinos, alimentacao, divisor de ECHO e objeto dentro da faixa do sensor.

Referencias de implementacao: [CameraWebServer da Espressif](https://github.com/espressif/arduino-esp32/tree/master/libraries/ESP32/examples/Camera/CameraWebServer) e [API PubSubClient](https://pubsubclient.knolleary.net/api.html).

## Testes do coletor

```bash
python -m unittest embarcado/test_coletor.py
```

Para testar so a camera (pagina com foto no navegador): `pio run -e teste-camera -t upload`.
