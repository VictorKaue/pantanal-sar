# CLAUDE.md: contexto do projeto Pantanal SAR

Leia este arquivo inteiro antes de qualquer ação. Ele resume as decisões já tomadas com o time.

## Evento e prazo
- NASA Space Apps Challenge 2026, desafio **Dancing with the SARs** (dados de radar NISAR).
- Enunciado: construir uma aplicação interativa que use dados NISAR para **rastrear e visualizar** mudanças na superfície, em locais ao redor do mundo. Pede detecção do que aconteceu, **não previsão**. Também pede hipótese sobre os motores físicos da mudança, dados auxiliares de contexto e comparação de polarizações.
- Submissão: domingo 15/11/2026. Meta interna: **17:00** (prazo oficial 23:59). Fuso: America/Sao_Paulo.
- Pontos de controle: sáb 18:00 sub-região escolhida, login ok, 1ª cena baixada · sáb 22:00 primeiro mapa de água de um recorte (se falhar, reduzir escopo para água antes/depois + focos FIRMS) · dom 09:00 dados reais no mapa · dom 14:00 congelamento · dom 16:00 vídeo e README · dom 17:00 submeter.
- Plano do time (Claude Doc): https://claude.ai/artifact/Son1szrSt4YUpHivYVoJwK

## Escopo decidido
- **Só alagamentos e queimadas no Pantanal**, numa sub-região, com **interface web intuitiva**.
- Fora do escopo: estimativa de carbono/CO2, metano, generalização para outras regiões (só como extensão futura), interferometria, contas de usuário.
- Abordagem **estatística, não IA**: série NISAR curta, sem dados rotulados; métodos explicáveis.
- Mensagem central: o radar em banda L vê água sob a vegetação e enxerga através da fumaça e das nuvens na temporada de fogo.
- Relação água e fogo: reportar **associação observada, não causa**.

## Fontes de dados (só NASA) e justificativa
| Fonte | Papel |
|---|---|
| NISAR GCOV (ASF) | Núcleo: água e cicatriz de queimada por data |
| FIRMS (MODIS + VIIRS) | Quando e onde houve fogo; confirma as cicatrizes |
| MCD64A1 v061 | Área queimada mensal; valida as cicatrizes |
| HLS L30/S30 v2.0 | Óptico para validar o mapa de água na mesma data |
Nenhuma fonte valida a si mesma. MapBiomas/JRC provavelmente não cobrem 2026.

## Fatos verificados em 14/11/2026 (CMR/ASF)
- Coleção NISAR GCOV provisória: `C2854338529-ASF` (`NISAR_L2_GCOV_PROVISIONAL_V1`). Produto **provisório**, parcialmente validado.
- 185 cenas no Pantanal (bbox -58,-20.5,-55.5,-16), de 19/06 a 21/10/2026, 1,4 a 7,5 GB cada (~489 GB). Ver `data/inventory/nisar_gcov_pantanal_2026.csv`.
- Revisita de 12 dias. Várias trilhas alternam DHDH (HH+HV) e SHSH (só HH). **Trilha 132 ascendente** é a única com DHDH em todas as 9 datas (05/07 a 21/10).
- AOI padrão em `config/aoi.yaml`: trilha 132, frame 169, bbox [-58.3,-17.5,-57.3,-16.5] (norte do Pantanal, MT). **Provisória**: confirmar com focos FIRMS de 2026.
- MCD64A1 disponível só até **setembro/2026**; outubro fica só com FIRMS.
- HLS sem nuvem perto das passagens: Landsat 04/09, 28/09, 07/10; Sentinel-2 19/10, 20/10.
- O container de nuvem do Claude não acessa NASA/ASF; rodar downloads na máquina do usuário.

## Estado do código
- `src/pantanal_sar/`: busca (CMR), leitura do GCOV por streaming ou download, filtro de Lee, água (Otsu em HH + vegetação alagada experimental), recuo da água, cicatriz de queimada (queda de HV em terra estável, mantida só se um foco FIRMS tocar a mancha), teste de razão de chances (secou vs sempre seco, amostra a cada 1 km), validação (HLS, MCD64A1), exportação para `web/`.
- CLI: `python -m pantanal_sar.cli {search,fetch-nisar,inspect,fetch-firms,fetch-hls,process,export,demo}`.
- **Testado só com dados sintéticos** (`cli demo`) e 3 testes unitários. Nunca rodou com dado real; limiares não ajustados.
- **Não verificado**: nomes internos do HDF5 (`science/LSAR/GCOV/grids/frequencyA/...`, atributo `epsg_code`) e se as coordenadas são centro de pixel. Primeiro passo com dado real: `cli inspect arquivo.h5` e ajustar `gcov.py`.
- `web/index.html`: Leaflet mínimo, seletor de data, camadas com rótulo de origem, aviso amarelo para dados de demonstração.

## Passos manuais (só o usuário pode fazer)
1. Conta Earthdata; autorizar ASF e LP DAAC no perfil.
2. Chave FIRMS (MAP_KEY) por e-mail.
3. Preencher `.env` (nunca commitar).
4. MCD64A1 pelo AppEEARS (GeoTIFF, Burn_Date) em `data/raw/mcd64a1/`.
5. Criar repositório no GitHub.
Detalhes em `docs/SETUP.md`.

## Próximas tarefas (em ordem)
1. `git init`, primeiro commit, ajudar a criar o repo no GitHub (perguntar antes de push).
2. Ambiente: venv, `pip install -r requirements.txt && pip install -e .`, rodar `cli demo` e `pytest`.
3. Com `.env` pronto: `fetch-firms`, confirmar/ajustar o bbox da AOI.
4. `fetch-nisar` de 1 data, `inspect`, corrigir leitura; depois as 4 datas.
5. `fetch-hls`, `process`, revisar limiares olhando os mapas, `export`.
6. Polir a interface (português, simples, rótulos "Medido (NISAR)" / "Observado (FIRMS)").
7. GitHub Pages, README final, checklist de `docs/HACKATHON.md`.

## Regras
- Citar toda fonte, dado e biblioteca; licença Apache-2.0; declarar uso de IA; nenhum menor de 18 anos reconhecível em vídeo/imagem.
- Nunca apresentar dados do `demo` como resultado. Manifest com `demo: true` não pode ir para a versão final.
- Não commitar `.env`, `.h5`, `.tif` nem dados brutos.
- Perguntar antes de push, publicar ou apagar arquivos.
- Estilo: respostas condensadas e diretas; em documentos, marcar mudanças com texto "(alterado)", sem emoji.
- O usuário (Victor) é estudante de Ciência da Computação e Ciência de Dados, com experiência em backend e iOS, migrando para engenharia de dados.
