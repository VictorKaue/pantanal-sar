# Considerações do hackathon

## Checklist de submissão

- [ ] Repositório público com licença aberta (Apache-2.0, padrão do evento) e README
- [ ] Toda fonte, dado, biblioteca e imagem citados (abaixo)
- [ ] Conteúdo original ou com licença aberta documentada
- [ ] Nenhum menor de 18 anos reconhecível em vídeo ou imagem
- [ ] Uso de IA declarado (README, seção "Use of AI")
- [ ] Nenhum dado de demonstração (`demo: true`) na versão final do mapa
- [ ] Hipótese sobre os motores da mudança explicada, sem afirmar causalidade
- [ ] Limitações declaradas (produto NISAR provisório, série curta, MCD64A1 até setembro)
- [ ] Submeter até domingo 15/11 às 17:00 (prazo oficial 23:59)

## O que o enunciado pede e onde está

| Pedido | Onde |
|---|---|
| Rastrear e visualizar mudança na superfície com NISAR | Mapa com controle de datas: água, área que secou, queimada |
| Locais ao redor do mundo | Pipeline parametrizado em `config/aoi.yaml`; outras áreas úmidas como extensão |
| Visualização interativa e acessível | `web/` |
| Hipótese sobre os motores físicos | Resumo no app / vídeo (frente de narrativa) |
| Código aberto | Este repositório |

## Citações de dados (conferir DOIs antes de submeter)

- **NISAR L2 GCOV, Provisional V1.** NASA/JPL, ISRO. Distribuído pelo ASF DAAC. CMR concept ID `C2854338529-ASF`. https://nisar-docs.asf.alaska.edu/gcov/
- **OPERA DSWx-HLS V1, OPERA DSWx-S1 V1, OPERA RTC-S1 V1** (alterado). NASA/JPL OPERA project, distribuídos por PO.DAAC e ASF DAAC; derivados de HLS e Copernicus Sentinel-1. Conferir DOIs nas páginas dos produtos (DSWx-HLS: doi:10.5067/OPERA/OPERA_L3_DSWX-HLS_PROVISIONAL_V1, ver NOTICE).
- **MapBiomas Água, Coleção 5** (alterado). Projeto MapBiomas, CC BY 4.0. Carregador pronto, não usado nos resultados.
- **Bibliotecas novas** (alterado): Prophet (MIT), pandas (BSD-3).
- Fontes abaixo (MCD64A1, HLS, FIRMS) eram do escopo antigo de queimadas e **não são usadas** nos resultados atuais (alterado).
- **MCD64A1 v061.** Giglio, L. et al. MODIS/Terra+Aqua Burned Area Monthly L3 Global 500m. NASA LP DAAC. doi:10.5067/MODIS/MCD64A1.061
- **HLS L30 / S30 v2.0.** Masek, J. et al. Harmonized Landsat Sentinel-2. NASA LP DAAC. doi:10.5067/HLS/HLSL30.002, doi:10.5067/HLS/HLSS30.002
- **FIRMS.** NASA Fire Information for Resource Management System, VIIRS 375 m e MODIS. https://firms.modaps.eosdis.nasa.gov/ (usar a citação recomendada pelo FIRMS para cada fonte)
- **Mapa de fundo.** OpenStreetMap contributors (ODbL) ou o que for usado no `web/`.

## Bibliotecas

numpy, scipy, scikit-image, scikit-learn, h5py, rasterio (GDAL), earthaccess, asf_search, requests, PyYAML, Pillow, Leaflet. Todas com licenças abertas.
