#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include "esp_camera.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

// AI Thinker ESP32-CAM, sem cartao microSD (GPIO14 e GPIO15 livres).
constexpr int TRIG_PIN = 14;
constexpr int ECHO_PIN = 15;
constexpr unsigned long INTERVALO_LEITURA = 2000;
constexpr unsigned long INTERVALO_FOTO = 10000;
const char* TOPICO = "pluvia/sensor01/leituras";
const char* TOPICO_CAMERA = "pluvia/sensor01/camera";
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
bool cameraPronta = false;
unsigned long ultimaLeitura = 0;
unsigned long ultimaFoto = 0;
unsigned long tentativaMQTT = 0;
unsigned long tentativaWiFi = 0;

bool iniciarCamera() {
    camera_config_t config = {};
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = 5;
    config.pin_d1 = 18;
    config.pin_d2 = 19;
    config.pin_d3 = 21;
    config.pin_d4 = 36;
    config.pin_d5 = 39;
    config.pin_d6 = 34;
    config.pin_d7 = 35;
    config.pin_xclk = 0;
    config.pin_pclk = 22;
    config.pin_vsync = 25;
    config.pin_href = 23;
    config.pin_sccb_sda = 26;
    config.pin_sccb_scl = 27;
    config.pin_pwdn = 32;
    config.pin_reset = -1;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = 15;
    config.fb_count = 1;
    config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
    esp_err_t erro = esp_camera_init(&config);
    if (erro != ESP_OK) {
        Serial.printf("Falha na camera: 0x%x. Ultrassom continuara ativo.\n", erro);
        return false;
    }
    Serial.println("Camera pronta: JPEG 320x240.");
    return true;
}

float medirDistancia() {
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(3);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);
    unsigned long duracao = pulseIn(ECHO_PIN, HIGH, 30000);
    float distancia = duracao * 0.0343f / 2.0f;
    return duracao && distancia >= 2 && distancia <= 400 ? distancia : -1;
}

void enviarFoto() {
    // A camera guarda a foto tirada logo depois da anterior (10 s atras).
    // Descartamos essa foto atrasada e capturamos uma nova.
    camera_fb_t* velha = esp_camera_fb_get();
    if (velha) esp_camera_fb_return(velha);

    camera_fb_t* foto = esp_camera_fb_get();
    if (!foto) {
        Serial.println("Falha ao capturar foto.");
        return;
    }
    // Transmissao em blocos sem reservar um buffer MQTT do tamanho da imagem.
    bool enviado = mqtt.beginPublish(TOPICO_CAMERA, foto->len, false);
    if (enviado) {
        size_t total = 0;
        while (total < foto->len) {
            size_t bloco = foto->len - total;
            if (bloco > 1024) bloco = 1024;
            size_t escritos = mqtt.write(foto->buf + total, bloco);
            if (escritos == 0) break;
            total += escritos;
            yield();
        }
        enviado = total == foto->len && mqtt.endPublish();
        // Um pacote incompleto exige fechar a conexao antes de enviar outro.
        if (!enviado) wifiClient.stop();
    }
    Serial.printf("Foto: %u bytes, %s\n", (unsigned)foto->len,
                  enviado ? "publicada" : "falha no envio");
    esp_camera_fb_return(foto);
}

void setup() {
    Serial.begin(9600);
    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    digitalWrite(TRIG_PIN, LOW);
    cameraPronta = iniciarCamera();
    mqtt.setServer(MQTT_BROKER, MQTT_PORT);
    mqtt.setBufferSize(256);
    mqtt.setSocketTimeout(3);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_SENHA);
    Serial.println("Conectando ao Wi-Fi. Confira include/secrets.h.");
}

void loop() {
    unsigned long agora = millis();
    if (WiFi.status() != WL_CONNECTED) {
        if (agora - tentativaWiFi >= 10000) {
            tentativaWiFi = agora;
            Serial.println("Wi-Fi desconectado. Tentando novamente.");
            WiFi.reconnect();
        }
        delay(10);
        return;
    }
    if (!mqtt.connected()) {
        if (agora - tentativaMQTT >= 3000) {
            tentativaMQTT = agora;
            String id = "PluviaESP32-" + String((uint32_t)ESP.getEfuseMac(), HEX);
            Serial.print("IP da placa: ");
            Serial.println(WiFi.localIP());
            Serial.printf("Conectando ao MQTT %s:%d...\n", MQTT_BROKER, MQTT_PORT);
            if (mqtt.connect(id.c_str())) Serial.println("MQTT conectado.");
            else Serial.printf("Falha MQTT: estado %d\n", mqtt.state());
        }
        delay(10);
        return;
    }
    mqtt.loop();
    if (agora - ultimaLeitura >= INTERVALO_LEITURA) {
        ultimaLeitura = agora;
        float distancia = medirDistancia();
        if (distancia >= 0) {
            char mensagem[160];
            snprintf(mensagem, sizeof(mensagem),
                     "{\"sensor_id\":\"PLUVIA_01\",\"distancia_cm\":%.2f}", distancia);
            bool enviado = mqtt.publish(TOPICO, mensagem);
            Serial.printf("%s - %s\n", mensagem, enviado ? "publicado" : "falha MQTT");
        } else {
            Serial.println("Ultrassom sem leitura valida: confira TRIG14/ECHO15 e alimentacao.");
        }
    }
    if (cameraPronta && mqtt.connected() && agora - ultimaFoto >= INTERVALO_FOTO) {
        ultimaFoto = agora;
        enviarFoto();
    }
    delay(2);
}