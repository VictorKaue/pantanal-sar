# Tarefas do frontend (contrato v2) (alterado, 15/11)

Objetivo: o site deixa de ser "água e fogo" e passa a mostrar a água no tempo: mapa NISAR por data, detecção e projeção.

**Regras:** mexer só em `web/index.html`, `web/js/app.js` e `web/css/style.css`. Não alterar `web/data/` nem o Python. Referências: `web/README.md` (guia) e `docs/DATA_CONTRACT.md` (contrato v2). Os dados já são reais (`demo: false`). Testar com `python -m http.server -d web 8000`. Commit na branch do PR #1, nunca direto na main.

## 1. Remover o que não existe mais
- [ ] Checkbox "Focos de fogo", `firmsLayer`, `fetch` de `m.firms` e o filtro de focos em `draw()`.
- [ ] Seção "Água e fogo" (`#analysis`, `showAnalysis`) e a razão de chances.
- [ ] Do array `TYPES`: `flooded_veg`, `dried`, `burn`, `dried_then_burned`. Ficam `backscatter` e `open_water`.
- [ ] Texto "Mudanças entre X e Y" e a regra especial de `dried_then_burned`.
- [ ] Cards "Secou no período", "Queimada (NISAR)" e "Focos FIRMS".

## 2. Adaptar ao manifest v2
- [ ] `m.bbox` → `m.aoi.bbox`; nome em `m.aoi.name`.
- [ ] `SOURCE_LABEL[ex.source]` → `label_pt` de `m.sources` pelo `id` (tag "Medido (NISAR)").
- [ ] Camadas em `"data/" + l.file` com `l.bounds`; `open_water` por cima de `backscatter`. Legenda do radar com `value_range_db` (preto = -25 dB, branco = 0 dB).
- [ ] Aviso amarelo só quando `m.demo === true`.

## 3. Cards da data selecionada
Linha `kind: "fit"` daquela data em `series/model.json`:
- [ ] "Água aberta": `observed_km2`; abaixo, "`method_lo_km2`–`method_hi_km2` km² (limiar ±1 dB)".
- [ ] "Esperado": `expected_km2`, faixa `lo95_km2`–`hi95_km2`.
- [ ] Status: `label_pt` (hoje todas as datas saem "Observado").

## 4. Gráfico principal
- [ ] Carregar `"data/series/" + m.series.model`. `kind: "fit"` = 8 datas NISAR; `kind: "forecast"` = 4 semanas de projeção.
- [ ] Detecção (km²): ponto `observed_km2` com barra de erro `method_lo_km2`–`method_hi_km2`; linha `expected_km2` com faixa sombreada `lo95_km2`–`hi95_km2`.
- [ ] Destacar a data do slider; clicar num ponto troca a data do mapa.
- [ ] Projeção em painel separado, **em %**: `forecast_pct` com faixa `lo80_pct`–`hi80_pct`, rótulo "Projeção" e linha de 0%. Não converter para km² nem emendar na linha do NISAR (degrau falso, ver `docs/DATA_REVIEW.md`). Se `level_calibrated === false`, aviso "nível em km² não calibrado; variação relativa".
- [ ] Se `check_same_direction === true`: "Sentinel-1 indica a mesma direção (estável)".
- [ ] Sem bibliotecas novas: SVG à mão. Se usar biblioteca, só Chart.js via CDN com versão fixa, registrado em `THIRD_PARTY_LICENSES.md`.

## 5. Contexto histórico (opcional)
- [ ] Gráfico pequeno de `series/observations.json`: `water_km2_raw` por fonte (`opera_dswx_hls`, `s1_rtc`), 2023-2026, sem linhas `quality: "drop"`. Rótulo "Observado (OPERA/Sentinel-1)" e aviso de que a escala é a da própria fonte.

## 6. Painel "Limitações"
- [ ] `<details>` com a lista de `series/metrics.json` → `limitations_pt`.

## 7. Textos e créditos
- [ ] Título, `<title>` e meta description: "Pantanal: água no tempo" (ou similar).
- [ ] Subtítulo: "O radar NISAR mede a água aberta mesmo sob nuvem e fumaça." Não dizer "vê água sob a vegetação".
- [ ] "Sobre os dados": NISAR GCOV (provisório), OPERA DSWx-HLS, OPERA DSWx-S1, OPERA RTC-S1 (Sentinel-1); tirar FIRMS, MCD64A1 e HLS. DOIs no README.
- [ ] Atribuição do mapa: "OpenStreetMap | NISAR: NASA/ISRO, ASF DAAC | OPERA: NASA/JPL".
- [ ] Mensagem "Sem dados": trocar `cli export` por `python -m pantanal_sar.cli timeseries`.
- [ ] Nunca "anomalia"; usar "Fora da faixa esperada (95%)".

## 8. Aceite (até 12:00)
- [ ] Console sem erros; nenhuma requisição 404 na aba Network.
- [ ] Celular (painel embaixo) e desktop (painel à direita).
- [ ] 8 datas navegáveis por slider e setas do teclado.
- [ ] Funciona no subcaminho `/pantanal-sar/` do GitHub Pages (só caminhos relativos).

## Prioridade
Itens 1, 2 e 3 até 09:00 (mínimo para o site funcionar com dados reais). Depois 4, 6 e 7. O 5 só se sobrar tempo.
