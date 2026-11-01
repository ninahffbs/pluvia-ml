// Pluvia - ESP32-CAM (AI-Thinker): mede o nivel da agua, tira fotos e publica por MQTT.
// Contrato de topicos: ver embarcado/receptor.py.
#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "esp_camera.h"
#include "config.h"

// ---------------------------------------------------------------- pinos da camera (AI-Thinker)
#define PWDN_GPIO_NUM   32
#define RESET_GPIO_NUM  -1
#define XCLK_GPIO_NUM    0
#define SIOD_GPIO_NUM   26
#define SIOC_GPIO_NUM   27
#define Y9_GPIO_NUM     35
#define Y8_GPIO_NUM     34
#define Y7_GPIO_NUM     39
#define Y6_GPIO_NUM     36
#define Y5_GPIO_NUM     21
#define Y4_GPIO_NUM     19
#define Y3_GPIO_NUM     18
#define Y2_GPIO_NUM      5
#define VSYNC_GPIO_NUM  25
#define HREF_GPIO_NUM   23
#define PCLK_GPIO_NUM   22
#define PINO_LED        33               // LED vermelho da placa, ativo em nivel baixo

const String BASE = String("pluvia/sensor/") + SENSOR_ID;
const String T_LEITURA = BASE + "/leitura";
const String T_FOTO = BASE + "/foto";
const String T_STATUS = BASE + "/status";
const String T_RISCO = BASE + "/risco";
const String T_COMANDO = BASE + "/comando";

WiFiClient rede;
PubSubClient mqtt(rede);

bool cameraOk = false;
bool pedidoFoto = false;
int nivelRisco = 0;
uint32_t intervaloLeituraMs = INTERVALO_LEITURA_S * 1000UL;
uint32_t intervaloFotoMs = INTERVALO_FOTO_S * 1000UL;
uint32_t ultimaLeitura = 0, ultimaFoto = 0, ultimaTentativaMqtt = 0, semWifiDesde = 0;
bool primeiraLeitura = true, primeiraFoto = true;

// ---------------------------------------------------------------- camera
bool iniciarCamera() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM; c.pin_d1 = Y3_GPIO_NUM; c.pin_d2 = Y4_GPIO_NUM; c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM; c.pin_d5 = Y7_GPIO_NUM; c.pin_d6 = Y8_GPIO_NUM; c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM; c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM; c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM; c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM; c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.grab_mode = CAMERA_GRAB_LATEST;      // sempre a imagem mais recente, nao uma antiga do buffer
  if (psramFound()) {
    c.frame_size = FRAMESIZE_VGA;        // 640x480, ~20-40 KB em JPEG: cabe bem numa mensagem MQTT
    c.jpeg_quality = 12;
    c.fb_count = 2;
    c.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    c.frame_size = FRAMESIZE_QVGA;
    c.jpeg_quality = 15;
    c.fb_count = 1;
    c.fb_location = CAMERA_FB_IN_DRAM;
  }
  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) {
    Serial.printf("camera: falha ao iniciar (0x%x); seguindo so com o nivel\n", err);
    return false;
  }
  return true;
}

bool enviarFoto() {
  if (!cameraOk || !mqtt.connected()) return false;
  camera_fb_t *fb = esp_camera_fb_get();   // descarta um quadro: o primeiro apos ocioso sai escuro/velho
  if (fb) esp_camera_fb_return(fb);
  fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("camera: captura falhou");
    return false;
  }
  // publica em partes: o JPEG nao precisa caber no buffer do PubSubClient
  bool ok = mqtt.beginPublish(T_FOTO.c_str(), fb->len, false);
  size_t enviado = 0;
  while (ok && enviado < fb->len) {
    size_t n = min((size_t)1024, fb->len - enviado);
    ok = mqtt.write(fb->buf + enviado, n) == n;
    enviado += n;
  }
  ok = ok && mqtt.endPublish();
  Serial.printf("foto: %u bytes %s\n", (unsigned)fb->len, ok ? "enviada" : "FALHOU");
  esp_camera_fb_return(fb);
  return ok;
}

// ---------------------------------------------------------------- nivel da agua (ultrassom)
float medirDistanciaCm() {
  float v[5];
  int n = 0;
  for (int i = 0; i < 5; i++) {
    digitalWrite(PINO_TRIG, LOW);
    delayMicroseconds(4);
    digitalWrite(PINO_TRIG, HIGH);
    delayMicroseconds(20);               // JSN-SR04T pede pulso maior que o HC-SR04
    digitalWrite(PINO_TRIG, LOW);
    unsigned long us = pulseIn(PINO_ECHO, HIGH, 30000UL);   // 30 ms ~ 5 m
    if (us > 0) v[n++] = us / 58.0f;
    delay(60);                           // deixa o eco anterior morrer
  }
  if (n < 3) return NAN;                 // poucas medidas validas: melhor nao inventar
  for (int i = 1; i < n; i++)            // mediana (ordenacao por insercao)
    for (int j = i; j > 0 && v[j - 1] > v[j]; j--) { float t = v[j]; v[j] = v[j - 1]; v[j - 1] = t; }
  return v[n / 2];
}

void enviarLeitura() {
  float dist = medirDistanciaCm();
  JsonDocument doc;
  time_t agora = time(nullptr);
  doc["ts"] = agora > 1700000000 ? (long)agora : 0;   // 0 = sem NTP; o servidor usa a hora de chegada
  if (isnan(dist)) {
    doc["distancia_cm"] = nullptr;
    doc["nivel_agua_cm"] = nullptr;
  } else {
    doc["distancia_cm"] = roundf(dist * 10) / 10;
    doc["nivel_agua_cm"] = roundf(max(0.0f, ALTURA_SENSOR_CM - dist) * 10) / 10;
  }
  doc["rssi"] = WiFi.RSSI();
  doc["uptime_s"] = millis() / 1000;
  char buf[192];
  size_t len = serializeJson(doc, buf, sizeof(buf));
  bool ok = mqtt.publish(T_LEITURA.c_str(), (const uint8_t *)buf, len, false);
  Serial.printf("leitura: %s %s\n", buf, ok ? "" : "(FALHOU)");
}

// ---------------------------------------------------------------- MQTT
void aoReceber(char *topico, byte *payload, unsigned int len) {
  String t(topico);
  if (t == T_COMANDO) {
    if (len == 4 && memcmp(payload, "foto", 4) == 0) pedidoFoto = true;
    return;
  }
  if (t == T_RISCO) {
    JsonDocument doc;
    if (deserializeJson(doc, payload, len)) return;
    nivelRisco = doc["nivel"] | nivelRisco;
    intervaloLeituraMs = (doc["intervalo_leitura_s"] | (int)(intervaloLeituraMs / 1000)) * 1000UL;
    intervaloFotoMs = (doc["intervalo_foto_s"] | (int)(intervaloFotoMs / 1000)) * 1000UL;
    digitalWrite(PINO_LED, nivelRisco >= 2 ? LOW : HIGH);
    Serial.printf("risco: nivel %d, leitura a cada %us, foto a cada %us\n", nivelRisco,
                  (unsigned)(intervaloLeituraMs / 1000), (unsigned)(intervaloFotoMs / 1000));
  }
}

bool conectarMqtt() {
  const char *usuario = strlen(MQTT_USUARIO) ? MQTT_USUARIO : nullptr;
  const char *senha = strlen(MQTT_SENHA) ? MQTT_SENHA : nullptr;
  // testamento: se a placa cair, o broker publica "offline" no lugar dela
  if (!mqtt.connect(SENSOR_ID, usuario, senha, T_STATUS.c_str(), 1, true, "offline")) {
    Serial.printf("mqtt: falha (estado %d)\n", mqtt.state());
    return false;
  }
  mqtt.publish(T_STATUS.c_str(), "online", true);
  mqtt.subscribe(T_RISCO.c_str(), 1);
  mqtt.subscribe(T_COMANDO.c_str(), 1);
  Serial.println("mqtt: conectado");
  return true;
}

// ---------------------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(PINO_TRIG, OUTPUT);
  digitalWrite(PINO_TRIG, LOW);
  pinMode(PINO_ECHO, INPUT);
  pinMode(PINO_LED, OUTPUT);
  digitalWrite(PINO_LED, HIGH);

  cameraOk = iniciarCamera();

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                  // com o Wi-Fi dormindo, fotos grandes por MQTT perdem pacotes
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  Serial.print("wifi: conectando");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print("."); }
  if (WiFi.status() == WL_CONNECTED) Serial.println(" ok " + WiFi.localIP().toString());
  else Serial.println(" ainda nao (tenta de novo no loop)");

  configTime(0, 0, "a.st1.ntp.br", "pool.ntp.org");   // hora em UTC; o servidor converte para Recife
  mqtt.setServer(MQTT_HOST, MQTT_PORTA);
  mqtt.setCallback(aoReceber);
  mqtt.setBufferSize(512);               // mensagens recebidas (risco) e leituras; a foto vai em partes
  mqtt.setSocketTimeout(15);
  mqtt.setKeepAlive(60);
}

void loop() {
  uint32_t agora = millis();

  if (WiFi.status() != WL_CONNECTED) {
    if (semWifiDesde == 0) semWifiDesde = agora;
    if (agora - semWifiDesde > 5 * 60 * 1000UL) ESP.restart();   // 5 min sem rede: reinicia
    delay(200);
    return;
  }
  semWifiDesde = 0;

  if (!mqtt.connected()) {
    if (agora - ultimaTentativaMqtt > 5000) {
      ultimaTentativaMqtt = agora;
      conectarMqtt();
    }
    delay(50);
    return;
  }
  mqtt.loop();

  if (primeiraLeitura || agora - ultimaLeitura >= intervaloLeituraMs) {
    primeiraLeitura = false;
    ultimaLeitura = agora;
    enviarLeitura();
  }
  if (pedidoFoto || primeiraFoto || agora - ultimaFoto >= intervaloFotoMs) {
    pedidoFoto = primeiraFoto = false;
    ultimaFoto = agora;
    enviarFoto();
  }
  delay(10);
}
