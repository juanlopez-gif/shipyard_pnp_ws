# Dataset de mapas dinámicos — fixed vs. dinámico por composición

Date: 2026-07-12

Generado con `scripts/generate_dynamic_map.py` (búsqueda en dos etapas:
prefiltro con la simulación fixed sobre las permutaciones de cada
composición, luego `beam_search()` sobre las mejores `--top-k`) y el batch
runner `scripts/run_overnight_dynamic_maps.sh` / `run_overnight_dynamic_maps_15pc.sh`.
24 composiciones en total: `BRRBRB` (3B/3R, 6 piezas, validada en hardware
real, de `docs/dynamic_map_brrbrb/`) + 17 de 9-12 piezas + 5 de 15 piezas +
`3B3R3G` (la primera prueba de este script, también de
`docs/dynamic_map_brrbrb/`).

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

15 de las 24 composiciones tienen más permutaciones únicas que
`--sample-cap` (2000), así que tanto la etapa 1 (ranking fixed) como la
etapa 2 (beam search, que solo explora los `--top-k` de esa muestra) operan
sobre una muestra aleatoria, no el espacio completo. Para esas filas, "mejor
fixed" y "mejor dinámico" son "mejor encontrado dentro de la muestra", no un
óptimo global probado — el verdadero mejor de cualquiera de los dos lados
podría estar fuera de la muestra. Las filas `exhaustivo` (9 de 24, `BRRBRB`
más las de 9-10 piezas con composiciones menos numerosas) sí cubren el 100%
del espacio de permutaciones.

## Tabla completa (24 composiciones)

Incluye `BRRBRB` (3B/3R, 6 piezas, de `docs/dynamic_map_brrbrb/`),
`4B/5R/0G` (9 piezas, de `docs/dynamic_map_4b5r0g/`), `5B/4R/0G`
(9 piezas, de `docs/dynamic_map_5b4r0g/`), `2B/2R/6G`
(10 piezas, de `docs/dynamic_map_2b2r6g/`), `4B/4R/3G`
(11 piezas, de `docs/dynamic_map_b6_4b4r3g/`) y `5B/5R/2G`
(12 piezas, de `docs/dynamic_map_5b5r2g/`), mas `5B/5R/5G`
(15 piezas, de `docs/dynamic_map_5b5r5g/`) — las siete composiciones
de este dataset con corrida real en hardware confirmada. Las columnas
"real" y "diff." (fidelidad simulación-vs-realidad, `(real-sim)/sim`) solo
tienen valor en esas siete filas.

| n | Composición | Fixed: sim | Fixed: real | Fixed: diff. | Fixed: mejor orden | Dinámico: sim | Dinámico: real | Dinámico: diff. | Dinámico: mejor orden | Ahorro (sim) | Ahorro (real) | Etapa 1 |
|---:|---|---:|---:|---:|---|---:|---:|---:|---|---:|---:|---|
| 6 | 3B/3R/0G | 560.2s | 552.962s | -1.29% | `BRRRBB` | 497.3s | 486.651s | -2.14% | `BRRBRB` | +11.2% | **+12.0%** | exhaustivo (validada en hardware, ver `docs/dynamic_map_brrbrb/`) |
| 9 | 3B/3R/3G | 562.8s | — | — | `BBGBGRRRG` | 514.4s | — | — | `BBGBGRRRG` | +8.6% | — | exhaustivo |
| 9 | 4B/5R/0G | 815.2s | 797.620s | -2.16% | `BRRRRRBBB` | 689.7s | 668.900s | -3.02% | `BRRRBBRRB` | +15.4% | **+16.1%** | exhaustivo (validada en hardware, ver `docs/dynamic_map_4b5r0g/`) |
| 9 | 5B/4R/0G | 916.7s | 899.789s | -1.84% | `BRRRRBBBB` | 759.8s | 747.367s | -1.64% | `BBBBRRRBR` | +17.1% | **+16.9%** | exhaustivo (validada en hardware, ver `docs/dynamic_map_5b4r0g/`) |
| 10 | 2B/2R/6G | 421.5s | 430.423s | +2.12% | `BGRBGGRGGG` | 421.5s | 433.563s | +2.86% | `BGRBGGRGGG` | +0.0% | **-0.7%** | exhaustivo (validada en hardware, ver `docs/dynamic_map_2b2r6g/`) |
| 10 | 2B/6R/2G | 561.1s | — | — | `BRGRRBRRRG` | 561.1s | — | — | `BRGRRBRRRG` | -0.0% | — | exhaustivo |
| 10 | 3B/3R/4G | 541.0s | — | — | `BGBGGGRRRB` | 514.4s | — | — | `BGBBGRGRGR` | +4.9% | — | muestreado |
| 10 | 3B/4R/3G | 614.0s | — | — | `BBBGGRRGRR` | 554.6s | — | — | `BBRGRGRBGR` | +9.7% | — | muestreado |
| 10 | 4B/3R/3G | 715.6s | — | — | `BBGBGGRRRB` | 604.3s | — | — | `BGBBGRRRGB` | +15.6% | — | muestreado |
| 10 | 4B/6R/0G | 866.4s | — | — | `BRRRRRRBBB` | 740.9s | — | — | `BRRRRBBRRB` | +14.5% | — | exhaustivo |
| 10 | 6B/2R/2G | 969.6s | — | — | `BBBBGGBRRB` | 841.9s | — | — | `BGBBRRGBBB` | +13.2% | — | exhaustivo |
| 10 | 6B/4R/0G | 1069.3s | — | — | `BRRRRBBBBB` | 863.9s | — | — | `BBRBRBBRRB` | +19.2% | — | exhaustivo |
| 11 | 3B/4R/4G | 611.1s | — | — | `BGGGGBRRRRB` | 567.1s | — | — | `BGBGBRGRGRR` | +7.2% | — | muestreado |
| 11 | 4B/3R/4G | 707.2s | — | — | `BBGGGGRRRBB` | 604.3s | — | — | `BGBBGGRGRRB` | +14.6% | — | muestreado |
| 11 | 4B/4R/3G | 767.0s | 758.330s | -1.13% | `BBBBGGGRRRR` | 655.5s | 645.673s | -1.50% | `BBGBGRRRGRB` | +14.5% | **+14.9%** | muestreado (validada en hardware, ver `docs/dynamic_map_b6_4b4r3g/`) |
| 12 | 2B/5R/5G | 553.1s | — | — | `BGRBGGGRGRRR` | 548.3s | — | — | `GBRGGBRGRRGR` | +0.9% | — | muestreado |
| 12 | 4B/4R/4G | 744.9s | — | — | `BGGBGGRRRBRB` | 659.3s | — | — | `BGBBGRRGGRBR` | +11.5% | — | muestreado |
| 12 | 5B/2R/5G | 768.4s | — | — | `BBBGGGBRGBGR` | 720.0s | — | — | `BBBGGBRGBGRG` | +6.3% | — | muestreado |
| 12 | 5B/5R/2G | 968.0s | 949.410s | -1.92% | `BRRRRBBBBRGG` | 796.7s | 775.495s | -2.66% | `BBRGRRBRBRGB` | +17.7% | **+18.3%** | muestreado (validada en hardware, ver `docs/dynamic_map_5b5r2g/`) |
| 15 | 3B/8R/4G | 830.6s | — | — | `BGRGRRBRRBGRRRG` | 767.3s | — | — | `BGRGRRBRRBGRRRG` | +7.6% | — | muestreado |
| 15 | 4B/3R/8G | 672.7s | — | — | `BGBBRRGGGGGBGRG` | 666.1s | — | — | `BGBBRRGGGGGBGRG` | +1.0% | — | muestreado |
| 15 | 5B/5R/5G | 963.8s | 952.436s | -1.18% | `RBBGGGGBGBRRRRB` | 811.7s | 800.218s | -1.41% | `BGRBGGGRRBRBRGB` | +15.8% | **+16.0%** | muestreado (validada en hardware, ver `docs/dynamic_map_5b5r5g/`) |
| 15 | 8B/4R/3G | 1326.5s | — | — | `BRRRBBBBBBGGRGB` | 1120.8s | — | — | `BGBBBBGGRRRBRBB` | +15.5% | — | muestreado |
| 15 | 8B/7R/0G | 1528.8s | — | — | `BRRRRRRBBRBBBBB` | 1257.4s | — | — | `BRRRRBBBRBBBRRB` | +17.8% | — | muestreado |

**Sim vs. real, las siete filas validadas:**

| Composición | Fixed diff. (real-sim) | Dinámico diff. (real-sim) | Ahorro sim | Ahorro real | Diferencia ahorro |
|---|---:|---:|---:|---:|---:|
| `BRRBRB` (6 piezas) | -1.29% | -2.14% | +11.2% | +12.0% | +0.8 pp |
| `4B/5R/0G` (9 piezas) | -2.16% | -3.02% | +15.4% | +16.1% | +0.7 pp |
| `5B/4R/0G` (9 piezas) | -1.84% | -1.64% | +17.1% | +16.9% | -0.2 pp |
| `2B/2R/6G` (10 piezas) | +2.12% | +2.86% | +0.0% | -0.7% | -0.7 pp |
| `4B/4R/3G` (11 piezas) | -1.13% | -1.50% | +14.5% | +14.9% | +0.4 pp |
| `5B/5R/2G` (12 piezas) | -1.92% | -2.66% | +17.7% | +18.3% | +0.6 pp |
| `5B/5R/5G` (15 piezas) | -1.18% | -1.41% | +15.8% | +16.0% | +0.2 pp |

Patrón general en las siete: la fidelidad sigue dentro de ±3.02% y el ahorro
real queda muy cerca del ahorro simulado. En cinco de las seis filas con mejora
simulada positiva el ahorro real es ligeramente mayor que el simulado; en
`5B/4R/0G` queda `0.2 pp` por debajo. `2B/2R/6G` es el caso de control: la
simulación predecía `0.0%` de ahorro y el hardware quedó `0.7 pp` por debajo,
una diferencia pequeña atribuible a variación natural entre corridas.

**Resumen (24 filas, corregidas):** media +10.8%, mínimo −0.0% (`2B/2R/6G` y
`2B/6R/2G`: el dinámico no encontró nada mejor que el fixed correcto),
máximo +19.2% (`6B/4R/0G`). Muy por debajo de la media de ~22% reportada
antes del arreglo — esa cifra estaba inflada por el bug descrito arriba.
Nótese que en varias filas (`4B/4R/3G`, `3B/8R/4G`, `4B/3R/8G`) el mejor
orden fixed y el mejor orden dinámico son literalmente el mismo string: el
beam search no encontró un orden inicial distinto, solo una política de
despacho mejor (los `WAIT` de robot1/robot2) sobre el mismo orden que ya
era el mejor bajo fixed.

## Validación física

Siete de las 24 filas tienen corrida real confirmada contra hardware, con
columnas de tiempo real y de fidelidad (`diff.`) propias:

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

Las otras 17 filas son, por ahora, pura simulación.
