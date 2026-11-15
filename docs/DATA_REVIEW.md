# Revisão de dados (Prumo, auditor independente)

Estado: fase 1 feita; fase 2 (Sentinel-1) auditada sobre o `s1_rtc.csv` de 23:21, que ainda não inclui o lote 3 (ver S0) (alterado, 15/11).
Análises somente leitura; scripts em scratchpad (sens.py, det.py). Nada foi editado fora deste arquivo.

## Veredito final (alterado, 15/11, re-auditoria da rodada da Mare de 01:03)

**Os dados podem ir para a entrega.** Os bloqueios B1 e B2 e os itens C1-C5 e S0-S1 foram corrigidos e conferidos nos arquivos. Ainda há **1 bloqueio**, que é de documentação e não de dados: o README. O resto vira limitação declarada.

### Re-auditoria do README (alterado, 15/11): APTO

O R1 foi resolvido. Confrontei o README reescrito com `metrics.json` (01:03), `data/qc/s1_validation.csv`, `docs/METHOD.md` e o `cli.py`. Tendência (-1,0; de -1,7 a -0,3 km²/dia), 0 de 8 datas fora de 95% (0,4 esperado), projeção de -1,1% a +1,5% com ±43%, checagem S1 de -0,2% a -1,8%, sensibilidade de -37% a +56%, S4 (cerca de 115 km²), MAPE 44%, amplitudes 0,14/0,85, portão sem aprovação, `demo: false`: **tudo bate**. Os comandos da CLI existem, NOTICE e THIRD_PARTY_LICENSES existem, e a declaração de IA está presente. Ajustes de texto que não bloqueiam:

- R2. "NISAR vs OPERA DSWx-HLS: F1 0.66, kappa 0.65" vem de **uma única data** (DSWx 19/07 contra NISAR 17/07, METHOD.md:24). Escrever "1 date".
- R3. "F1 0.74, kappa 0.73 (16 pairs)" é a mediana; a média é 0,73/0,72 e a soma de pixels dá 0,73/0,73. Escrever "median".
- R4. "173 usable" para o DSWx-HLS: o modelo usa 169 (depois do descarte de 4 outliers). Idem "246 dates" para o RTC-S1: usadas 109 (T039 `ok`).
- R5. **Não afirmar no vídeo nem no pitch que "o NISAR vê água sob a vegetação" (CLAUDE.md).** O método detecta só água aberta (HH escuro); contra o DSWx classes 1+2 o F1 cai para 0,27 (METHOD.md:24). Água sob vegetação (double bounce) não foi medida. Incluir como limitação no README.
- R6. DOI do DSWx-HLS no NOTICE/HACKATHON termina em `PROVISIONAL_V1`, mas o produto usado é `OPERA_L3_DSWX-HLS_V1`. Conferir na página do PO.DAAC antes de submeter (o próprio HACKATHON.md já pede isso).

### Bloqueio anterior (resolvido)

- **R1. O `README.md` estava desatualizado e dizia coisas falsas.** A linha 10 afirma que o dado NISAR real ainda não foi processado. O texto descreve cicatriz de queimada, FIRMS e MCD64A1 como núcleo, que estão fora do escopo atual. E não cita OPERA DSWx-HLS, DSWx-S1, RTC-S1, Prophet nem MapBiomas. A declaração de uso de IA (linha 66) e a licença Apache-2.0 estão ok. Correção: reescrever com o escopo de água, as fontes de `config/aoi.yaml` e as `limitations_pt`, antes das 16:00.

### Re-auditoria das correções

| Achado | Estado | Evidência |
|---|---|---|
| B1 anomalias | resolvido | faixa de 95%, 0 de 8 fora (esperado 0,4); rótulo "Fora da faixa esperada (95%)"; `detection_chance` publicado |
| B2 limiar | resolvido como limitação | `method_lo_km2`/`method_hi_km2` batem com a minha recomputação (ex.: 07-17 236,76/509,53); tendência de -1,73 a -0,29 km²/dia declarada |
| C1 degrau | resolvido | `expected_km2`/`lo80_km2`/`hi80_km2` = null no forecast; saída só em % |
| C2 faixa | parcial, vira limitação | faixa reduzida a 0,75x no mesmo holdout (declarado otimista); ±42% ainda é largo |
| C3 outliers HLS | resolvido | 4 linhas descartadas; restam 2024-05-10 e 2024-08-22 com razão 0,47, acima do corte de 0,3 (aceitável) |
| C4 cobertura | resolvido | `normalize_coverage` (fração x 11.884 km²); holdout MAPE de 28,5% para 18,7% (obs) e de 23,7% para 9,3% (composto) |
| C5 S1 impossível | resolvido | checagem agora válida (12/12 meses, 109 obs); valores de -0,2 a -1,8% |
| S0 lote 3 | resolvido | s1_rtc com 109 obs T039 em 12/12 meses, até 05/11 |
| S1 queimada | resolvido | 16/08-15/10/2024 excluído; a série vai de 169 a 300 km², sem resíduo fora de 0,6-1,5x a mediana de 45 d; amplitude 0,14 (antes 0,78, era artefato); corr HLS~S1 0,51 (antes -0,42) |

### Vira limitação (declarar no README e no vídeo)

1. Detecção: 8 datas, só da seca. Nenhuma fica fora da faixa de 95%, então **a mensagem é "variação dentro do esperado e tendência de queda"**, não "anomalia". Holdout MAPE 44% (n=2).
2. A área em km² depende do limiar (±1 dB = -37% a +56%). Ler valores relativos.
3. As quedas de 22/08 e 27/09 não são confirmadas pelo Sentinel-1 (S4: F1 S1 x NISAR 0,59-0,68, o NISAR perde cerca de 115 km²). Isso não está em `limitations_pt`; incluir.
4. Previsão: só % (de -1,1% a +1,5% em 4 semanas), faixa de cerca de ±42%. Na prática, é **"estável, com grande incerteza"**. A checagem S1 dá "mesma direção 3/4", mas como as duas trajetórias ficam perto de 0%, o sinal não diz nada. Apresentar como "as duas fontes indicam estabilidade", não como "concordam na direção".
5. Holdout de 90 d usado para escolher a variante e para ajustar a faixa (L2): as métricas da previsão são otimistas.
6. Nenhuma fonte passa no portão de calibração para km² NISAR (todas com skill ≤ 0,07).
7. O S1 (banda C) não vê a cheia sob vegetação (amplitude 0,14 contra 0,85 do HLS); serve para tendência e checagem, não para nível.
8. A validação S1 x DSWx-S1 não é independente (mesmo sensor); o T141, de melhor F1, ficou fora por cobertura.
9. NISAR é produto provisório. MapBiomas ainda não entrou (precisa de login no Google Earth Engine).

### Menores (não bloqueiam)

- O manifest lista `s1_rtc` com `n_obs` 109; a mensagem da Mare diz 115 (a diferença são as datas `drop`/excluídas). Coerente.
- `opera_dswx_water.csv` (v1) continua órfão (L5).

## Veredito parcial (fase 1, mantido como histórico)

Pacote `web/data` é real (`demo: false` legítimo, 8 datas NISAR, rótulo "Projeção" presente). Mas a **detecção não se sustenta como está apresentada**: a área NISAR depende mais do limiar do que do fenômeno, e as "anomalias" são do tamanho do acaso esperado numa faixa de 80%. A previsão em km² tem um degrau visual enganoso. Corrigível até 14:00 com mudanças de rótulo e filtros simples, sem refazer o pipeline.

## Bloqueia entrega

**B1. "Anomalias" NISAR não são distinguíveis de ruído.**
- Faixa de 80% dentro da amostra com 8 pontos: espera-se 1,6 pontos fora por acaso; P(≥3 fora) = 0,20.
- Resíduos de uma reta OLS (mesma inclinação -1,01 km²/dia): |z| máximo 1,38. Nenhum ponto passa de 2 desvios.
- Sorteio do Prophet (20 sementes): 07-17 sinalizada 20/20, 08-22 19/20, **09-27 só 5/20**. A semente fixa (0) cai no caso minoritário.
- Limiar ±1 dB (ver B2): 09-27 e 08-22 aparecem em 3/5 limiares cada.
- Correção: renomear para "Fora da faixa esperada (80%)" ou usar IC 95% / |z| ≥ 2; no texto, tratar como "variação compatível com ruído", exceto 07-17 (robusta, e coerente com o fim da cheia). Não citar 09-27 como anomalia.

**B2. Área NISAR muito sensível ao limiar fixo HH < -16,75 dB.**
Área (km²) recalculada com o mesmo filtro de Lee 5x5 e máscara do bbox:

| data | -17,75 | -16,75 (atual) | -15,75 |
|---|---|---|---|
| 07-17 | 237 | 376 | 510 |
| 08-22 | 93 | 210 | 357 |
| 09-27 | 132 | 180 | 277 |
| 10-21 | 178 | 254 | 327 |

- ±1 dB muda a área em -37% a +56%; percentil 1 do HH ≈ -18 dB, ou seja, o limiar está no ombro da distribuição de terra, não num vale plano.
- Tendência varia de -0,28 a -1,73 km²/dia (6x) conforme o limiar; holdout MAPE 29-51%.
- A ordem das datas muda (data mínima: 08-22 a -17,75; 09-27 a -16,75).
- Correção: publicar a faixa ±1 dB como incerteza de método (`water_km2_lo/hi` ou nota em `limitations_pt`); mostrar valores relativos, não km² absolutos como "medidos"; confirmar com DSWx/HLS em pixel (pendente, ver P1).

## Corrigir antes de 14:00

**C1. Degrau falso entre detecção e projeção no gráfico.** Último NISAR 254 km² (21/10); primeira projeção 175 km² (08/11), enquanto `forecast_pct` diz -2%. Causa: nível = k 0,605 × yhat do DSWx (289), e o yhat do DSWx na base (295) está 25% abaixo da mediana observada dos últimos 15 dias (395). Correção: no frontend, plotar só `forecast_pct` (ou ancorar o nível no último NISAR × (1+pct)); não plotar `expected_km2` não calibrado na mesma escala do observado.

**C2. Faixa da projeção mistura níveis e é larga demais.** `lo80_km2 = k_lo95 × yhat_lo80`: não é um IC80. Holdout: cobertura 100% em n=18 (P=0,018 se fosse 80% calibrado); `lo80_pct` -67% a `hi80_pct` +65%. Correção: chamar de "faixa ampla de incerteza", não "80%"; registrar que está superdispersa.

**C3. Outliers físicos no DSWx-HLS 2024 entram no treino como `ok`/`low`.** 2024-09-17: 0,16 km² com valid_frac 0,93; 08-23 9,1; 09-12 8,6; 09-22 11,5 km², alternando com 402 e 320 km² em dias vizinhos. Impossível fisicamente (só o canal do Paraguai no bbox tem dezenas de km²); coincide com fumaça da temporada de fogo recorde de 2024, não mascarada como nuvem. Correção: marcar `drop` quando água < 0,3 × mediana móvel de 31 dias (12 linhas no total, listar em limitação); refazer a previsão.

**C4. `water_km2` do DSWx-HLS cai com a cobertura válida.** corr(valid_frac, água km²) = 0,40, mas corr(valid_frac, água/valid) = 0,07: o viés é de cobertura, não de hidrologia. Linhas `low` (valid 0,60-0,79) subestimam 20-40% e entram no Prophet com peso cheio (Prophet não aceita peso; já declarado). Ex.: 08-10/2026 208 km² (valid 0,66) vs 08-08 500 km² (0,98). Correção: usar fração de água × área do bbox, ou excluir `low` do Prophet.

**C5. Checagem S1 publica valores impossíveis.** `forecast_check.weeks[].forecast_pct` chega a -178% (área negativa) com `valid: false`. Correção: não exportar `weeks` quando inválido, ou anular os valores.

## Registrar como limitação

- L1. Detecção com 8 pontos, só seca, tendência + 3 changepoints em 8 pontos: quase interpola. Holdout das 2 últimas datas MAPE 44%.
- L2. Escolha da variante (obs vs composto15) e avaliação usam o mesmo holdout de 90 dias: leve viés otimista no MAPE 23,7% declarado.
- L3. Nota do Orquestrador diz forma sazonal HLS~S1 r = 0,92 e amplitude S1 0,41; `metrics.json` atual tem corr mensal -0,42, climatologia -0,77 e amplitude 0,78 (marcado inconclusivo). Reconciliar antes de citar no pitch.
- L4. `aoi.area_km2` 11.823,9 vs `valid_km2` NISAR 11.777,5 (0,4%, geodésica vs grade UTM). Inofensivo; anotar.
- L5. `data/series/opera_dswx_water.csv` (v1) continua no repo e fora de `series.sources`: órfão.
- L6. NISAR é produto provisório, parcialmente validado (já declarado no CLAUDE.md; repetir no README).

## Fase 2: Sentinel-1 RTC (alterado, 15/11)

Base: `data/series/s1_rtc.csv` (23:21), `data/qc/s1_threshold.json`, `data/qc/s1_validation.csv`.

**S0 (corrigir antes de 14:00). O lote 3 ainda não está na série.** Os recortes estão em `data/processed/s1_rtc` (jan/2023 a 12/11/2026, `index.csv` às 23:53), mas `s1_rtc.csv` é de 23:21: T039 utilizável só em mar-mai e jul-out (62 linhas; 1 linha em julho). `metrics.json` e a checagem da previsão ("7/12 meses") refletem a série antiga. Regenerar `s1_rtc.csv` e rodar `timeseries` de novo antes de 14:00; perguntado à Lagoa.

**S1 (bloqueia o uso do S1 como checagem). Cicatrizes de queimada viram "água" em VH na seca de 2024.** T039 de ago a out/2024: 262 -> 364 -> 525 -> 616 -> 775 -> 856 -> 901 km², depois 184 km² em 27/10. A linha de base da seca nos outros anos é de cerca de 210 km², e 2024 teve seca recorde, então a água deveria cair, não subir. Validação contra o DSWx-S1 nas mesmas datas: F1 cai de 0,74-0,81 (2025-26) para **0,33-0,47** (T039, 28/08-15/10/2024), com 358-780 mil pixels FP (S1 diz água, DSWx-S1 não), contra cerca de 1-20 mil em 2025-26. Solo queimado e cinza ficam escuros em VH. Efeito em cadeia: `amplitude_rel` de 0,78 do s1_rtc em `seasonal_comparison` vem desse artefato. Sem 2024, o T039 é quase plano (184-291 km²), coerente com a nota "banda C achata a cheia". A correlação HLS x S1 negativa (-0,42) também é contaminada. Correção: `drop` em T039 de 16/08 a 15/10/2024 (ou sempre que o F1 contra o DSWx-S1 for < 0,6), ou máscara de área queimada (MCD64A1) antes do limiar.

**S2 (limitação). Escolha VH < -22,95 dB.** Escore 0,57 (VH) contra 0,32 (VV) em 16 datas: VH ganha, mas o vale do histograma é raso (profundidade 0,10 a 0,60) e o limiar é único para cheia e seca. Validar contra o DSWx-S1 superestima a acurácia, porque o produto vem do mesmo sensor (Sentinel-1); não chamar isso de validação independente.

**S3 (registrar). T141 descartado, mas concorda melhor.** O T141 tem F1 0,78-0,83 contra o DSWx-S1 e 0,66-0,84 contra o NISAR, contra 0,59-0,80 do T039. Foi descartado por cobrir só 57% do bbox. Defensável, mas declarar.

**S4 (evidência nova para B1, NISAR). As quedas de 22/08 e 27/09 parecem erro de detecção do NISAR, não hidrologia.** Na comparação de máscaras S1 x NISAR (pixel de 30 m; FP = S1 vê água, NISAR não), as duas datas com pior F1 são justamente as "anomalias negativas":

| NISAR | F1 T141 / T039 | FP T141 (mil px) |
|---|---|---|
| 17/07 | 0,82 / 0,69 | 37 |
| 22/08 | 0,68 / 0,64 | 117 |
| 27/09 | **0,66 / 0,59** | **127** |
| 21/10 | 0,84 / 0,80 | 55 |

Em 27/09 o NISAR deixa de ver cerca de 115 km² de água que o S1 vê (2-3 dias de diferença), o dobro das datas boas. Ao mesmo tempo, a série S1 T039 de 2026 é plana (217-223 km² em ago-out). Hipótese: vento ou rugosidade na lâmina d'água em HH, ou umidade. Correção: no pitch, não apresentar 22/08 e 27/09 como perda de água; no máximo como "queda não confirmada pelo Sentinel-1".

## Pendente

- P1. Máscara NISAR x DSWx-HLS em pixel: o DSWx-HLS de 2026 não tem data `ok` no mesmo dia do NISAR, e `data/raw/hls` só tem 2024. Parcialmente coberto pela comparação S1 x NISAR (S4).
- P2. Rever S1 e calibração depois que `s1_rtc.csv` for regenerado (S0).
- P3. Proveniência (citações no README, licenças, declaração de IA).
