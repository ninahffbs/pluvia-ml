// Copie para config.h e preencha. config.h fica fora do git (tem a senha do Wi-Fi).
#pragma once

#define WIFI_SSID      "minha-rede"
#define WIFI_SENHA     "minha-senha"

#define MQTT_HOST      "192.168.0.10"     // IP do computador/servidor com o broker (Mosquitto)
#define MQTT_PORTA     1883
#define MQTT_USUARIO   ""                 // vazio = sem autenticacao
#define MQTT_SENHA     ""

#define SENSOR_ID      "esp32cam-01"      // precisa existir em embarcado/sensores.json

// Sensor ultrassonico (JSN-SR04T a prova d'agua ou HC-SR04) apontado para baixo, sobre o canal/rua.
#define PINO_TRIG      13
#define PINO_ECHO      14                 // sensor em 5 V: use divisor de tensao (ex.: 1k + 2k) no ECHO
#define ALTURA_SENSOR_CM  150.0f          // distancia do sensor ate o fundo seco; nivel = altura - distancia

// Intervalos usados ate o servidor mandar os dele (topico .../risco)
#define INTERVALO_LEITURA_S  300
#define INTERVALO_FOTO_S     1800
