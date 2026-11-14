# Configuração e passos manuais

Itens marcados **[MANUAL]** precisam de alguém do time, porque envolvem login ou cadastro.

## 1. Contas [MANUAL]

1. **Earthdata Login**: crie em https://urs.earthdata.nasa.gov/users/new. Uma conta serve para NISAR, MCD64A1, HLS e AppEEARS.
2. No perfil do Earthdata, em *Applications > Authorized Apps*, autorize **ASF** e **LP DAAC** se o download pedir. Sem isso o download retorna erro 401/403.
3. **Chave do FIRMS (MAP_KEY)**: peça em https://firms.modaps.eosdis.nasa.gov/api/map_key/. Chega por e-mail em minutos.
4. Copie `.env.example` para `.env` e preencha. O `.env` está no `.gitignore`: **nunca faça commit dele**.

## 2. Ambiente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
python -m pantanal_sar.cli demo   # teste com dados SINTÉTICOS
```

## 3. Escolher a sub-região [MANUAL, 10 min]

A AOI padrão (`config/aoi.yaml`) é **provisória**: norte do Pantanal, dentro da trilha 132, frame 169.
1. Rode `python -m pantanal_sar.cli fetch-firms` (ou veja no mapa do FIRMS) e confira se há focos de 2026 dentro do `bbox`.
2. Se não houver, mova o `bbox` para onde há focos, desde que continue dentro de um frame com várias datas em `data/inventory/nisar_gcov_pantanal_2026.csv`.
3. Rode `python -m pantanal_sar.cli search` para confirmar as datas da nova área.

## 4. NISAR

```bash
python -m pantanal_sar.cli fetch-nisar             # streaming: lê só o recorte
python -m pantanal_sar.cli fetch-nisar --download  # plano B: baixa o .h5 inteiro (~1,9 GB/data)
```
Se a leitura falhar por nome de dataset, rode `python -m pantanal_sar.cli inspect arquivo.h5` e ajuste `src/pantanal_sar/gcov.py`.

**Download manual [MANUAL, plano B]:** no [ASF Vertex](https://search.asf.alaska.edu/), filtre NISAR / GCOV, desenhe a área, escolha as datas de `config/aoi.yaml` e baixe os `.h5`. Coloque em `data/raw/nisar/` e rode `fetch-nisar --download` (ele reaproveita os arquivos já baixados).

## 5. MCD64A1 [MANUAL, via AppEEARS]

O produto vem em HDF4/sinusoidal; o AppEEARS entrega GeoTIFF pronto.
1. Acesse https://appeears.earthdatacloud.nasa.gov/ > *Extract > Area*.
2. Área: o `bbox` do `config/aoi.yaml`. Datas: 2026-06-01 a 2026-11-14.
3. Camada: **MCD64A1.061 > Burn_Date**. Formato: **GeoTIFF**, projeção **Geographic**.
4. Ao terminar, baixe os arquivos `*Burn_Date*doy*.tif` e coloque em `data/raw/mcd64a1/`.

Em 14/11/2026, o MCD64A1 só tinha até setembro de 2026. Outubro fica só com FIRMS.

## 6. HLS

```bash
python -m pantanal_sar.cli fetch-hls
```
Baixa verde, SWIR1 e Fmask da cena mais limpa perto de cada data do NISAR, em `data/raw/hls/<data>/`. Datas limpas encontradas: Landsat 04/09, 28/09 e 07/10; Sentinel-2 19/10 e 20/10.

## 7. Processar e publicar

```bash
python -m pantanal_sar.cli process   # máscaras + data/processed/stats.json
python -m pantanal_sar.cli export    # PNGs + web/data/manifest.json
python -m http.server -d web 8000
```

## 8. Repositório no GitHub [MANUAL]

```bash
git remote add origin https://github.com/<usuario>/pantanal-sar.git
git push -u origin main
```
Para publicar o mapa: *Settings > Pages > Deploy from branch > main / `/web`* (ou mova `web/` para `docs/`, conforme a opção disponível). Os dados gerados em `web/data/` são ignorados pelo git; para publicar o mapa com dados reais, remova a linha `web/data/**` do `.gitignore` antes do commit final (os PNGs são pequenos).
