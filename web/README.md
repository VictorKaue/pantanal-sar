# Frontend (web/) (alterado, 15/11)

Site estático (HTML, CSS e JS puros, sem build) que mostra os resultados do pipeline num mapa Leaflet.
Pode ser desenvolvido separado do Python: o único ponto de contato é a pasta `web/data/`.

**O contrato de dados oficial agora é o v2: [`docs/DATA_CONTRACT.md`](../docs/DATA_CONTRACT.md).** Este arquivo
resume o que o frontend precisa ler. Em caso de dúvida, vale o contrato. (alterado)

```
web/
  index.html      estrutura da página (do frontend)
  css/style.css   visual (do frontend)
  js/app.js       lógica (do frontend); ainda escrito para o contrato v1, ver abaixo
  data/           GERADO pelo pipeline e versionado no git (alterado):
    manifest.json             índice (ler primeiro)
    series/observations.json  todas as fontes, tabela longa (+ .csv igual)
    series/model.json         detecção e projeção para o gráfico (+ .csv igual)
    series/metrics.json       calibração, testes, limitações em português
    layers/*.png              camadas do mapa (NISAR: radar HH e água aberta)
```

## Rodar localmente

```bash
python -m http.server -d web 8000      # abrir http://localhost:8000
```
Abrir o `index.html` direto (file://) não funciona: o navegador bloqueia o `fetch`.
`web/data/` já vem com dados reais (`demo: false`); não é preciso rodar Python. (alterado)

## O que o `app.js` atual lê e não existe mais (alterado)

O foco do projeto mudou de "água e fogo" para **série temporal de área de água** (detecção e projeção).

| `app.js` lê hoje | Situação no v2 | O que usar |
|---|---|---|
| `data/firms.geojson`, `manifest.firms` | removido (FIRMS fora do escopo atual) | nada; esconder o controle "Focos FIRMS" |
| `manifest.stats` (`per_date`, `per_pair`, `analysis.dried_vs_always_dry`) | removido | números do gráfico vêm de `series/model.json`; a área de água de cada data também está na camada `open_water` (`water_km2`) |
| camadas `burn`, `dried`, `dried_then_burned`, `flooded_veg` | não existem | só `backscatter` e `open_water` |
| `layer.date_from` | não existe (não há camadas de mudança) | `layer.date` |
| `manifest.bbox`, `manifest.name` | movidos | `manifest.aoi.bbox`, `manifest.aoi.name` (e `aoi.area_km2`) |
| `layer.source` = `measured` / `derived` (`SOURCE_LABEL`) | agora é o id da fonte (`nisar`) | rótulo em `manifest.sources[].label_pt` do mesmo `id` ("Medido (NISAR)"); `layer.origin` = `measured` |
| `manifest.water_series`, `data/water_series.json` | removidos | `manifest.series.*` → `series/*.json` |

Continua igual: `manifest.demo`, `manifest.dates` (datas NISAR com camada), `layers[].file` relativo a `data/`
(agora com prefixo `layers/`, então `"data/" + file` continua funcionando) e `layers[].bounds` no formato do Leaflet.

## O que ler agora (alterado)

### `manifest.json`

| Campo | Uso |
|---|---|
| `schema_version` | `2` |
| `demo` | `true` = aviso amarelo. Os dados atuais são reais (`false`). |
| `aoi` | `{name, bbox:[oeste,sul,leste,norte], area_km2}`: enquadramento e retângulo da AOI |
| `sources[]` | `{id, label_pt, sensor, product, citation, n_obs, first, last, calibrated, skill}`: legenda e créditos. Ids atuais: `nisar`, `opera_dswx_hls`, `opera_dswx_s1`, `s1_rtc` |
| `series` | `{observations, model, metrics}`: nomes dos arquivos dentro de `series/` |
| `forecast` | `{source, level_calibrated}`: fonte da projeção e se o nível em km² é calibrado |
| `dates` | datas NISAR com camada de mapa (ordem crescente) |
| `layers[]` | camadas do mapa (abaixo) |

### `layers[]` e `layers/*.png`

Dois PNG transparentes por data NISAR, já em lon/lat e cobrindo exatamente o bbox:

| Campo | Exemplo | Observação |
|---|---|---|
| `id` | `2026-07-17_nisar_open_water` | |
| `type` | `backscatter` ou `open_water` | desenhar `open_water` por cima |
| `date` | `2026-07-17` | uma das `manifest.dates` |
| `source` / `origin` | `nisar` / `measured` | rótulo "Medido (NISAR)" |
| `label_pt`, `label_en` | `Água aberta (NISAR)` | legenda |
| `color` | `rgba(30,110,230,0.75)` | só `open_water` (o PNG já vem colorido) |
| `file` | `layers/2026-07-17_nisar_open_water.png` | relativo a `data/` |
| `bounds` | `[[-17.5, -58.3], [-16.5, -57.3]]` | `[[sul, oeste], [norte, leste]]`, formato do Leaflet |
| `value_range_db` | `[-25, 0]` | só `backscatter`: preto = -25 dB, branco = 0 dB |
| `method`, `water_km2` | `HH<-16.75dB`, `376.49` | só `open_water`: limiar usado e área de água da data |
| `resolution_deg` | `0.001` (HH) / `0.0005` (água) | tamanho do pixel; cada PNG de HH tem ~0,85 MB |

### `series/model.json` (gráfico principal)

Lista de objetos, um por data do eixo. `kind` separa os dois blocos:

- **`fit`** (datas NISAR observadas, detecção):
  `observed_km2` (ponto medido), `expected_km2` (esperado), `lo95_km2`/`hi95_km2` (faixa esperada de 95%),
  `method_lo_km2`/`method_hi_km2` (área com limiar -1 dB / +1 dB: incerteza do método, ex.: barra de erro do ponto),
  `anomaly` (`true` = fora da faixa de 95%), `anomaly_km2`, `anomaly_pct`.
- **`forecast`** (projeção semanal; sempre com o rótulo "Projeção"):
  **a saída principal é em %**: `forecast_pct` com `lo80_pct`/`hi80_pct` (variação em relação à última observação, IC 80%).
  `expected_km2`/`lo80_km2`/`hi80_km2` só valem quando `level_calibrated` é `true`; hoje são `null`, e o nível
  aproximado fica em `expected_src_km2`/`lo80_src_km2`/`hi80_src_km2` (escala da fonte `forecast_source`; mostrar com aviso).
  `check_same_direction`: `true` se a checagem independente (Sentinel-1) aponta na mesma direção.
- **`label_pt`**: texto pronto para tooltip e legenda: `"Observado"`, `"Fora da faixa esperada (95%)"` ou `"Projeção"`.

`null` aparece onde o campo não se aplica; trate como "sem valor".

### `series/observations.json` e `series/metrics.json`

- `observations`: `{date, source, water_km2_raw, water_km2, water_km2_sd, calibrated, quality}` de todas as fontes,
  para pontos de contexto no gráfico. `water_km2` está na escala NISAR, ou é `null` se a fonte não foi calibrada
  (use `water_km2_raw`, na escala da própria fonte). Linhas com `quality: "drop"` não devem ser mostradas como medida.
- `metrics.limitations_pt`: lista de frases em português para um painel "Limitações". Os demais campos estão no contrato.

## Exemplo mínimo (JS puro) (alterado)

```js
const base = "data/";
const m = await fetch(base + "manifest.json").then(r => r.json());
const [model, obs] = await Promise.all([
  fetch(base + "series/" + m.series.model).then(r => r.json()),
  fetch(base + "series/" + m.series.observations).then(r => r.json()),
]);

// mapa: camadas da última data, água por cima do radar
const [w, s, e, n] = m.aoi.bbox;
map.fitBounds([[s, w], [n, e]]);
const d = m.dates[m.dates.length - 1];
m.layers
  .filter(l => l.date === d)
  .sort((a, b) => (a.type === "open_water") - (b.type === "open_water"))
  .forEach(l => L.imageOverlay(base + l.file, l.bounds, { opacity: 0.9 }).addTo(map));

// gráfico: detecção (fit) e projeção (forecast)
const fit = model.filter(r => r.kind === "fit");        // observed_km2, lo95_km2/hi95_km2, method_lo_km2/method_hi_km2
const proj = model.filter(r => r.kind === "forecast");  // forecast_pct, lo80_pct/hi80_pct, label_pt "Projeção"
const label = id => (m.sources.find(x => x.id === id) || {}).label_pt || id;
console.log(label("nisar"), fit.length, "datas;", proj.length, "passos de projeção;", obs.length, "observações");
```

## Regras de interface

- Português, linguagem simples.
- Rótulos de origem: **Medido (NISAR)**, **Observado (OPERA/Sentinel-1)**, **Projeção (modelo)**. (alterado)
- Projeção sempre com faixa de incerteza e o rótulo "Projeção"; nunca como valor medido. (alterado)
- Créditos no mapa: OpenStreetMap, NASA/ISRO/ASF (NISAR), NASA OPERA (DSWx, RTC-S1); texto completo em
  `manifest.sources[].citation`. (alterado)
- Bibliotecas: só Leaflet 1.9.4 (BSD-2-Clause) via CDN.

## Publicação

GitHub Pages só serve a raiz ou `/docs` de um branch; para servir `web/`, usar um workflow de Pages
(GitHub Actions) que publica esta pasta. Antes de publicar, conferir `demo: false` no `manifest.json`.
