# Integração embarcado ↔ machine learning

Este documento descreve como a parte embarcada (ESP32-CAM + ultrassom) e a parte de ML se conectam hoje.

## Visão geral

```
HC-SR04 (GPIO14/15) --2s--> ESP32-CAM --JSON--> pluvia/<sensor>/leituras --+
OV2640 --10s--> JPEG 320x240 ------------------> pluvia/<sensor>/camera  --+
                                                                           v
                                                  Mosquitto :1883 -> embarcado/coletor.py
                                                      |-> embarcado/dados/leituras.csv
                                                      |-> embarcado/dados/imagens/<sensor>/*.jpg
                                                      '-> PostgreSQL (opcional: leituras_sensor, fotos_sensor)
                                                                  |
                                              src/alerta.py <-----'  (lê o leituras.csv)
                                                   ^
   Defesa Civil/INMET/mapas -> preparacao.py -> modelo.py -> ModeloRisco (previsão por bairro)
                                                   |
                                         alerta combinado (nível 0-3)
```

## Componentes

### 1. Firmware (`embarcado/firmware/`)
- A cada 2 s lê a distância do ultrassom (aceita 2 a 400 cm) e publica `{"sensor_id": "PLUVIA_01", "distancia_cm": 12.34}` em `pluvia/sensor01/leituras`.
- A cada 10 s publica um JPEG binário em `pluvia/sensor01/camera`.
- Wi-Fi e broker vêm de `include/secrets.h` (ignorado pelo git).

### 2. Coletor (`embarcado/coletor.py`)
- Assina `pluvia/+/leituras` e `pluvia/+/camera` no broker definido por `PLUVIA_BROKER`.
- Valida cada mensagem e grava:
  - leituras em `embarcado/dados/leituras.csv` (`timestamp,sensor_id,distancia_cm`), com a hora local do computador coletor;
  - fotos em `embarcado/dados/imagens/<sensor>/`.
- Se `PLUVIA_DB_URL` estiver definida, grava também em `leituras_sensor` e `fotos_sensor` por meio de `embarcado/armazenamento.py`. Se `PLUVIA_ALTURA_CM` estiver definida, preenche `nivel_agua_cm` (altura − distância). Falha no banco não interrompe o CSV nem as fotos.

### 3. Modelo de risco (`src/preparacao.py`, `src/modelo.py`)
- `ModeloRisco` estima a probabilidade de alagamento por bairro e dia. Usa chuva (do dia e acumulada), maré, altitude, faixa marginal, histórico e propensão do bairro.
- Devolve probabilidade (`prever`) e nível de risco 0 a 3 (`nivel`).
- É treinado com dados históricos de 2014 a 2021. **Não usa nenhum dado do sensor.**

### 4. Alerta combinado (`src/alerta.py`)
- `ultima_leitura` lê a última linha válida do `leituras.csv` (filtrável por sensor). Descarta a leitura se tiver mais de 10 min.
- `nivel_sensor` converte o nível da água (altura de montagem − distância) em nível 0 a 3, com `LIMIARES_AGUA_CM = (5, 15, 30)`.
- `avaliar` devolve o **maior** entre o nível do modelo e o do sensor, mais a origem (`modelo` ou `sensor`), a probabilidade, o nível da água e a leitura usada.

Exemplo de uso:

```python
import joblib, pandas as pd
from alerta import avaliar          # com src/ no sys.path

modelo = joblib.load("modelos/risco_alagamento.joblib")
entrada = pd.DataFrame([{...colunas de entrada_api, incluindo "bairro"...}])
r = avaliar(modelo, entrada, altura_montagem_cm=100)
# {"nivel": 3, "origem": "sensor", "probabilidade_modelo": 0.1, "nivel_modelo": 0,
#  "nivel_sensor": 3, "nivel_agua_cm": 30.0, "leitura": {...}}
```

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `PLUVIA_BROKER` | IP do broker Mosquitto (padrão `192.168.100.10`) |
| `PLUVIA_DB_URL` | URL do PostgreSQL; sem ela, só CSV e JPEGs |
| `PLUVIA_ALTURA_CM` | Altura de montagem do sensor, para calcular `nivel_agua_cm` |

## O que a integração faz e o que não faz

- O sensor **não é feature** do modelo. Não há histórico de leituras para treinar, então a combinação é uma regra (máximo dos dois níveis), sem retreino.
- A integração é por **biblioteca**: `avaliar` precisa ser chamada por quem tem as features do bairro e do dia. Não há API de inferência, DAG do Airflow nem serviço que chame `avaliar` periodicamente.
- As **fotos** só são armazenadas. Nenhum código as analisa.
- O alerta lê o **CSV**, não o Postgres. O banco guarda o histórico, mas nada o consulta ainda.
- Os limiares de nível da água são **provisórios** e precisam de calibração com a instalação real.
- Segurança: o Mosquitto está anônimo e sem TLS.

## Pendências conhecidas

- O `schema.sql` nunca foi executado em um PostgreSQL de verdade. Teste-o em um banco vazio.
- `sensor_id` do payload (`PLUVIA_01`) não casa com o nome no tópico (`sensor01`), então associar fotos a leituras exige um mapeamento.
- O timestamp vem do coletor, não da placa (o firmware não usa NTP).
- O IP padrão do broker difere entre `coletor.py` e o README do embarcado.
- Os testes do coletor (`embarcado/test_coletor.py`) precisam do `paho-mqtt` instalado.

## Testes

```bash
python -m unittest tests.test_alerta          # alerta combinado e gravação no banco (simulada)
python -m unittest embarcado/test_coletor.py  # requer paho-mqtt
```
