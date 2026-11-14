# Frontend (web/)

Site estático (HTML, CSS e JS puros, sem build) que mostra os resultados do pipeline num mapa Leaflet.
Pode ser desenvolvido separado do Python: o único ponto de contato é a pasta `web/data/`.

```
web/
  index.html      estrutura da página
  css/style.css   visual (desktop: painel à direita; celular: painel embaixo)
  js/app.js       lógica: lê o manifest, desenha camadas, focos e resumo
  data/           GERADO pelo pipeline (ignorado pelo git, exceto manifest.json vazio)
```

## Rodar localmente

```bash
python -m pantanal_sar.cli demo        # gera data/ com dados SINTÉTICOS (aparece aviso amarelo)
python -m http.server -d web 8000      # abrir http://localhost:8000
```
Abrir o `index.html` direto (file://) não funciona: o navegador bloqueia o `fetch` do manifest.

## Contrato de dados (o que o pipeline entrega)

`data/manifest.json`, gerado por `src/pantanal_sar/export_web.py`:

| Campo | Tipo | Uso |
|---|---|---|
| `name` | string | nome da AOI |
| `bbox` | `[oeste, sul, leste, norte]` | enquadramento e retângulo da AOI |
| `demo` | bool | `true` mostra o aviso amarelo. **Nunca publicar com `true`.** |
| `dates` | `["AAAA-MM-DD", ...]` | passagens NISAR, em ordem |
| `layers[]` | objetos | PNG transparente por camada (abaixo) |
| `firms` | string | nome do GeoJSON de focos (`firms.geojson`) |
| `stats` | objeto | áreas por data (`per_date`), por par de datas (`per_pair`) e teste de associação (`analysis`) |

Cada item de `layers`:

| Campo | Exemplo | Observação |
|---|---|---|
| `id` | `2026-08-22_2026-09-27_burn` | |
| `type` | `backscatter`, `open_water`, `flooded_veg`, `dried`, `burn`, `dried_then_burned` | |
| `date` | `2026-09-27` | data em que a camada aparece; `null` em `dried_then_burned` (mostrado só na última data) |
| `date_from` | `2026-08-22` | só em camadas de mudança (`dried`, `burn`) |
| `source` | `measured` / `derived` | vira o rótulo "Medido (NISAR)" / "Derivado (NISAR + FIRMS)" |
| `label_pt`, `label_en` | | nome na legenda |
| `color` | `rgba(...)` | cor da legenda (o PNG já vem colorido) |
| `file` | `...png` | relativo a `data/` |
| `bounds` | `[[sul, oeste], [norte, leste]]` | formato do Leaflet |

`data/firms.geojson`: pontos com `properties.date` (AAAA-MM-DD), `source` e `frp`. No mapa, cada data mostra os focos
entre a passagem anterior (exclusive) e a atual (inclusive).

## Regras de interface

- Português, linguagem simples.
- Toda camada com rótulo de origem: **Medido (NISAR)**, **Observado (FIRMS)**, **Derivado**.
- Água e fogo: sempre "associação observada, não causa".
- Créditos no mapa: OpenStreetMap, NASA/ISRO/ASF, FIRMS.
- Bibliotecas: só Leaflet 1.9.4 (BSD-2-Clause) via CDN.

## Publicação

GitHub Pages só serve a raiz ou `/docs` de um branch; para servir `web/`, usar um workflow de Pages
(GitHub Actions) que publica esta pasta. Antes: rodar `export` com dados reais e conferir `demo: false`.
