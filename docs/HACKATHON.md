# Considerações do hackathon

## Checklist de submissão (alterado, 15/11 01:20)

Feito:
- [x] Repositório público com licença Apache-2.0 e README atualizado (PR #1)
- [x] Fontes, dados e bibliotecas citados, com DOIs oficiais conferidos no CMR
- [x] Uso de IA declarado (README, seção "Use of AI")
- [x] Nenhum dado de demonstração em `web/data/` (`demo: false`)
- [x] Limitações declaradas (README e `metrics.limitations_pt`)
- [x] Auditoria independente dos dados e reprodutibilidade (`docs/DATA_REVIEW.md`)
- [x] Workflow do GitHub Pages (`.github/workflows/pages.yml`)

Falta (time dev):
- [ ] Mergear o PR #1 na main (Victor, até 08:00)
- [ ] Habilitar Pages: Settings > Pages > Source: GitHub Actions (Victor, até 08:00)
- [ ] `web/js/app.js` ler o contrato v2, guia em `web/README.md` (frontend, até 09:00)
- [ ] Gráfico: área medida, faixa de 95%, faixa do método; projeção só em % com faixa (frontend, até 12:00)
- [ ] Painel de limitações a partir de `metrics.limitations_pt` (frontend, até 12:00)
- [ ] Conferir o site publicado com `demo: false` e congelar o código (todos, 14:00)

Falta (apresentação):
- [ ] Conferir campos e limites do formulário de 2026
- [ ] Slides e vídeo (16:00); nenhum menor de 18 anos reconhecível
- [ ] Não dizer "anomalia" nem "vê água sob a vegetação"; projeção sempre rotulada
- [ ] Submeter até domingo 15/11 às 17:00 (prazo oficial 23:59)

## O que o enunciado pede e onde está

| Pedido | Onde |
|---|---|
| Rastrear e visualizar mudança na superfície com NISAR | Mapa com controle de datas: água, área que secou, queimada |
| Locais ao redor do mundo | Pipeline parametrizado em `config/aoi.yaml`; outras áreas úmidas como extensão |
| Visualização interativa e acessível | `web/` |
| Hipótese sobre os motores físicos | Resumo no app / vídeo (frente de narrativa) |
| Código aberto | Este repositório |

## Citações de dados (DOIs de NISAR e OPERA conferidos em 15/11) (alterado)

- **NISAR L2 GCOV, Provisional V1.** NASA/JPL, ISRO. Distribuído pelo ASF DAAC. CMR concept ID `C2854338529-ASF`. doi:10.5067/NIL2GCOV-P1 (alterado). https://nisar-docs.asf.alaska.edu/gcov/
- **OPERA DSWx-HLS V1, OPERA DSWx-S1 V1, OPERA RTC-S1 V1** (alterado). NASA/JPL OPERA project, distribuídos por PO.DAAC (DSWx) e ASF DAAC (RTC-S1); derivados de HLS e Copernicus Sentinel-1. DOIs conferidos no CMR em 15/11/2026: DSWx-HLS doi:10.5067/OPDSW-PL3V1 · DSWx-S1 doi:10.5067/OPDSWS1-L3V1 · RTC-S1 doi:10.5067/SNWG/OPERA_L2_RTC-S1_V1.
- **MapBiomas Água, Coleção 5** (alterado). Projeto MapBiomas, CC BY 4.0. Carregador pronto, não usado nos resultados.
- **Bibliotecas novas** (alterado): Prophet (MIT), pandas (BSD-3).
- Fontes abaixo (MCD64A1, HLS, FIRMS) eram do escopo antigo de queimadas e **não são usadas** nos resultados atuais (alterado).
- **MCD64A1 v061.** Giglio, L. et al. MODIS/Terra+Aqua Burned Area Monthly L3 Global 500m. NASA LP DAAC. doi:10.5067/MODIS/MCD64A1.061
- **HLS L30 / S30 v2.0.** Masek, J. et al. Harmonized Landsat Sentinel-2. NASA LP DAAC. doi:10.5067/HLS/HLSL30.002, doi:10.5067/HLS/HLSS30.002
- **FIRMS.** NASA Fire Information for Resource Management System, VIIRS 375 m e MODIS. https://firms.modaps.eosdis.nasa.gov/ (usar a citação recomendada pelo FIRMS para cada fonte)
- **Mapa de fundo.** OpenStreetMap contributors (ODbL) ou o que for usado no `web/`.

## Bibliotecas

numpy, scipy, scikit-image, scikit-learn, h5py, rasterio (GDAL), earthaccess, asf_search, requests, PyYAML, Pillow, Leaflet. Todas com licenças abertas.
