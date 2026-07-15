# Dataset de mapas dinámicos — fixed vs. dinámico por composición

Date: 2026-07-12 (última actualización de tabla: 2026-07-15)

Generado con `scripts/generate_dynamic_map.py` (búsqueda en dos etapas:
prefiltro con la simulación fixed sobre las permutaciones de cada
composición, luego `beam_search()` sobre las mejores `--top-k`) y los batch
runners `scripts/run_overnight_dynamic_maps*.sh` /
`run_parallel_dynamic_maps_12to15pc.sh` / `run_5lane_dynamic_maps_50comp.sh`.
**87 composiciones en total** (6-18 piezas), incluida `BRRBRB` (3B/3R,
6 piezas, sin JSON propio por ser anterior al script). El registro vivo de
qué composición está completada/validada/en curso vive en la tabla
`shipyard_pnp_ws.dynamic_map_registry` (Postgres, ver
`scripts/dynamic_map_registry.py`) — pensada para coordinar varios
ordenadores generando tandas distintas sin repetir composiciones. Estado
actual del registro: 79 `COMPLETED` + 8 `VALIDATED`.

**Las dos tandas de 2026-07-13/14/15 terminaron por completo** (10/10 y
50/50, sin fallos): `run_parallel_dynamic_maps_12to15pc.sh` (F1-F10, 12-15
piezas) y `run_5lane_dynamic_maps_50comp.sh` (5 carriles de 10, 9-18
piezas). Las 60 composiciones nuevas ya están en la tabla de abajo.

**Corrida overnight de 18 piezas (2026-07-13):** las tres composiciones
(`9B/9R/0G`, `6B/6R/6G`, `7B/6R/5G`) terminaron sin fallos, ~79 min cada una
(mucho más rápido de lo temido con `--top-k 6 --beam-width 60
--max-rollouts 3000`). Antes de esta corrida se arregló un bug real en
`generate_dynamic_map.py`: la etapa 1 enumeraba **todas** las permutaciones
únicas antes de muestrear, y `6B/6R/6G` tiene ~17.2 millones (`7B/6R/5G`
~14.7 millones) — habría agotado memoria. Ahora `_count_permutations()`
calcula el total con la fórmula cerrada del multinomial (sin enumerar) y,
si supera `--sample-cap`, `_sample_permutations_directly()` extrae permutaciones
aleatorias distintas barajando el multiset, sin construir nunca el espacio
completo.

## Corrección aplicada el 2026-07-12

El campo `fixed_reference_time_s`/`fixed_reference_order` de las 22
composiciones generadas por el batch runner estaba mal: se calculaba
simulando el **string de entrada literal** que se le pasó al script en
línea de comandos (un orden arbitrario elegido a mano solo para fijar la
composición, p.ej. `BBBBRRRRGGG`), no el mejor orden que la propia etapa 1
ya había encontrado (`scored[0]`) buscando entre todas — o, si la
composición se muestreó por superar `--sample-cap`, entre las muestreadas —
permutaciones bajo la política fixed.

Lo detectó el usuario corriendo manualmente el optimizador fixed del
dashboard para `4B/4R/3G`: encontró `767.0s` (`BBBBGGGRRRR`), muy por debajo
de los `899.0s` que teníamos guardados como referencia fixed para esa
composición. Confirmado con el propio log de esa corrida
(`B6_BBBBRRRRGGG_20260711_060302.log`): la etapa 1 ya había encontrado
`766.8s` (`BBGBGRRRGRB`) — casi idéntico al hallazgo manual — pero ese valor
nunca se usó para el campo `fixed_reference_*`, que en su lugar recalculaba
sobre el string arbitrario de entrada.

**Arreglado en dos sitios:**
- `scripts/generate_dynamic_map.py`: `fixed_reference_order`/
  `fixed_reference_time_s` ahora vienen de `scored[0]` (el mejor real de la
  etapa 1), no de una simulación nueva del argumento de entrada.
- Los 22 JSON ya generados en `src/shipyard_pnp/config/dynamic_maps/` se
  corrigieron releyendo la línea `"[stage 1/2] done... Top N candidates:"`
  de cada log ya guardado en `results/dynamic_map_generation_logs/` (no
  hizo falta re-simular nada, ese dato ya estaba calculado y logueado
  durante la corrida original). `3B3R3G` no tenía log guardado (se generó
  antes de esta convención de logging) — se recalculó aparte, exhaustivo
  sobre sus 1680 permutaciones (barato, cabía dentro del `sample_cap`).

Cada JSON corregido lleva un campo `_correction_note` explicando el cambio.

**Efecto de la corrección**: el ahorro medio reportado bajó de ~22% (con el
bug) a un valor mucho más modesto (ver tabla) — en dos composiciones
(`2B/2R/6G` y `2B/6R/2G`) el mapa dinámico no encontró ninguna mejora real
sobre el fixed correcto (mismo orden, mismo tiempo).

## Aviso sobre `SAMPLED`

Muchas de las 87 composiciones tienen más permutaciones únicas que el
`--sample-cap` usado para generarlas, así que tanto la etapa 1 (ranking
fixed) como la etapa 2 (beam search, que solo explora los `--top-k` de esa
muestra) operan sobre una muestra aleatoria, no el espacio completo. Para
esas filas, "mejor fixed" y "mejor dinámico" son "mejor encontrado dentro de
la muestra", no un óptimo global probado. **Ojo con mezclar generaciones**:
las 27 primeras (2026-07-10/13) se generaron con `--sample-cap 2000`; las 60
compuestas después (2026-07-13/14/15, `F1-F10` y `G*1-G*10`) usan
`--sample-cap 20000` (10x más cobertura, ver commit del fix de
`generate_dynamic_map.py` que evita enumerar espacios de millones de
permutaciones antes de muestrear). Las filas `exhaustivo` (42 de 87) cubren
el 100% del espacio de permutaciones. **Caso especial, RESUELTO:** `13B/2R/2G`
(17 piezas) tenía su fixed marcado como "no completa (>2000s)" con las
14,280 permutaciones exhaustivas — era un artefacto del horizonte de
simulación por defecto (2000s), no un deadlock real. Re-escaneadas las
14,280 permutaciones exhaustivamente con horizonte 5000s (4 shards en
paralelo): **las 14,280 completan**, 0 incompletas. Mejor fixed real:
`2039.0s` (`BBBBBGGRRBBBBBBBB`) — ya reflejado en la tabla de abajo. El
mapa dinámico no necesitó recalcularse: su `1753.1s` ya había completado
dentro del horizonte original de 2000s, solo la referencia fixed estaba
mal por el corte de horizonte.

## Tabla completa (87 composiciones)

Incluye `BRRBRB` (3B/3R, 6 piezas, de `docs/dynamic_map_brrbrb/`),
`4B/5R/0G` (9 piezas, de `docs/dynamic_map_4b5r0g/`), `5B/4R/0G`
(9 piezas, de `docs/dynamic_map_5b4r0g/`), `2B/2R/6G`
(10 piezas, de `docs/dynamic_map_2b2r6g/`), `4B/4R/3G`
(11 piezas, de `docs/dynamic_map_b6_4b4r3g/`) y `5B/5R/2G`
(12 piezas, de `docs/dynamic_map_5b5r2g/`), `5B/5R/5G`
(15 piezas, de `docs/dynamic_map_5b5r5g/`) y `6B/6R/6G`
(18 piezas, de `docs/dynamic_map_6b6r6g/`) — las ocho composiciones
de este dataset con corrida real en hardware confirmada. Las columnas
"real" y "diff." (fidelidad simulación-vs-realidad, `(real-sim)/sim`) solo
tienen valor en esas ocho filas.

| n | Composición | Fixed: sim | Fixed: real | Fixed: diff. | Fixed: mejor orden | Dinámico: sim | Dinámico: real | Dinámico: diff. | Dinámico: mejor orden | Ahorro (sim) | Ahorro (real) | Etapa 1 |
|---:|---|---:|---:|---:|---|---:|---:|---:|---|---:|---:|---|
| 6 | 3B/3R/0G | 560.2s | 552.962s | -1.29% | `BRRRBB` | 497.3s | 486.651s | -2.14% | `BRRBRB` | +11.2% | **+12.0%** | exhaustivo, validada en hardware, ver `docs/dynamic_map_brrbrb/` |
| 9 | 2B/3R/4G | 425.4s | — | — | `BGRBGGRRG` | 425.4s | — | — | `BGRBGGRRG` | +0.0% | — | exhaustivo |
| 9 | 2B/5R/2G | 512.3s | — | — | `BRGRGRBRR` | 512.3s | — | — | `BRGRGRBRR` | +0.0% | — | exhaustivo |
| 9 | 3B/3R/3G | 562.8s | — | — | `BBGBGRRRG` | 514.4s | — | — | `BBGBGRRRG` | +8.6% | — | exhaustivo |
| 9 | 3B/6R/0G | 713.8s | — | — | `BRRRRRRBB` | 651.0s | — | — | `BRRRRRBBR` | +8.8% | — | exhaustivo |
| 9 | 4B/2R/3G | 664.4s | — | — | `BGBBBGGRR` | 615.9s | — | — | `BGBBBGGRR` | +7.3% | — | exhaustivo |
| 9 | 4B/5R/0G | 815.2s | 797.620s | -2.16% | `BRRRRRBBB` | 689.7s | 668.900s | -3.02% | `BRRRBBRRB` | +15.4% | **+16.1%** | exhaustivo, validada en hardware, ver `docs/dynamic_map_4b5r0g/` |
| 9 | 5B/2R/2G | 816.8s | — | — | `BBBBGGBRR` | 720.0s | — | — | `BBGBGRBBR` | +11.9% | — | exhaustivo |
| 9 | 5B/4R/0G | 916.7s | 899.789s | -1.84% | `BRRRRBBBB` | 759.8s | 747.367s | -1.64% | `BBBBRRRBR` | +17.1% | **+16.9%** | exhaustivo, validada en hardware, ver `docs/dynamic_map_5b4r0g/` |
| 10 | 2B/2R/6G | 421.5s | 430.423s | +2.12% | `BGRBGGRGGG` | 421.5s | 433.563s | +2.86% | `BGRBGGRGGG` | -0.0% | **-0.7%** | exhaustivo, validada en hardware, ver `docs/dynamic_map_2b2r6g/` |
| 10 | 2B/6R/2G | 561.1s | — | — | `BRGRRBRRRG` | 561.1s | — | — | `BRGRRBRRRG` | -0.0% | — | exhaustivo |
| 10 | 3B/2R/5G | 476.7s | — | — | `BBBGGRGGGR` | 476.7s | — | — | `BBBGGRGGGR` | +0.0% | — | exhaustivo |
| 10 | 3B/3R/4G | 541.0s | — | — | `BGBGGGRRRB` | 514.4s | — | — | `BGBBGRGRGR` | +4.9% | — | muestreado |
| 10 | 3B/4R/3G | 614.0s | — | — | `BBBGGRRGRR` | 554.6s | — | — | `BBRGRGRBGR` | +9.7% | — | muestreado |
| 10 | 4B/2R/4G | 633.6s | — | — | `BBBGGGGBRR` | 585.1s | — | — | `BBBGGGGBRR` | +7.7% | — | exhaustivo |
| 10 | 4B/3R/3G | 715.6s | — | — | `BBGBGGRRRB` | 604.3s | — | — | `BGBBGRRRGB` | +15.6% | — | muestreado |
| 10 | 4B/6R/0G | 866.4s | — | — | `BRRRRRRBBB` | 740.9s | — | — | `BRRRRBBRRB` | +14.5% | — | exhaustivo |
| 10 | 5B/2R/3G | 816.8s | — | — | `BGBBBBGGRR` | 720.0s | — | — | `BGBBBBGGRR` | +11.9% | — | exhaustivo |
| 10 | 6B/2R/2G | 969.6s | — | — | `BBBBGGBRRB` | 841.9s | — | — | `BGBBRRGBBB` | +13.2% | — | exhaustivo |
| 10 | 6B/4R/0G | 1069.3s | — | — | `BRRRRBBBBB` | 863.9s | — | — | `BBRBRBBRRB` | +19.2% | — | exhaustivo |
| 10 | 7B/3R/0G | 1170.9s | — | — | `BRRRBBBBBB` | 979.6s | — | — | `BBBBBBBRRR` | +16.3% | — | exhaustivo |
| 11 | 3B/3R/5G | 528.1s | — | — | `BBBGGRGGGRR` | 528.0s | — | — | `BBBGGRGGGRR` | +0.0% | — | exhaustivo |
| 11 | 3B/4R/4G | 611.1s | — | — | `BGGGGBRRRRB` | 567.1s | — | — | `BGBGBRGRGRR` | +7.2% | — | muestreado |
| 11 | 4B/3R/4G | 707.2s | — | — | `BBGGGGRRRBB` | 604.3s | — | — | `BGBBGGRGRRB` | +14.6% | — | muestreado |
| 11 | 4B/4R/3G | 766.8s | 758.330s | -1.13% | `BBBBGGGRRRR` | 655.5s | 645.673s | -1.50% | `BBGBGRRRGRB` | +14.5% | **+14.9%** | muestreado, validada en hardware, ver `docs/dynamic_map_b6_4b4r3g/` |
| 11 | 5B/2R/4G | 773.6s | — | — | `BBBGGGGBBRR` | 720.0s | — | — | `BBBBBGGRGRG` | +6.9% | — | exhaustivo |
| 11 | 5B/4R/2G | 916.7s | — | — | `BRGRRBRBBGB` | 805.3s | — | — | `BRGRRBRBBGB` | +12.2% | — | exhaustivo |
| 11 | 6B/2R/3G | 969.6s | — | — | `BGBBBBGGRRB` | 872.7s | — | — | `BBBGGBBBRRG` | +10.0% | — | exhaustivo |
| 12 | 2B/2R/8G | 487.3s | — | — | `GBGBGRGRGGGG` | 487.3s | — | — | `GBGBGRGRGGGG` | +0.0% | — | exhaustivo |
| 12 | 2B/5R/5G | 553.1s | — | — | `BGRBGGGRGRRR` | 548.3s | — | — | `GBRGGBRGRRGR` | +0.9% | — | muestreado |
| 12 | 3B/2R/7G | 514.9s | — | — | `BGBGBGRGGGRG` | 514.9s | — | — | `BGBGBGRGGGRG` | +0.0% | — | exhaustivo |
| 12 | 3B/7R/2G | 765.1s | — | — | `BRGRRBRRRGRB` | 702.1s | — | — | `BRGRRBRRRGRB` | +8.2% | — | exhaustivo |
| 12 | 4B/4R/4G | 744.9s | — | — | `BGGBGGRRRBRB` | 659.3s | — | — | `BGBBGRRGGRBR` | +11.5% | — | muestreado |
| 12 | 4B/6R/2G | 866.4s | — | — | `BRGRRRRBRBBG` | 740.8s | — | — | `BRGRRRBRBBGR` | +14.5% | — | exhaustivo |
| 12 | 5B/2R/5G | 768.4s | — | — | `BBBGGGBRGBGR` | 720.0s | — | — | `BBBGGBRGBGRG` | +6.3% | — | muestreado |
| 12 | 5B/5R/2G | 968.0s | 949.410s | -1.92% | `BRRRRBBBBRGG` | 796.7s | 775.495s | -2.66% | `BBRGRRBRBRGB` | +17.7% | **+18.3%** | muestreado, validada en hardware, ver `docs/dynamic_map_5b5r2g/` |
| 12 | 6B/2R/4G | 926.3s | — | — | `BBBGGGGBBRRB` | 841.9s | — | — | `BBBGGGGBRRBB` | +9.1% | — | exhaustivo |
| 12 | 6B/4R/2G | 1020.9s | — | — | `BRRRBBBBBGGR` | 923.9s | — | — | `BRRRBBBBBGGR` | +9.5% | — | exhaustivo |
| 12 | 7B/2R/3G | 1122.3s | — | — | `BGBBBBGGRRBB` | 976.8s | — | — | `BGBBBBBBGGRR` | +13.0% | — | exhaustivo |
| 12 | 8B/2R/2G | 1275.1s | — | — | `BBBBBGGRRBBB` | 1098.7s | — | — | `BGBBRRBBBBBG` | +13.8% | — | exhaustivo |
| 13 | 3B/2R/8G | 537.2s | — | — | `BGBGBGRGGGRGG` | 537.2s | — | — | `BGBGBGRGGGRGG` | +0.0% | — | exhaustivo |
| 13 | 3B/3R/7G | 562.6s | — | — | `BGRBGGGRGGBRG` | 562.6s | — | — | `BGRBGGGRGGBRG` | +0.0% | — | muestreado |
| 13 | 4B/4R/5G | 732.0s | — | — | `BBBGGGRGGRRRB` | 669.0s | — | — | `BBBGGGRGGRRRB` | +8.6% | — | muestreado |
| 13 | 5B/2R/6G | 753.2s | — | — | `BBBGGGRGGGBBR` | 720.0s | — | — | `BGBBGGBGBGGRR` | +4.4% | — | muestreado |
| 13 | 5B/3R/5G | 819.7s | — | — | `BBGBGRBBGGGRR` | 722.8s | — | — | `BBGBGRBBGGGRR` | +11.8% | — | muestreado |
| 13 | 5B/5R/3G | 942.1s | — | — | `BRRRBBBBGGGRR` | 822.6s | — | — | `BRRRBBBBGGGRR` | +12.7% | — | muestreado |
| 13 | 6B/2R/5G | 921.2s | — | — | `BBBGGBBGGBGRR` | 849.7s | — | — | `BBBGBGGGBGBRR` | +7.8% | — | muestreado |
| 13 | 6B/5R/2G | 1120.6s | — | — | `BRRRRRBBBBBGG` | 960.7s | — | — | `BRRRBRBBGBRBG` | +14.3% | — | muestreado |
| 13 | 8B/5R/0G | 1426.2s | — | — | `BRRRRRBBBBBBB` | 1183.6s | — | — | `BRRRBBBBBBBRR` | +17.0% | — | exhaustivo |
| 14 | 10B/2R/2G | 1580.6s | — | — | `BBBBBGGRRBBBBB` | 1355.8s | — | — | `BBBBBGGRRBBBBB` | +14.2% | — | exhaustivo |
| 14 | 10B/4R/0G | 1680.5s | — | — | `BRRRRBBBBBBBBB` | 1437.9s | — | — | `BRRRBBBBBBBBBR` | +14.4% | — | exhaustivo |
| 14 | 4B/2R/8G | 606.2s | — | — | `BGBGGBGGBGRGGR` | 606.2s | — | — | `BGBGGBGGBGRGGR` | +0.0% | — | muestreado |
| 14 | 4B/6R/4G | 846.9s | — | — | `BRRRRBBBRGGGRG` | 757.6s | — | — | `BRGGRRBRBBGRRG` | +10.5% | — | muestreado |
| 14 | 4B/8R/2G | 968.9s | — | — | `BRRRRRBRBBGRRG` | 843.2s | — | — | `BRGRRRRRBRBRGB` | +13.0% | — | muestreado |
| 14 | 5B/5R/4G | 939.2s | — | — | `BRRRBBBRBGGGGR` | 823.3s | — | — | `BBRGRRBBRBGGGR` | +12.3% | — | muestreado |
| 14 | 6B/4R/4G | 1041.5s | — | — | `BBBGGGGBRRRRBB` | 915.8s | — | — | `BBBGGGGBRRRRBB` | +12.1% | — | muestreado |
| 14 | 8B/6R/0G | 1477.4s | — | — | `BRRRRRRBBBBBBB` | 1234.8s | — | — | `BRRRRBBBBBBBRR` | +16.4% | — | exhaustivo |
| 15 | 11B/2R/2G | 1733.5s | — | — | `BBBBBGGRRBBBBBB` | 1490.9s | — | — | `BBBBBGGRRBBBBBB` | +14.0% | — | exhaustivo |
| 15 | 3B/12R/0G | 1021.5s | — | — | `BRRRRRRRBBRRRRR` | 958.6s | — | — | `BRRRRRRRBBRRRRR` | +6.2% | — | exhaustivo |
| 15 | 3B/6R/6G | 710.3s | — | — | `BBGGGBRGGRRRGRR` | 710.3s | — | — | `BBGGGBRGGRRRGRR` | +0.0% | — | muestreado |
| 15 | 3B/8R/4G | 830.6s | — | — | `BGRGRRBRRBGRRRG` | 767.3s | — | — | `BGRGRRBRRBGRRRG` | +7.6% | — | muestreado |
| 15 | 4B/11R/0G | 1123.0s | — | — | `BRRRRRRRBBBRRRR` | 997.1s | — | — | `BRRRRRRRBBRRBRR` | +11.2% | — | exhaustivo |
| 15 | 4B/3R/8G | 672.7s | — | — | `BGBBRRGGGGGBGRG` | 666.1s | — | — | `BGBBRRGGGGGBGRG` | +1.0% | — | muestreado |
| 15 | 5B/2R/8G | 746.4s | — | — | `BGBGBGGRGGBGBGR` | 722.2s | — | — | `BBBGBGGGGBRGGGR` | +3.2% | — | muestreado |
| 15 | 5B/5R/5G | 963.8s | 952.436s | -1.18% | `RBBGGGGBGBRRRRB` | 811.7s | 800.218s | -1.41% | `BGRBGGGRRBRBRGB` | +15.8% | **+16.0%** | muestreado, validada en hardware, ver `docs/dynamic_map_5b5r5g/` |
| 15 | 6B/6R/3G | 1126.5s | — | — | `BBRRRRBBBBGGRRG` | 963.6s | — | — | `BRRRBRBBGBRGRBG` | +14.5% | — | muestreado |
| 15 | 7B/5R/3G | 1225.0s | — | — | `BRRRBBBBBGGRGBR` | 1049.7s | — | — | `BRRRBBBBBGGRGBR` | +14.3% | — | muestreado |
| 15 | 7B/8R/0G | 1427.2s | — | — | `BRRRRRRRBBBBBBR` | 1218.7s | — | — | `BRRRRRRBBBBBRRB` | +14.6% | — | exhaustivo |
| 15 | 8B/4R/3G | 1326.5s | — | — | `BRRRBBBBBBGGRGB` | 1120.8s | — | — | `BGBBBBGGRRRBRBB` | +15.5% | — | muestreado |
| 15 | 8B/5R/2G | 1377.9s | — | — | `BRRRBBRBBBBBGGR` | 1206.3s | — | — | `BBRRRRBBBBBBGGR` | +12.5% | — | muestreado |
| 15 | 8B/7R/0G | 1528.8s | — | — | `BRRRRRRBBRBBBBB` | 1257.4s | — | — | `BRRRRBBBRBBBRRB` | +17.8% | — | muestreado |
| 16 | 11B/2R/3G | 1733.5s | — | — | `BBGBBBBRBBBBBGGR` | 1490.9s | — | — | `BGBBGBGBRRBBBBBB` | +14.0% | — | muestreado |
| 16 | 4B/10R/2G | 1071.3s | — | — | `BRRRRBRBRGBRRGRR` | 945.7s | — | — | `BRRRRRRBRBRGRBRG` | +11.7% | — | muestreado |
| 16 | 6B/2R/8G | 852.4s | — | — | `BBBGGGRGGBGGBGBR` | 841.9s | — | — | `BGBBGGGBGGRBBGGR` | +1.2% | — | muestreado |
| 16 | 9B/5R/2G | 1530.6s | — | — | `BRRRBBBBBBGGRRBB` | 1322.1s | — | — | `BRRRBBBBBBGGRRBB` | +13.6% | — | muestreado |
| 17 | 11B/2R/4G | 1685.0s | — | — | `BBGBGRBBBBBBBBGGR` | 1492.3s | — | — | `BBBBBBRBBGBBBGGRG` | +11.4% | — | muestreado |
| 17 | 13B/2R/2G | 2039.0s | — | — | `BBBBBGGRRBBBBBBBB` | 1753.1s | — | — | `BBBBBBBBBBBBBRRGG` | +14.0% | — | exhaustivo (horizonte 5000s, ver nota) |
| 17 | 3B/14R/0G | 1124.0s | — | — | `BRRRRRRRRRRRRRBRB` | 1061.0s | — | — | `BRRRRRRRBRRRRRRRB` | +5.6% | — | exhaustivo |
| 17 | 5B/4R/8G | 819.7s | — | — | `BBBGGRGGGBGGGBRRR` | 800.4s | — | — | `BGBGBGGRGGBGBGRRR` | +2.4% | — | muestreado |
| 17 | 6B/9R/2G | 1325.8s | — | — | `BRRRRRRRBBBRBGRBG` | 1117.3s | — | — | `BRRRRRRBRBBGBRGRB` | +15.7% | — | muestreado |
| 18 | 11B/2R/5G | 1685.0s | — | — | `BBBBBBBGGRGBBBBGGR` | 1487.8s | — | — | `BBBGGBBGGGBBBRBBRB` | +11.7% | — | muestreado |
| 18 | 11B/5R/2G | 1836.1s | — | — | `BRRRBBBBBBBBGGRRBB` | 1584.4s | — | — | `BRRRBBBBBBBBGGRRBB` | +13.7% | — | muestreado |
| 18 | 3B/15R/0G | 1175.3s | — | — | `BRRRRRRRBRRRRRRRRB` | 1112.2s | — | — | `BRRRRRRRBRRRRRRRRB` | +5.4% | — | exhaustivo |
| 18 | 6B/6R/6G | 1137.8s | 1125.103s | -1.12% | `BBGBGBRGGGGRRBRRRB` | 978.0s | 963.823s | -1.45% | `BBGBGBRGGGGRRBRRRB` | +14.0% | **+14.3%** | muestreado (~2000/17M), validada en hardware, ver `docs/dynamic_map_6b6r6g/` |
| 18 | 7B/6R/5G | 1280.3s | — | — | `RBGGRRBBBBBGGRRRGB` | 1056.3s | — | — | `BGBBBGGRRGRBRRBGRB` | +17.5% | — | muestreado (~2000/14M) |
| 18 | 9B/7R/2G | 1633.2s | — | — | `BRRRRBBBBBGGRRBBRB` | 1361.7s | — | — | `BRRRBBRBBBBBGGRRRB` | +16.6% | — | muestreado |
| 18 | 9B/9R/0G | 1784.1s | — | — | `BRRRRRRRBRBBBRBBBB` | 1478.4s | — | — | `BRRRRRRBBBBRRBBRBB` | +17.1% | — | muestreado (~2000/48620) |

**Sim vs. real, las ocho filas validadas:**

| Composición | Fixed diff. (real-sim) | Dinámico diff. (real-sim) | Ahorro sim | Ahorro real | Diferencia ahorro |
|---|---:|---:|---:|---:|---:|
| `BRRBRB` (6 piezas) | -1.29% | -2.14% | +11.2% | +12.0% | +0.8 pp |
| `4B/5R/0G` (9 piezas) | -2.16% | -3.02% | +15.4% | +16.1% | +0.7 pp |
| `5B/4R/0G` (9 piezas) | -1.84% | -1.64% | +17.1% | +16.9% | -0.2 pp |
| `2B/2R/6G` (10 piezas) | +2.12% | +2.86% | +0.0% | -0.7% | -0.7 pp |
| `4B/4R/3G` (11 piezas) | -1.13% | -1.50% | +14.5% | +14.9% | +0.4 pp |
| `5B/5R/2G` (12 piezas) | -1.92% | -2.66% | +17.7% | +18.3% | +0.6 pp |
| `5B/5R/5G` (15 piezas) | -1.18% | -1.41% | +15.8% | +16.0% | +0.2 pp |
| `6B/6R/6G` (18 piezas) | -1.12% | -1.45% | +14.0% | +14.3% | +0.3 pp |

Patrón general en las ocho: la fidelidad sigue dentro de ±3.02% y el ahorro
real queda muy cerca del ahorro simulado. En seis de las siete filas con mejora
simulada positiva el ahorro real es ligeramente mayor que el simulado; en
`5B/4R/0G` queda `0.2 pp` por debajo. `2B/2R/6G` es el caso de control: la
simulación predecía `0.0%` de ahorro y el hardware quedó `0.7 pp` por debajo,
una diferencia pequeña atribuible a variación natural entre corridas.

**Resumen (87 filas, las 87 con % válido):** media +9.96%, mínimo `+0.0%`
(tres composiciones: `2B/2R/6G`, `2B/6R/2G` y `2B/3R/4G` — el dinámico no
encontró nada mejor que el fixed correcto; las tres tienen solo 2 piezas
BLUE, consistente con el hallazgo de que el mecanismo de `WAIT` necesita
tráfico real por bantam para tener algo que optimizar), máximo +19.2%
(`6B/4R/0G`). El rango de 16-18 piezas (+1.2% a +17.5%, la mayoría entre
+11% y +17%) queda dentro del mismo rango que el resto del dataset — sin
señal de que la ganancia colapse ni se dispare al crecer el tamaño, con la
salvedad de que esas filas son también las más muestreadas (42 exhaustivas
de 87 en total). Muy por debajo de la media de ~22% reportada antes del
arreglo del bug de `fixed_reference_*` — esa cifra estaba inflada. Nótese
que en varias filas el mejor orden fixed y el mejor orden dinámico son
literalmente el mismo string: el beam search no encontró un orden inicial
distinto, solo una política de despacho mejor (los `WAIT` de robot1/robot2)
sobre el mismo orden que ya era el mejor bajo fixed.

## Validación física

Ocho de las 87 filas tienen corrida real confirmada contra hardware, con
columnas de tiempo real y de fidelidad (`diff.`) propias. Las otras 79 —
incluidas las 25 generadas el 2026-07-13/14 — son por ahora pura simulación:

- `BRRBRB` (6 piezas) — `docs/dynamic_map_brrbrb/README.md`. Ahorro real
  `66.311 s` (`+12.0%`), fidelidad dentro de ±2.14%.
- `4B/5R/0G` (9 piezas) — `docs/dynamic_map_4b5r0g/README.md`. Ahorro real
  `128.720 s` (`+16.1%`), fidelidad dentro de ±3.02%, 9/9 piezas a destino
  correcto en las dos corridas.
- `5B/4R/0G` (9 piezas) — `docs/dynamic_map_5b4r0g/README.md`. Ahorro real
  `152.422 s` (`+16.9%`), fidelidad dentro de ±1.84%, 9/9 piezas a destino
  correcto en las dos corridas.
- `2B/2R/6G` (10 piezas) — `docs/dynamic_map_2b2r6g/README.md`. Caso de
  control: la simulación predecía `0.0 s` de ahorro y la realidad dio
  `-3.140 s` (`-0.7%`) por variación entre corridas, con fidelidad dentro de
  ±2.86%, 10/10 piezas a destino correcto en las dos corridas.
- `4B/4R/3G` (11 piezas) — `docs/dynamic_map_b6_4b4r3g/README.md`. Ahorro
  real `112.657 s` (`+14.9%`), fidelidad dentro de ±1.5%, 11/11 piezas a
  destino correcto en las dos corridas. Nota: el orden fixed real
  (`BBBBGGGRRRR`, encontrado por el optimizador del dashboard) difiere
  ligeramente del que encontró la etapa 1 de este generador para esa
  composición (`BBGBGRRRGRB`, 766.8s) — la diferencia es de 0.2s, así que la
  tabla usa el validado físicamente como referencia fixed de esa fila.
- `5B/5R/2G` (12 piezas) — `docs/dynamic_map_5b5r2g/README.md`. Ahorro real
  `173.915 s` (`+18.3%`), fidelidad dentro de ±2.66%, 12/12 piezas a destino
  correcto en las dos corridas.
- `5B/5R/5G` (15 piezas) — `docs/dynamic_map_5b5r5g/README.md`. Ahorro real
  `152.218 s` (`+16.0%`), fidelidad dentro de ±1.41%, 15/15 piezas a destino
  correcto en las dos corridas.
- `6B/6R/6G` (18 piezas) — `docs/dynamic_map_6b6r6g/README.md`. Ahorro real
  `161.280 s` (`+14.3%`), fidelidad dentro de ±1.45%, 18/18 piezas a destino
  correcto en las dos corridas.
