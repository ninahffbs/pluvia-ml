# Relatório de qualidade dos dados (gerado em 17/10/2026)

## Dataset de modelagem: `processed/dataset_ml_bairro_dia.csv`
- Granularidade: bairro × dia, 2014-01-01 a 2021-12-31. 227.916 linhas, 78 bairros com ao menos um alagamento registrado.
- Alvo `alagou`: 1 se há registro com "alag" em Ocorrência/Solicitação naquele bairro e dia. **314 positivos (0,14%)**: desbalanceamento extremo.
- Chuva: só a estação INMET A301 (um ponto para a cidade inteira, igual para todos os bairros).
- `chuva_dia_mm` e `chuva_max_1h_mm` são da própria data do rótulo: em produção virão de previsão. As colunas `chuva_d1/ult3d/ult7d/ult15d/ult30d` usam só dias anteriores.
- Colunas de histórico usam apenas eventos anteriores ao dia (sem vazamento).
- `fase_lunar`/`sizigia`: cálculo aproximado, substituto fraco da maré (não há maré observada pós-1968).

## Sinal chuva → alagamento (sanity check)
| Chuva do dia | Taxa de alagamento (bairro-dia) |
|---|---|
| ≥ 1 mm | 0,20% |
| ≥ 10 mm | 0,43% |
| ≥ 30 mm | 1,28% |
| ≥ 50 mm | 2,50% |

## Riscos para o ML
1. **Rótulo = registro administrativo, não alagamento real.** 43 dos 291 positivos com chuva medida ocorreram com 0 mm medido. Dias de chuva forte sem registro viram falsos negativos.
2. **Mudança de prática de registro:** pares positivos por ano: 85, 42, 32, 29, 63, 51, **10, 3**, 116, 67, 84 (2014–2024). Considere treinar com 2014–2019 ou incluir `ano` na análise.
3. **Sem coordenadas:** endereços mascarados; o ponto é o bairro/localidade. Há "bairros" que na verdade são localidades (ex.: "UR 02", córregos).
4. **Chuva recente ausente:** A301 inutilizável de 2022 em diante. Os rótulos de 2022–2024 existem em `atendimentos_defesa_civil.csv`, mas sem feature de chuva.
5. **Maré:** sem observação para o período. Pendente (Marinha/IOC/IBGE ou maré harmônica).
6. Sugestão de validação: divisão temporal (treino 2014–2018, teste 2019–2021), métricas PR-AUC/recall, não acurácia.

## Maré (atualização 19/10/2026)
- Nenhuma fonte liberada tem maré **observada** para 2014–2021: UHSLC Recife termina em 1968; IOC Tamandaré começa em 2025-09; IBGE RMPG não tem Recife; Open-Meteo Marine começa em 2023.
- Solução: previsão astronômica por análise harmônica (32 constituintes) ajustada em 1955–1966 e validada em 1967–1968: RMSE 0,11 m, 96% da variância explicada (amplitude de M2 = 0,77 m).
- Arquivo: `processed/mare_prevista_horaria_recife_2014_2024.csv` (UTC, anomalia em metros, média zero).
- Features no dataset: `mare_max_dia_m`, `mare_min_dia_m`, `mare_amp_dia_m`, `mare_na_hora_pico_chuva_m`, `mare_subindo_na_hora_pico`.
- Limitação: não inclui maré meteorológica (ressaca) nem mudanças desde os anos 1960. Em dias com ≥30 mm, a taxa de alagamento foi 1,56% (maré baixa), 0,64% (média) e 1,52% (alta): **sem efeito monotônico claro** da maré neste nível de agregação. Não assumir que a maré é preditora forte sem testar no modelo.

## Variáveis de local (atualização 19/10/2026)
- Fontes: limites oficiais de bairros 2023 (94 bairros, GeoJSON WGS84), faixas marginais de recursos hídricos (81 multipolígonos), elevação Copernicus ~90 m via Open-Meteo em grade de ~250 m (3.577 pontos).
- Arquivos: `processed/caracteristicas_bairro.csv` (94 bairros) e `processed/dataset_ml_bairro_dia_completo.csv` (41 colunas, **este é o dataset final**).
- Cobertura da junção: 96,2% das linhas. Sem correspondência: "Ibura de Baixo", "Iraque", "UR 05" (localidades, não bairros oficiais). Aliases aplicados: Cohab → "Cohab - Ibura de Cima", Poço da Panela → "Poço". Coluna `local_casado` indica se há features.
- Bairros sem altitude: Totó e Ponto de Parada (pequenos demais para a grade de 250 m).
- Limitações: o DEM de 90 m tem erro vertical comparável ao relevo útil em área plana (mínimo observado -5 m); a altitude é média do bairro, não do ponto crítico; a distância à faixa marginal usa vértices dos polígonos (aproximação).
- **Atenção na interpretação:** em dias com ≥30 mm, a taxa de alagamento sobe com a altitude média (0,68% abaixo de 5 m; 1,32% em 5–10 m; 1,86% acima de 20 m), o contrário da expectativa física. Isso sugere que o rótulo reflete **onde a Defesa Civil atua e registra** (inclusive encostas), não apenas onde alaga. Essas features podem ajudar o modelo a prever *registro*, não alagamento. Vale testar rótulo restrito a "Alagamentos" e "Imóveis Alagados" (sem "Monitoramento/Vistoria") e a bairros de planície.

## Rótulo estrito vs. amplo (atualização 19/10/2026)
- `alagou` (amplo): "alag" em Ocorrência OU Solicitação → 314 pares bairro-dia. `alagou_estrito`: só campo Ocorrência (Alagamentos / Imóveis Alagados) → **162 pares**, 40 dos 78 bairros. Colunas de histórico estritas: `n_alag_estrito_bairro_365d`, `dias_desde_ultimo_alag_estrito`.
- Por ano (amplo/estrito): 2014 84/64, 2015 42/34, 2016 32/30, **2017 29/9, 2018 63/1**, 2019 51/17, 2020 10/5, 2021 3/2. O rótulo estrito praticamente não existe em 2018.
- Taxa por chuva do dia (amplo / estrito): <1 mm 0,06% / 0,02%; 10–30 mm 0,18% / 0,13%; 30–50 mm 0,48% / 0,15%; ≥50 mm 2,50% / 2,40%. O estrito é mais "limpo": quase todo o sinal está em dias ≥50 mm (73 dos 162 positivos).
- Faixa marginal tem o sinal esperado nos dois rótulos (0–1% da área: 0,36% estrito; ≥1%: ~1,1–1,2%).
- **Altitude: o paradoxo NÃO sumiu com o rótulo estrito** (dias ≥30 mm: <5 m = 0,27%; 5–10 m = 1,05%; ≥20 m = 1,59%). Logo o viés de registro não explica tudo. Hipótese mais provável: a altitude *média do bairro* é um mau indicador, pois bairros como Linha do Tiro (31,7 m) e Várzea (34,3 m) alagam em baixadas/canais dentro de áreas altas, enquanto bairros costeiros baixos têm boa drenagem. O que importa é a altitude *relativa à drenagem* (HAND) ou `alt_min`/`alt_desvio`, não a média.
- Recomendações: treinar com `alagou_estrito` e comparar com `alagou`; usar divisão temporal e avaliar com PR-AUC; considerar excluir 2018 do treino estrito; não interpretar a altitude média como causal.

## Modelagem (atualização 29/10/2026)
Os resultados completos estão nos notebooks `01_eda_preparacao.ipynb` e `02_modelagem_mlflow.ipynb` (com as saídas já executadas) e registrados no MLflow.
- **Dataset de modelagem:** `processed/dataset_modelagem.csv` (219.882 linhas após remover 3,5% sem chuva medida; 162 eventos estritos mantidos; 29 variáveis no cenário A e 25 no B, mais a propensão do bairro).
- **Eventos agrupados:** os 162 positivos caem em apenas 78 dias distintos (os 10 maiores dias concentram 40%; 10 bairros concentram 61%). O número efetivo de eventos independentes é menor que 162.
- **Validação por ano (cenário A):** logística PR-AUC 0,036 / recall@top5% 64%; floresta 0,020 / 64%; boosting 0,027 / 59%; referências sem ML: só chuva 0,020 / 51%, chuva × bairro 0,044 / 59%. Empate técnico entre a logística e "chuva × bairro".
- **Overfitting:** floresta e boosting decoram o treino (PR-AUC 0,24 e 0,48 no treino contra ~0,02–0,03 na validação); a logística não. O Apêndice A mostrou que árvores regularizadas reduzem o gap pela metade sem melhorar o teste.
- **Otimização (Optuna):** na busca (2014–2017) o boosting parecia o melhor (0,132) mas caiu para 0,015 no teste cronológico 2018–2021; a logística foi de 0,083 para 0,033. A estimativa honesta do modelo final é o teste cronológico (PR-AUC 0,033); o 0,057 da validação por ano é **otimista** (parâmetros escolhidos em parte dos mesmos anos).
- **Cenário B (sem a chuva do dia):** recall@top5% de ~60% (A: ~64%), mas PR-AUC cai de 0,057 para 0,020.
- **Curva de aprendizado:** a PR-AUC ainda sobe de 4 para 7 anos de treino (0,016 → 0,036): mais dados ajudariam.
- **Modelo registrado:** `risco_alagamento` e `risco_alagamento_cenario_B` (regressão logística), com alias `campeao`. A saída bruta é muito pequena (taxa base de 0,07%): exibir o **nível de risco (0–3)** e não a probabilidade em %.
