-- Esquema do banco (PostgreSQL 14+ com PostGIS). Atualizado em 20/10/2026 para refletir os dados reais.
-- ATENCAO: este SQL NAO foi executado em um PostgreSQL (nao ha banco no ambiente de desenvolvimento);
-- teste-o em um banco vazio antes de usar. A logica das views replica scripts/build_dataset.py e features_local.py.
--
-- Fluxo: ETL (Python) carrega as tabelas-base; as views calculam o dataset (unidade x dia) usado pelo modelo.
-- Unidade de analise = bairro/localidade da Defesa Civil (enderecos mascarados impedem ponto por rua).
CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------- metadados
CREATE TABLE fontes (
  fonte_id      text PRIMARY KEY,                  -- F01..F17 (ver fontes_de_dados.csv)
  nome          text NOT NULL,
  orgao         text,
  url           text,
  licenca       text,
  qualidade     text,                              -- resumo da avaliacao
  coletado_em   timestamptz
);

-- ---------------------------------------------------------------- geografia
CREATE TABLE bairros_oficiais (                    -- limites oficiais 2023 (F11), 94 bairros
  bairro_id     serial PRIMARY KEY,
  nome_oficial  text NOT NULL,
  nome_key      text NOT NULL UNIQUE,              -- minusculo, sem acento
  geom          geometry(Polygon, 4326) NOT NULL,
  area_km2      real
);
CREATE INDEX ON bairros_oficiais USING gist (geom);

CREATE TABLE unidades (                            -- unidade de analise = bairro/localidade como aparece na Defesa Civil
  unidade_id    serial PRIMARY KEY,
  nome_key      text NOT NULL UNIQUE,              -- chave de juncao com atendimentos (minusculo, sem acento)
  nome_exibicao text NOT NULL,
  regional      text,                              -- moda da regional por unidade (campo ausente em 2019-2022)
  bairro_id     int REFERENCES bairros_oficiais,   -- NULL: localidade sem bairro oficial (Ibura de Baixo, Iraque, UR 05)
  no_modelo     boolean NOT NULL DEFAULT false     -- true: >=1 registro de alagamento (78 unidades)
);
-- aliases usados na juncao: cohab -> "cohab - ibura de cima"; poco da panela -> "poco"

CREATE TABLE caracteristicas_bairro (              -- features estaticas (F11, F12, F14); uma linha por bairro oficial
  bairro_id            int PRIMARY KEY REFERENCES bairros_oficiais,
  lat_centro           real, lon_centro real,
  n_pontos_grade       int,                        -- grade de ~250 m; poucos pontos = altitude pouco confiavel
  alt_media_m          real, alt_mediana_m real, alt_min_m real, alt_max_m real,
  alt_desvio_m         real, alt_p10_m real,
  pct_pontos_abaixo_5m real,
  pct_area_faixa_marginal real,
  dist_faixa_media_m   real, dist_faixa_min_m real,
  hand_m               real,                       -- planejada (altura acima da drenagem), ainda nao calculada
  pct_area_impermeavel real,                       -- planejada
  densidade_vias       real,                       -- planejada
  eh_tunel             boolean                     -- planejada
);

-- ---------------------------------------------------------------- historico de alagamentos (F01)
CREATE TABLE atendimentos_defesa_civil (           -- 886.263 linhas, 2014-2024, ja normalizadas pelo parser
  atendimento_id   bigserial PRIMARY KEY,
  ano_arquivo      smallint NOT NULL,
  regional         text,
  data             date NOT NULL,                  -- se vazia no original, usa data_acao
  data_original_vazia boolean NOT NULL DEFAULT false,
  ocorrencia       text,                           -- Alagamentos | Imoveis Alagados | ...
  solicitacao      text,                           -- Monitoramento Alagado | Vistoria ... (acao de rotina)
  endereco_bruto   text,                           -- mascarado na origem; mantido so para auditoria
  bairro           text,
  localidade       text,
  bairro_key       text,                           -- normalizado pelo ETL (minusculo, sem acento)
  grau_risco       text,
  data_acao        date,
  tipo_acao        text,
  quantidade real, altura real, largura real, area_m2 real,
  flag_alag_amplo   boolean NOT NULL,              -- "alag" em ocorrencia OU solicitacao (preenchido pelo ETL)
  flag_alag_estrito boolean NOT NULL,              -- "alag" so em ocorrencia
  fonte_id         text REFERENCES fontes DEFAULT 'F01'
);
CREATE INDEX ON atendimentos_defesa_civil (bairro_key, data);
CREATE INDEX ON atendimentos_defesa_civil (data) WHERE flag_alag_amplo;

-- ---------------------------------------------------------------- chuva (F02 hoje; F03/F04 quando houver)
CREATE TABLE estacoes (
  estacao_id  serial PRIMARY KEY,
  fonte_id    text REFERENCES fontes,
  codigo      text NOT NULL,                       -- ex. A301 (INMET Recife)
  tipo        text CHECK (tipo IN ('chuva','mare','sensor')),
  geom        geometry(Point, 4326),
  UNIQUE (fonte_id, codigo)
);

CREATE TABLE observacoes_chuva (
  estacao_id  int REFERENCES estacoes,
  ts_utc      timestamptz NOT NULL,                -- INMET entrega em UTC
  precip_mm   real,                                -- NULL quando -9999/vazio na origem
  PRIMARY KEY (estacao_id, ts_utc)
);
-- A301: utilizavel em 2014-2021; 100% faltante em 2022-2023; ausente em 2024-2025.

-- ---------------------------------------------------------------- mare (F17: previsao harmonica; observada nao existe para 2014+)
CREATE TABLE mare_prevista (
  ts_utc      timestamptz PRIMARY KEY,
  altura_m    real NOT NULL                        -- anomalia (media = 0); sem mare meteorologica
);

-- ---------------------------------------------------------------- saidas e validacao
CREATE TABLE previsoes (
  previsao_id   bigserial PRIMARY KEY,
  unidade_id    int REFERENCES unidades,
  gerada_em     timestamptz NOT NULL,
  data_alvo     date NOT NULL,
  rotulo        text NOT NULL CHECK (rotulo IN ('amplo','estrito')),
  probabilidade real CHECK (probabilidade BETWEEN 0 AND 1),
  nivel_risco   smallint CHECK (nivel_risco BETWEEN 0 AND 3),
  modelo_versao text
);

CREATE TABLE leituras_sensor (                     -- ESP32-CAM via MQTT (embarcado/receptor.py)
  leitura_id    bigserial PRIMARY KEY,
  sensor_id     text NOT NULL,
  unidade_id    int REFERENCES unidades,
  ts_utc        timestamptz NOT NULL,
  nivel_agua_cm real,                              -- altura de montagem - distancia medida
  distancia_cm  real,                              -- leitura bruta do ultrassom
  rssi          smallint,                          -- sinal Wi-Fi (dBm)
  nivel_risco   smallint CHECK (nivel_risco BETWEEN 0 AND 3)   -- maior entre o medido e o previsto, enviado a placa
);

CREATE TABLE fotos_sensor (                        -- JPEG da ESP32-CAM; o arquivo fica em disco/objeto, aqui so o caminho
  foto_id       bigserial PRIMARY KEY,
  sensor_id     text NOT NULL,
  ts_utc        timestamptz NOT NULL,
  caminho       text NOT NULL,
  bytes         int NOT NULL
);

-- ================================================================ VIEWS (dataset de ML)
-- Dia local = America/Recife (UTC-3, sem horario de verao).

-- eventos por unidade e dia
CREATE VIEW eventos_unidade_dia AS
SELECT u.unidade_id, a.data,
       count(*) FILTER (WHERE a.flag_alag_amplo)   AS n_amplo,
       count(*) FILTER (WHERE a.flag_alag_estrito) AS n_estrito
FROM atendimentos_defesa_civil a
JOIN unidades u ON u.nome_key = a.bairro_key
WHERE a.flag_alag_amplo
GROUP BY u.unidade_id, a.data;

-- chuva por dia local (estacao A301)
CREATE VIEW chuva_dia AS
SELECT (o.ts_utc AT TIME ZONE 'America/Recife')::date AS data,
       sum(o.precip_mm)  AS chuva_mm,
       count(o.precip_mm) AS horas_validas,
       max(o.precip_mm)  AS chuva_max_1h
FROM observacoes_chuva o JOIN estacoes e USING (estacao_id)
WHERE e.codigo = 'A301'
GROUP BY 1;

-- hora de maior chuva de cada dia local (para a mare no pico)
CREATE VIEW hora_pico_chuva AS
SELECT DISTINCT ON (d) d AS data, ts_utc
FROM (SELECT (o.ts_utc AT TIME ZONE 'America/Recife')::date AS d, o.ts_utc, o.precip_mm
      FROM observacoes_chuva o JOIN estacoes e USING (estacao_id)
      WHERE e.codigo = 'A301' AND o.precip_mm > 0) x
ORDER BY d, precip_mm DESC;

-- features de chuva, mare e calendario por dia (iguais para todas as unidades)
CREATE VIEW features_dia AS
WITH cal AS (
  SELECT g::date AS data FROM generate_series('2014-01-01'::date, '2021-12-31'::date, interval '1 day') g
), c AS (
  SELECT cal.data, cd.chuva_mm, coalesce(cd.horas_validas, 0) AS hv, cd.chuva_max_1h
  FROM cal LEFT JOIN chuva_dia cd USING (data)
), j AS (
  SELECT data, chuva_mm, hv, chuva_max_1h,
    -- janela de n dias terminando no dia anterior; vale se >= 50% das horas existirem
    sum(coalesce(chuva_mm,0)) OVER w1  AS s1,  sum(hv) OVER w1  AS h1,
    sum(coalesce(chuva_mm,0)) OVER w3  AS s3,  sum(hv) OVER w3  AS h3,
    sum(coalesce(chuva_mm,0)) OVER w7  AS s7,  sum(hv) OVER w7  AS h7,
    sum(coalesce(chuva_mm,0)) OVER w15 AS s15, sum(hv) OVER w15 AS h15,
    sum(coalesce(chuva_mm,0)) OVER w30 AS s30, sum(hv) OVER w30 AS h30
  FROM c
  WINDOW w1  AS (ORDER BY data ROWS BETWEEN 1  PRECEDING AND 1 PRECEDING),
         w3  AS (ORDER BY data ROWS BETWEEN 3  PRECEDING AND 1 PRECEDING),
         w7  AS (ORDER BY data ROWS BETWEEN 7  PRECEDING AND 1 PRECEDING),
         w15 AS (ORDER BY data ROWS BETWEEN 15 PRECEDING AND 1 PRECEDING),
         w30 AS (ORDER BY data ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING)
), m AS (
  SELECT (ts_utc AT TIME ZONE 'America/Recife')::date AS data,
         max(altura_m) AS mx, min(altura_m) AS mn, count(*) AS n
  FROM mare_prevista GROUP BY 1
), lua AS (
  SELECT data,
    (mod(extract(epoch FROM (data::timestamp + interval '12 hours' - timestamp '2000-01-06 18:14'))::numeric / 86400,
         29.530588853) / 29.530588853) AS f
  FROM cal
)
SELECT j.data,
  CASE WHEN j.hv >= 12 THEN j.chuva_mm END                 AS chuva_dia_mm,
  CASE WHEN j.hv >= 12 THEN j.chuva_max_1h END             AS chuva_max_1h_mm,
  j.hv                                                     AS horas_validas_dia,
  CASE WHEN j.h1  >= 12      THEN round(j.s1::numeric,1)  END AS chuva_d1_mm,
  CASE WHEN j.h3  >= 12*3    THEN round(j.s3::numeric,1)  END AS chuva_ult3d_mm,
  CASE WHEN j.h7  >= 12*7    THEN round(j.s7::numeric,1)  END AS chuva_ult7d_mm,
  CASE WHEN j.h15 >= 12*15   THEN round(j.s15::numeric,1) END AS chuva_ult15d_mm,
  CASE WHEN j.h30 >= 12*30   THEN round(j.s30::numeric,1) END AS chuva_ult30d_mm,
  extract(month FROM j.data)::int                          AS mes,
  sin(2*pi()*extract(doy FROM j.data)/365.25)              AS dia_do_ano_sin,
  cos(2*pi()*extract(doy FROM j.data)/365.25)              AS dia_do_ano_cos,
  round(lua.f::numeric,3)                                  AS fase_lunar,
  (least(lua.f, abs(lua.f-0.5), 1-lua.f) < 0.07)::int      AS sizigia,
  CASE WHEN m.n = 24 THEN m.mx END                         AS mare_max_dia_m,
  CASE WHEN m.n = 24 THEN m.mn END                         AS mare_min_dia_m,
  CASE WHEN m.n = 24 THEN m.mx - m.mn END                  AS mare_amp_dia_m,
  mp.altura_m                                              AS mare_na_hora_pico_chuva_m,
  (mp1.altura_m > mp.altura_m)::int                        AS mare_subindo_na_hora_pico
FROM j
JOIN lua USING (data)
LEFT JOIN m USING (data)
LEFT JOIN hora_pico_chuva hp USING (data)
LEFT JOIN mare_prevista mp  ON mp.ts_utc  = hp.ts_utc
LEFT JOIN mare_prevista mp1 ON mp1.ts_utc = hp.ts_utc + interval '1 hour';

-- dataset final: unidade x dia, rotulos (amplo e estrito), historico SEM vazamento (so dias anteriores), local e dia
CREATE VIEW dataset_ml_unidade_dia AS
WITH spine AS (
  SELECT u.unidade_id, f.data FROM unidades u CROSS JOIN features_dia f WHERE u.no_modelo
), e AS (
  SELECT s.unidade_id, s.data,
         coalesce(ev.n_amplo, 0)   AS n_amplo,
         coalesce(ev.n_estrito, 0) AS n_estrito
  FROM spine s LEFT JOIN eventos_unidade_dia ev USING (unidade_id, data)
), h AS (
  SELECT unidade_id, data, n_amplo, n_estrito,
    coalesce(sum((n_amplo>0)::int)   OVER w365, 0) AS n_alag_unidade_365d,
    coalesce(sum((n_estrito>0)::int) OVER w365, 0) AS n_alag_estrito_unidade_365d,
    data - max(CASE WHEN n_amplo>0   THEN data END) OVER wall AS dias_desde_ultimo_alag,
    data - max(CASE WHEN n_estrito>0 THEN data END) OVER wall AS dias_desde_ultimo_alag_estrito
  FROM e
  WINDOW w365 AS (PARTITION BY unidade_id ORDER BY data ROWS BETWEEN 365 PRECEDING AND 1 PRECEDING),
         wall AS (PARTITION BY unidade_id ORDER BY data ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
), cidade AS (                                      -- unidades com alagamento (amplo) por dia
  SELECT data, count(*) FILTER (WHERE n_amplo>0) AS n_unidades FROM e GROUP BY data
)
SELECT u.nome_exibicao AS bairro, u.regional, h.data,
  (h.n_amplo>0)::int   AS alagou,   h.n_amplo   AS n_registros_alag,          -- n_registros_*: NAO usar como feature
  (h.n_estrito>0)::int AS alagou_estrito, h.n_estrito AS n_registros_alag_estrito,
  fd.chuva_dia_mm, fd.chuva_max_1h_mm, fd.horas_validas_dia,
  fd.chuva_d1_mm, fd.chuva_ult3d_mm, fd.chuva_ult7d_mm, fd.chuva_ult15d_mm, fd.chuva_ult30d_mm,
  h.n_alag_unidade_365d AS n_alag_bairro_365d, h.dias_desde_ultimo_alag,
  coalesce(cprev.n_unidades, 0) AS n_bairros_alag_dia_anterior,
  h.n_alag_estrito_unidade_365d AS n_alag_estrito_bairro_365d, h.dias_desde_ultimo_alag_estrito,
  fd.mes, fd.dia_do_ano_sin, fd.dia_do_ano_cos, fd.fase_lunar, fd.sizigia,
  fd.mare_max_dia_m, fd.mare_min_dia_m, fd.mare_amp_dia_m, fd.mare_na_hora_pico_chuva_m, fd.mare_subindo_na_hora_pico,
  b.area_km2, cb.lat_centro, cb.lon_centro, cb.n_pontos_grade,
  cb.alt_media_m, cb.alt_mediana_m, cb.alt_min_m, cb.alt_max_m, cb.alt_desvio_m, cb.alt_p10_m,
  cb.pct_pontos_abaixo_5m, cb.pct_area_faixa_marginal, cb.dist_faixa_media_m, cb.dist_faixa_min_m,
  (cb.bairro_id IS NOT NULL)::int AS local_casado
FROM h
JOIN unidades u ON u.unidade_id = h.unidade_id
JOIN features_dia fd ON fd.data = h.data
LEFT JOIN cidade cprev ON cprev.data = h.data - 1
LEFT JOIN bairros_oficiais b ON b.bairro_id = u.bairro_id
LEFT JOIN caracteristicas_bairro cb ON cb.bairro_id = u.bairro_id;

-- Conferencia apos carregar: a view deve ter 227.916 linhas (78 unidades x 2.922 dias), 314 alagou=1 e 162 alagou_estrito=1,
-- como em processed/dataset_ml_bairro_dia_completo.csv.
