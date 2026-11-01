# ESP32-CAM do Pluvia

A placa mede o nível da água com um sensor ultrassônico, tira fotos do ponto monitorado e publica tudo por MQTT.
O `receptor.py` grava as leituras e as fotos e devolve o nível de risco (0–3), que a placa usa para acender o LED e
ajustar a frequência de leitura e de foto.

```
ESP32-CAM ──leitura (JSON) / foto (JPEG)──▶ broker MQTT ──▶ receptor.py ──▶ SQLite + fotos/
    ▲                                                            │
    └──────────────── risco (JSON, retido) ◀─────────────────────┘   (sensor + modelo do bairro)
```

## Tópicos

| Tópico | Sentido | Conteúdo |
|---|---|---|
| `pluvia/sensor/<id>/leitura` | placa → servidor | `{"ts", "distancia_cm", "nivel_agua_cm", "rssi", "uptime_s"}` (`ts`=0 se a placa ainda não tem hora) |
| `pluvia/sensor/<id>/foto` | placa → servidor | JPEG binário (640×480, ~20–40 KB) |
| `pluvia/sensor/<id>/status` | placa → servidor | `online` / `offline` (retido; `offline` é publicado pelo broker se a placa cair) |
| `pluvia/sensor/<id>/risco` | servidor → placa | `{"nivel", "nivel_sensor", "nivel_modelo", "intervalo_leitura_s", "intervalo_foto_s"}` (retido) |
| `pluvia/sensor/<id>/comando` | servidor → placa | `foto`: tira uma foto agora |

**Nível de risco** = o maior entre:
- `nivel_sensor`: quantos limiares de `limiares_cm` (em `sensores.json`) a água ultrapassou;
- `nivel_modelo`: o nível do `ModeloRisco` para o bairro do sensor **no dia**, usando a linha de hoje em
  `features_dia.csv` (colunas de `entrada_api` da ficha do modelo + `bairro` + `data`). Sem essa linha, o modelo
  fica de fora (`null`) e vale só a medida local. O CSV é recarregado sozinho quando muda.

| Nível | Leitura a cada | Foto a cada |
|---|---|---|
| 0 | 5 min | 30 min |
| 1 | 2 min | 10 min |
| 2 | 1 min | 5 min |
| 3 | 30 s | 2 min |

## Montagem

| Peça | Ligação na ESP32-CAM (AI-Thinker) |
|---|---|
| Sensor ultrassônico JSN-SR04T (à prova d'água) ou HC-SR04 | VCC → 5V, GND → GND, TRIG → GPIO13, ECHO → GPIO14 |
| Divisor no ECHO (se o sensor estiver em 5 V) | ECHO → 1 kΩ → GPIO14 → 2 kΩ → GND |
| Alimentação | 5 V / 2 A estável (com menos, a placa reinicia por *brownout* ao ligar Wi-Fi + câmera) |
| Gravação | adaptador USB-serial (FTDI) em U0R/U0T, com GPIO0 → GND durante a gravação |

O sensor fica apontado para baixo, sobre o canal ou a rua. Meça a distância até o fundo seco e coloque em
`ALTURA_SENSOR_CM`. O JSN-SR04T não mede abaixo de ~20 cm: monte-o pelo menos 20 cm acima do nível máximo esperado.
O cartão SD não é usado (GPIO13/14 são compartilhados com ele).

## Como rodar

1. **Broker** (no computador/servidor):
   ```bash
   brew install mosquitto
   ```
   ```bash
   mosquitto -c embarcado/mosquitto.conf
   ```
2. **Receptor**:
   ```bash
   pip install -r requirements-ml.txt -r embarcado/requirements-embarcado.txt
   ```
   ```bash
   cp embarcado/sensores.example.json embarcado/sensores.json
   ```
   Edite `sensores.json` (o `bairro` precisa ser escrito como na coluna `bairro` do dataset) e rode:
   ```bash
   python embarcado/receptor.py --config embarcado/sensores.json
   ```
3. **Firmware** (PlatformIO):
   ```bash
   cp embarcado/firmware/include/config.example.h embarcado/firmware/include/config.h
   ```
   Preencha Wi-Fi, IP do broker e `SENSOR_ID`, depois grave e abra o monitor serial:
   ```bash
   cd embarcado/firmware && pio run -t upload && pio device monitor
   ```

**Testar sem a placa:** com o broker e o receptor rodando,
```bash
python embarcado/simular_sensor.py --sensor esp32cam-01 --niveis 5 20 40 60
```

Dados gravados em `embarcado/dados/embarcado.db` (tabelas `leituras_sensor` e `fotos_sensor`, as mesmas do
`schema.sql`) e as fotos em `embarcado/dados/fotos/<sensor_id>/`.

## Limitações
- O nível medido é **local** (um ponto) e o modelo é **por bairro e dia**: os dois se complementam, mas a placa não
  substitui a previsão nem vice-versa.
- O `features_dia.csv` ainda não é gerado por nenhuma tarefa: ele é a saída esperada do DAG (chuva do dia +
  histórico por bairro). Até lá, só o nível medido entra no risco.
- MQTT sem TLS (porta 1883). Para expor o broker fora da rede local, use usuário/senha e TLS (porta 8883).
