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

Colunas opcionais usadas pelo modelo (alterado): `water_km2_lo`, `water_km2_hi` no `nisar.csv` (área com o limiar -1 dB e +1 dB, sensibilidade do método).

Opções por fonte em `config/aoi.yaml` (`series.sources[]`) (alterado): `filter` (`{coluna: [valores]}`, `min_<col>`, `max_<col>`, `exclude_ranges: [[início, fim]]`), `normalize_coverage: true` (água = fração `water_km2/valid_km2` × área do bbox) e `outlier: {window_days, min_ratio}` (descarta linhas abaixo de `min_ratio` × mediana móvel).

## 2. Pacote para o frontend: `web/data/`

### `manifest.json` (índice; o frontend lê só ele primeiro)

| Campo | Tipo | Descrição |
|---|---|---|
| `schema_version` | `2` | |
| `demo` | bool | `true` = mostrar aviso amarelo. **Nunca publicar `true`.** |
| `generated` | ISO 8601 UTC | |
| `aoi` | `{name, bbox:[oeste,sul,leste,norte], area_km2}` | |
| `sources[]` | `{id, label_pt, sensor, product, citation, n_obs, first, last, calibrated, skill}` | para legenda e créditos. `calibrated`: passou no portão de calibração para a escala NISAR; `skill`: ganho sobre a constante (abaixo) (alterado) |
| `series` | `{observations, model, metrics}` | nomes dos arquivos em `series/` |
| `forecast` | `{source, level_calibrated}` | fonte usada na previsão e se o nível em km² está calibrado (alterado) |
| `layers[]` | igual ao contrato v1 (`web/README.md`) + `source` (`nisar`…) | PNG em `layers/` |
| `dates` | lista AAAA-MM-DD | datas NISAR com camada de mapa |

### `series/observations.json` (e `.csv` igual)

Todas as fontes numa tabela longa. `water_km2_raw` na escala da própria fonte; `water_km2` na **escala NISAR** só quando a fonte passou no portão de calibração, senão `null` (alterado).

`{date, source, water_km2_raw, water_km2, water_km2_sd, calibrated, quality}`

### `series/model.json` (e `.csv` igual)

Uma linha por data do eixo do gráfico.

| Campo | Descrição |
|---|---|
| `date` | |
| `kind` | `fit` (período observado) ou `forecast` (projeção) |
| `observed_km2` | valor NISAR do dia, ou `null` |
| `expected_km2`, `lo80_km2`, `hi80_km2` | saída do Prophet; em `forecast`, intervalo de 80% e `null` quando `level_calibrated` é `false` (alterado) |
| `lo95_km2`, `hi95_km2` | só em `fit`: faixa esperada de 95% da detecção; em `fit`, `lo80_km2`/`hi80_km2` são `null` (alterado) |
| `method_lo_km2`, `method_hi_km2` | só em `fit`: área NISAR com o limiar -1 dB / +1 dB (incerteza de método); `null` se o `nisar.csv` não tiver as colunas (alterado) |
| `anomaly` | `true` quando o observado cai fora da faixa de 95% (alterado) |
| `anomaly_km2`, `anomaly_pct` | observado menos esperado |
| `label_pt` | `"Observado"` (dentro do esperado), `"Fora da faixa esperada (95%)"` (`anomaly: true`) ou `"Projeção"` (`kind: forecast`) (alterado) |
| `forecast_pct`, `lo80_pct`, `hi80_pct` | só em `forecast`: **saída principal da previsão**, trajetória do próprio modelo: `yhat(semana k) / yhat(data da última observação) - 1`, em %, com o IC80 calculado do mesmo jeito (alterado) |
| `expected_src_km2`, `lo80_src_km2`, `hi80_src_km2` | só em `forecast`: previsão na escala da própria fonte (alterado) |
| `forecast_source` | só em `forecast`: id da fonte usada (alterado) |
| `level_calibrated` | só em `forecast`: `true` se `expected_km2`/`lo80_km2`/`hi80_km2` vêm de calibração aprovada; `false` = nível aproximado por k proporcional com faixa larga, mostrar com aviso (alterado) |
| `check_same_direction` | só em `forecast`: `true` se a checagem independente (S1 T039, mesmo Prophet, mesma trajetória em %) aponta na mesma direção (sinal) da previsão; `null` sem checagem válida (a fonte de checagem precisa ter observações em todos os meses do horizonte em pelo menos 1 ano) (alterado) |

Linhas `fit` (alterado): só as datas NISAR. A detecção usa **só o NISAR** (tendência da própria série, sem sazonalidade anual); as outras fontes não entram no esperado.
Linhas `forecast` (alterado): Prophet com sazonalidade anual em `opera_dswx_hls` (fonte fixa: mesma definição de água aberta, amplitude sazonal mais próxima da cheia, mais dados), na escala dessa fonte. `s1_rtc` (só trilha T039) nunca é fonte da previsão; entra só como checagem independente. `expected_km2` pode ser `null` se não houver pares com o NISAR.

### `series/metrics.json`

`{phase, calibration:{<fonte>:{a,b,r2,n,sd_km2,pairing}}, holdout:{mae_km2,mape_pct,n}, trend_km2_per_day, limitations_pt:[...]}`

Campos novos (alterado):

| Campo | Descrição |
|---|---|
| `calibration.<fonte>` | só fontes aprovadas; ganhou `via`, `model` (`linear`/`proporcional`), `loo_mape_pct`, `loo_const_pct`, `skill`, `cv_target`, `k_ci95` |
| `calibration_tests.<fonte>` | teste de toda fonte, aprovada ou não: `{passed, model, coef, a, k_ci95, loo_mape_pct, loo_const_pct, skill, skill_ci95, n, cv_target, pairing, via, reason}` (`skill_ci95` alterado) |
| `skill.<fonte>` | `1 - LOO_fonte / LOO_constante` (constante = média dos outros pares) |
| `forecast_source`, `forecast_source_reason` | fonte da previsão e por que foi escolhida |
| `forecast_check` | checagem independente (alterado): `{source, valid, skipped, coverage, n_obs, last_obs, base_yhat_src, horizon_months, forecast_pct:[por semana], same_direction:[bool por semana] ou null, weeks:[{date, forecast_pct, lo80_pct, hi80_pct, main_pct, same_direction}], r_seasonal, r_seasonal_n_months}`; `r_seasonal` = correlação das médias mensais entre a fonte da previsão e a de checagem. Sem checagem: `{source: null, skipped}`. Checagem inválida: `weeks`, `forecast_pct` e `same_direction` = `null` (alterado) |
| `seasonal_comparison` | `{amplitude_rel:{fonte}, months_covered:{fonte}, coverage:{fonte:{complete, months, n_months, n_obs, years}}, criteria:{min_months_covered, min_years}, pairs:{"a~b":{corr_monthly, n_months, corr_climatology, n_months_of_year, conclusive, incomplete_sources}}}`. Série completa = observações usáveis em ≥ 10 dos 12 meses do ano, em ≥ 2 anos; par com fonte incompleta tem `conclusive: false` e não gera conclusão em `limitations_pt` (alterado) |
| `level_calibrated`, `level_method` | se o nível em km² da previsão é calibrado e como foi obtido |
| `forecast_base` | `{date, water_km2_src, kind, variant, observed_median_15d, observed_n_15d}`: base do `forecast_pct` = `yhat` do modelo na data da última observação (`water_km2_src`); a mediana observada dos últimos 15 dias fica só como referência (alterado) |
| `forecast_variants` | holdout dos últimos 90 dias para cada forma de treino (`obs` = observações individuais, `composto15` = medianas de 15 dias): `{n_train, alvo_composto:{mae_km2, mape_pct, n, coverage80}, alvo_obs:{...}}` (alterado) |
| `forecast_variant`, `forecast_variant_reason` | forma escolhida: menor MAPE no alvo composto entre as que cobrem ≥ 60% com o IC80 (alterado) |
| `forecast_holdout` | o item de `forecast_variants` da forma escolhida (alterado) |
| `holdout` | agora é da detecção (últimas 2 datas NISAR) |
| `detection_interval` | 0,95 (alterado) |
| `detection_chance` | `{n, k_outside, p_outside_each, expected_outside, p_at_least_k, note_pt}`: probabilidade binomial de ≥ k pontos fora da faixa por acaso (alterado) |
| `detection_sensitivity` | `{central, lo, hi: {column, trend_km2_per_day, outside:[datas]}}` (alterado) |
| `trend_range_km2_per_day` | `{min, central, max, available}` entre os limiares (alterado) |
| `outside_all_thresholds` | datas fora da faixa nos três limiares, ou `null` sem sensibilidade (alterado) |
| `data_notes` | por fonte: `normalize_coverage.full_area_km2` e `outliers_dropped {rule, dates}` (alterado) |
| `forecast_interval` | `{nominal, coverage_holdout_prophet, n_holdout, scale, note_pt}`: a meia-largura do Prophet é multiplicada por `scale` para a cobertura no holdout ficar no nível nominal (alterado) |

Portão de calibração (`config/aoi.yaml`, `series.calibration_gate`) (alterado): n ≥ 8, coeficiente > 0, LOO MAPE ≤ 25%, skill ≥ 0,10 e limite inferior do IC95 do skill (bootstrap dos erros LOO pareados) > 0. R² não é usado (o NISAR só cobre a seca).

## Regras

- Rótulos de origem: "Medido (NISAR)", "Observado (OPERA/Sentinel-1)", "Projeção (modelo)".
- Projeção sempre com faixa de incerteza e rótulo "Projeção".
- Todo arquivo é estático e servível pelo GitHub Pages.

## Histórico

- v1 (14/11): manifest de camadas e FIRMS (`web/README.md`).
- v2 (15/11): série multi-fonte, modelo e métricas; camadas em `layers/`.
- v2, campos adicionados (15/11) (alterado): detecção só NISAR; previsão na escala da fonte com `forecast_pct`; portão com skill; `forecast` no manifest; `calibrated`/`skill` em `sources[]` e `observations`. Só acréscimos e `water_km2` pode ser `null`, por isso `schema_version` continua `2`.
