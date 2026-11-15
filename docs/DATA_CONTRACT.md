# Contrato de dados v2 (alterado, 15/11)

O pipeline Python e o frontend só se encontram na pasta `web/data/`. O frontend é de outro integrante: ele lê apenas o que está descrito aqui e não precisa rodar Python. Mudou um campo? Suba `schema_version` e anote no fim deste arquivo.

## Visão geral

```
fontes (um módulo por fonte)        série padrão por fonte         modelo                 pacote para o frontend
nisar     water_series.py  ─┐
opera_dswx_hls  opera.py   ─┤──> data/series/<fonte>.csv ──> timeseries.py ──> web/data/manifest.json
s1_rtc / opera_dswx_s1     ─┤    (mesmas colunas)            (calibra p/ escala    web/data/series/*.json|csv
mapbiomas  mapbiomas.py    ─┘                                 NISAR + Prophet)      web/data/layers/*.png
```

Adicionar uma fonte = escrever um módulo que gere `data/series/<fonte>.csv` no formato abaixo e listá-la em `config/aoi.yaml` (`series.sources`). O modelo e o frontend não mudam.

## 1. Série padrão por fonte: `data/series/<fonte>.csv`

Uma linha por data observada (cena ou mosaico do dia; nunca média mensal aqui).

| Coluna | Tipo | Descrição |
|---|---|---|
| `date` | AAAA-MM-DD | data da aquisição |
| `source` | texto | `nisar`, `opera_dswx_hls`, `opera_dswx_s1`, `s1_rtc`, `mapbiomas` |
| `sensor` | texto | `NISAR L-band`, `HLS optical`, `Sentinel-1 C-band`, `Landsat` |
| `water_km2` | número | água aberta dentro do bbox da AOI |
| `water_partial_km2` | número ou vazio | água parcial/sob vegetação, quando a fonte separa |
| `valid_km2` | número | área com dado válido (sem nuvem, sem fill) |
| `valid_frac` | 0-1 | `valid_km2` / área do bbox |
| `method` | texto | ex.: `HH<-16.75dB`, `DSWx WTR=1`, `VV<-18dB` |
| `quality` | `ok` / `low` / `drop` | `drop` não entra no modelo; `low` entra com peso menor |
| `product` | texto | short name / coleção de origem |

Colunas extras são permitidas; o modelo ignora o que não conhece.

## 2. Pacote para o frontend: `web/data/`

### `manifest.json` (índice; o frontend lê só ele primeiro)

| Campo | Tipo | Descrição |
|---|---|---|
| `schema_version` | `2` | |
| `demo` | bool | `true` = mostrar aviso amarelo. **Nunca publicar `true`.** |
| `generated` | ISO 8601 UTC | |
| `aoi` | `{name, bbox:[oeste,sul,leste,norte], area_km2}` | |
| `sources[]` | `{id, label_pt, sensor, product, citation, n_obs, first, last}` | para legenda e créditos |
| `series` | `{observations, model, metrics}` | nomes dos arquivos em `series/` |
| `layers[]` | igual ao contrato v1 (`web/README.md`) + `source` (`nisar`…) | PNG em `layers/` |
| `dates` | lista AAAA-MM-DD | datas NISAR com camada de mapa |

### `series/observations.json` (e `.csv` igual)

Todas as fontes numa tabela longa, já na **escala NISAR** após calibração.

`{date, source, water_km2_raw, water_km2, water_km2_sd, quality}`

### `series/model.json` (e `.csv` igual)

Uma linha por data do eixo do gráfico.

| Campo | Descrição |
|---|---|
| `date` | |
| `kind` | `fit` (período observado) ou `forecast` (projeção) |
| `observed_km2` | valor NISAR do dia, ou `null` |
| `expected_km2`, `lo80_km2`, `hi80_km2` | saída do Prophet com intervalo de 80% |
| `anomaly` | `true` quando o observado cai fora do intervalo |
| `anomaly_km2`, `anomaly_pct` | observado menos esperado |
| `label_pt` | `"Observado"` (dentro do esperado), `"Anomalia"` (`anomaly: true`) ou `"Projeção"` (`kind: forecast`) |

### `series/metrics.json`

`{phase, calibration:{<fonte>:{a,b,r2,n,sd_km2,pairing}}, holdout:{mae_km2,mape_pct,n}, trend_km2_per_day, limitations_pt:[...]}`

## Regras

- Rótulos de origem: "Medido (NISAR)", "Observado (OPERA/Sentinel-1)", "Projeção (modelo)".
- Projeção sempre com faixa de incerteza e rótulo "Projeção".
- Todo arquivo é estático e servível pelo GitHub Pages.

## Histórico

- v1 (14/11): manifest de camadas e FIRMS (`web/README.md`).
- v2 (15/11): série multi-fonte, modelo e métricas; camadas em `layers/`.
