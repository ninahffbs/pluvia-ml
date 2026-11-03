// Teste simples da camera da ESP32-CAM (AI Thinker).
// Nao usa MQTT nem o sensor: so liga a camera e mostra uma foto no navegador.
// Abra no navegador o endereco que aparecer no Serial Monitor.

#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include "esp_camera.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

WebServer servidor(80);

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
    config.frame_size = FRAMESIZE_QVGA;   // 320x240
    config.jpeg_quality = 15;
    config.fb_count = 1;
    config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;

    esp_err_t erro = esp_camera_init(&config);
    if (erro != ESP_OK) {
        Serial.printf("ERRO: camera nao iniciou (codigo 0x%x)\n", erro);
        return false;
    }
    Serial.println("Camera iniciada.");
    return true;
}

// Pagina inicial: mostra a foto e um botao para tirar outra.
void paginaInicial() {
    servidor.send(200, "text/html",
        "<html><body style='font-family:sans-serif;text-align:center'>"
        "<h2>Teste da camera - Pluvia</h2>"
        "<img src='/foto' style='max-width:100%'><br><br>"
        "<button onclick='location.reload()'>Tirar outra foto</button>"
        "</body></html>");
}

// Tira uma foto e envia para o navegador.
void enviarFoto() {
    // A camera guarda a foto tirada logo depois da anterior.
    // Descartamos essa foto "velha" e pegamos uma nova.
    camera_fb_t* velha = esp_camera_fb_get();
    if (velha) esp_camera_fb_return(velha);

    camera_fb_t* foto = esp_camera_fb_get();
    if (!foto) {
        Serial.println("ERRO: falha ao capturar foto.");
        servidor.send(500, "text/plain", "Falha ao capturar foto");
        return;
    }
    Serial.printf("Foto capturada: %u bytes\n", (unsigned)foto->len);
    WiFiClient cliente = servidor.client();
    servidor.setContentLength(foto->len);
    servidor.send(200, "image/jpeg", "");
    cliente.write(foto->buf, foto->len);
    esp_camera_fb_return(foto);
}

void setup() {
    Serial.begin(9600);
    delay(500);
    Serial.println("\n--- Teste da camera ---");

    if (!iniciarCamera()) {
        Serial.println("Confira o cabo laranja da camera e a alimentacao.");
        return;
    }

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_SENHA);
    Serial.print("Conectando ao Wi-Fi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nWi-Fi conectado!");

    servidor.on("/", paginaInicial);
    servidor.on("/foto", enviarFoto);
    servidor.begin();

    Serial.print("Abra no navegador: http://");
    Serial.println(WiFi.localIP());
}

void loop() {
    servidor.handleClient();
}