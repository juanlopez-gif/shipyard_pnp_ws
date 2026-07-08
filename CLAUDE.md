# shipyard_pnp — notas de contexto para Claude

## Transferencia al depositar enganchada a PLACE_DONE, no al completado del comando (2026-07-07)

Tras arreglar el bloqueo de `ml_node.py` por zona, el usuario detectó que
EXPECTED seguía sin actualizarse al depositar, solo en xarm1/xarm2 (C3
funcionaba, conveyor1/conveyor2 no). Causa real, confirmada leyendo los
adaptadores reales (no hipótesis): varios de ellos meten un `move_home()`
**dentro del mismo comando** justo después de `PLACE_DONE`, antes de
devolver `COMPLETED` — `xarm2_adapter.py::_place_to_c1s1`,
`xarm1_adapter.py::_place_to_c2s1`/`_place_to_laser`,
`robot2_adapter.py`'s BANTAM/IBS/SCRAP. Otros (`_place_to_c3` de xarm2,
`_place_to_c4`/C4 de robot2) devuelven justo tras `PLACE_DONE` sin ese
`move_home` interno — comentario explícito en el código: *"Retraction
happens in move_home so the PLACED_C3/C4 callback fires immediately after
vacuum_off"*. Como la transferencia gripper→destino vivía en el callback
`on_complete` del comando MOVE_PIECE completo (`task_state==COMPLETED`),
para las rutas con `move_home` interno no se disparaba hasta volver a
home — de ahí que solo fallara en conveyor1/conveyor2 (xarm1/xarm2) y no en
C3/C4.

**Arreglado con un segundo hook simétrico al de `PICK_DONE`**
(`factory_supervisor.py`): `register_place_target(entity, target_loc)` se
llama en cada despacho junto a `register_pick_source`, y
`_apply_resource_state` transfiere `gripper→target` en cuanto el
`resource_state` real llega a `PLACE_DONE` — sin esperar a
`task_state==COMPLETED`. El `transfer_via_gripper` del `on_complete`
original queda como fallback inofensivo (si el gripper ya está vacío,
intenta `source→target` directo, que falla en silencio si `source` también
ya está vacío). No hacía falta tocar robot1 (`unloading_rules.py`): ya
transfiere en el completado de su comando `RELEASE` explícito, que no tiene
este problema.

## `/factory/system_state` bajado a 0.5s — el muestreo de 2s se comía la mejora en xArms (2026-07-07)

Al arreglar el desbloqueo temprano de `ml_node.py` (ver sección más abajo)
con datos EXPECTED (`pipeline.queues`) en vez de `resource_state`, funcionaba
claramente bien para robot1/robot2 pero apenas se notaba en xarm1/xarm2.
Verificado en `shipyard_pnp_ws.resource_state_change` (DB real, no hipótesis):
xarm1/xarm2 SÍ emiten los mismos estados granulares (`PICKING`→`PICK_DONE`→
`PLACING`→`PLACE_DONE`) que robot1/robot2 — no era un problema de datos. La
causa real: sus ciclos completos duran ~14s (frente a ~30-130s de
robot1/robot2), con `PICK_DONE` ocurriendo a ~4s de ese total — un margen de
mejora de ~10s que el muestreo de `/factory/system_state` cada 2s se comía
casi entero (el primer hueco detectable solía caer ya en `PLACING`/
`PLACE_DONE`, ~3-4s antes del final, no en el pick real). Para robot1/robot2,
el mismo mecanismo sobre un ciclo de ~30s+ deja mucho más margen y la mejora
es obvia (~10-20s antes). **Arreglado bajando el timer de
`_publish_system_state` de 2.0s a 0.5s** en `factory_supervisor.py` — no es
un fix de lógica, es de latencia de muestreo.

## `ml_node.py`: cada zona de conveyor la tocan DOS entidades, solo se vigilaba a una (2026-07-07)

Tras el fix del intervalo de publicación, el usuario reportó que el problema
persistía **únicamente en el PLACE de xarm1 y xarm2**. Causa real: cada zona
de conveyor intermedia la usan dos entidades — una la coloca, otra la recoge
más tarde — pero el bloqueo de `ml_node.py` solo vigilaba la tarea de la que
recoge:

| Zona | Coloca | Recoge | Vigilado antes |
|---|---|---|---|
| conveyor1 | xarm2 (`FEED_TO_C1S1`) | xarm1 | solo xarm1 |
| conveyor2 | xarm1 (`C1S2_TO_C2S1`/`LASER_TO_C2S1`) | robot2 | solo robot2 |
| c3_location | xarm2 (`FEED_GREEN_TO_C3`) | robot1 | solo robot1 |
| c4_location | robot2 (`CLASSIFY_C2S2_TO_C4`/`BANTAM_TO_C4`) | robot1 | solo robot1 |

Como nadie vigilaba el lado del PLACE de xarm1/xarm2 (ni el de robot2→C4,
mismo fallo, aún no reportado), la cámara nunca se bloqueaba durante esa
maniobra de depósito — la única mitad sin proteger. Arreglado añadiendo el
lado que faltaba a cada `*_task_active` (`XARM2_C1S1_TASK`, `XARM2_C3_TASK`,
`XARM1_C2S1_PLACE_TASKS`, `ROBOT2_C4_PLACE_TASKS`, junto a
`XARM1_C1S2_TASKS` en `ml_node.py`). IBS no lo necesitaba: coloca
(`CLASSIFY_C2S2_TO_IBS`) y recoge (`IBS_TO_BANTAM`) los hace robot2, ya
cubiertos ambos por `ROBOT2_IBS_TASKS`.

De paso, `_early_unblock` (antes solo detectaba que el recuento de EXPECTED
BAJARA, válido para quien recoge) ahora detecta cualquier CAMBIO de recuento
— sube cuando quien coloca ya depositó, baja cuando quien recoge ya se la
llevó.

**Segunda vuelta — el lado que coloca necesita gate de pinza, no solo
task_name (2026-07-07):** el usuario confirmó que C3 (coloca xarm2) ya
funcionaba bien, pero conveyor1/conveyor2 seguían mal. Causa: `task_name`
está activo desde que se DESPACHA la tarea, no desde que el brazo llega a la
zona de destino — para `FEED_TO_C1S1`/`FEED_GREEN_TO_C3` eso incluye ir a
recoger del stack inicial; para `C1S2_TO_C2S1`/`LASER_TO_C2S1` incluye ir a
recoger de conveyor1/laser_bed. Bloquear por task_name activo sin más tapaba
conveyor1/conveyor2 (que tienen tráfico solapado de varias piezas seguidas)
durante toda esa fase previa, no relacionada — algo que en C3 casi nunca se
notaba por ser una ruta GREEN mucho más esporádica. Arreglado exigiendo
ADEMÁS que la pinza correspondiente (`queues["xarm1_gripper"]`/
`xarm2_gripper`/`robot2_gripper`, la misma cola que llena el hook de
`register_pick_source` en `factory_supervisor.py`) tenga la pieza en mano —
así el lado que coloca solo cuenta como activo entre el pick real y el
place real, no desde el despacho.

## Shape real desde `stack_status` (proceso externo) — patrón calcado de shipyard_core (2026-07-07)

`camera_adapter.py` (nuestro GlobalVision, cámara del stack inicial) detecta
color/ocupación por HSV en vivo pero **nunca infiere shape a propósito**
(`GlobalVisionCameraAdapter` docstring: "Shape is intentionally not
inferred"; `LOCATE_NEXT_PIECE` siempre devuelve `"shape": "UNKNOWN"`). Antes
de este cambio, toda pieza de `initial_stack` quedaba con shape=UNKNOWN
hasta que la clasificaba la visión de C2S2 mucho más tarde en el pipeline.

Se investigó cómo resuelve esto `shipyard_core` (repo hermano, ya en
producción) antes de tocar nada aquí: allí `GlobalVision` tampoco publica
`/stack_status` ni tiene shape fiable propia — lo publica un **proceso
externo ajeno al repo** (mismo patrón que nuestro `ml_node.py`, que corre en
otro ordenador). El Supervisor de shipyard_core NO usa ese topic para elegir
qué pieza coger (eso lo sigue decidiendo la detección de color en vivo); solo
lo usa para pegar la shape real al comando de pick, indexando por `slot_id`
que la propia detección en vivo ya resolvió (`slot_to_piece[slot]["shape"]`,
ver `feeding_rules.py` de shipyard_core, sin equivalente a una cola FIFO que
se consuma — es un mapa estático que se sobrescribe entero en cada mensaje).

**Adaptado tal cual** a nuestra arquitectura:
- `factory_supervisor.py`: `self._stack_status_shapes: dict = {}` (slot_id →
  shape), suscripción a `stack_status` (topic sin barra inicial, lo publica
  `ml_node.py` desde el otro ordenador) → `_on_stack_status` parsea
  `{"s1.1": "GREEN_CIRCLE", "s1.2": "null", ...}` quedándose solo con la
  mitad de shape (`"CIRCLE"`), descartando `"null"`. `get_stack_status_shape(slot_id)`
  como accessor.
- `feeding_rules.py::_on_locate_complete`: justo después de que
  `LOCATE_NEXT_PIECE` devuelva `slot_id` (decidido por nuestra propia
  detección en vivo, sin cambios ahí), si `fs.get_stack_status_shape(slot_id)`
  tiene algo, sustituye al `shape="UNKNOWN"` de camera_adapter.py antes de
  `assign_color_shape("initial_stack", color, shape)` — sigue operando sobre
  `q[0]` de `initial_stack` (cabeza de FIFO), como todo `piece_tracker.py`.

Si `stack_status` no llega nunca (proceso externo caído), el comportamiento
es exactamente el de antes: shape se queda en `"UNKNOWN"` — no es un
requisito duro de arranque como en shipyard_core (allí el feeding entero se
bloquea sin ese topic; aquí el color en vivo es suficiente para seguir
produciendo).

## ml_node.py — vive fuera de este repo (2026-07-07)

Nodo de visión (YOLO + bloqueo por estado de robot + escritura a
`vision_slot_snapshot`/`vision_conveyor_snapshot` + display) que el usuario
lanza manualmente en el ordenador de las cámaras, no en el de
`factory_supervisor`. Se adaptó una versión legacy (indentación rota +
topics de un sistema anterior que ya no existen) para hablar con
`/factory/system_state` y `/factory/run_id`, pero **por decisión del
usuario se eliminó del repo** — no se registra en `setup.py`. Si vuelve a
aparecer para adaptar: el punto clave es que el estado de bloqueo por grupo
(stack/conveyor1-4/IBS) sale de `cycles.active_entity_cycles[entity].task_name`
y `resources.robots[entity]` en `/factory/system_state`, y "qué pieza se
espera en cada sitio" sale de `pipeline.queues` (mapeo de nombres:
conveyor3→`c3_location`, conveyor4→`c4_location`, ibs→
`intermediate_blue_stack`, ver `factory/piece_tracker.py`
PIPELINE_LOCATIONS) — no de los viejos topics `/xarm1/status`,
`/robot1/status`, `/supervisor/*/piece_color`, que no existen.

## Control layer: piezas intrusas ya no consumen el hueco del mapa (arreglado 2026-07-07)

Bug real encontrado: en `classification_rules.py`, `fs._map_note_dispatch("robot2",
"CLASSIFY_C2S2")` se llamaba en `evaluate()` **antes** de que la visión
resolviera el color/ruta real de la pieza en C2S2. El chequeo de coincidencia
en `_map_note_dispatch` tenía un caso especial genérico
(`actual_category == "CLASSIFY_C2S2" and expected_task.startswith("CLASSIFY_C2S2")`)
que hacía `matched=True` para **cualquier** disparo de clasificación, sin
importar en qué acababa resolviendo la visión. Consecuencia: si a C2S2 llega
una pieza que la visión no reconoce (SCRAP) cuando el mapa esperaba un
`CLASSIFY_C2S2_TO_C4` normal, el puntero del mapa para robot2 avanzaba igual
—como si esa pieza intrusa hubiera cumplido la expectativa— y la pieza roja
real que sí se esperaba quedaba comparada contra el **siguiente** hueco del
mapa, desincronizando robot2 para el resto de la corrida. Silencioso: no
saltaba ningún timeout ni alarma porque, para el código, "coincidió".

**Arreglado** dividiendo `_map_note_dispatch` en dos fases en
`factory_supervisor.py`:
- `_map_begin_dispatch(entity)` — se llama en el momento de decidir el
  despacho (aunque el resultado final aún no se conozca), solo cierra la
  contabilidad del temporizador de espera para que no gotee a una espera
  posterior no relacionada. Devuelve `wait_info`.
- `_map_resolve_dispatch(entity, actual_category, wait_info)` — compara la
  categoría **ya resuelta** contra lo que esperaba el mapa (match exacto,
  sin el caso especial genérico) y solo entonces avanza el puntero. Si no
  coincide y tampoco fue un timeout de gracia (`gave_up_after`), es un
  **ciclo intruso**: se registra en `alarm_event`
  (`MAP GUIDANCE INTRUDER`) y en el metadata del `cycle_event`
  (`map_outcome: "intruder"`), pero el puntero **no se toca** — el hueco
  esperado sigue debiéndose y se compara de nuevo en el siguiente disparo
  de esa entidad.
- `_map_note_dispatch(entity, actual_category)` se queda como envoltorio de
  una sola llamada (`_map_resolve_dispatch(entity, actual_category,
  _map_begin_dispatch(entity))`) para los sitios que ya conocen su
  categoría final en el momento del disparo (`unloading_rules.py`,
  `processing_rules.py`, y las rutas BANTAM_TO_C4/IBS_TO_BANTAM de
  `classification_rules.py`) — sin cambios de comportamiento ahí.

En `classification_rules.py`: `evaluate()` ahora llama a
`fs._map_begin_dispatch("robot2")` al despachar la clasificación (guarda
`wait_info`, se lo pasa a `_on_vision_complete`), y `_on_vision_complete`
llama a `fs._map_resolve_dispatch("robot2", task_name, wait_info)` una vez
conocida la ruta real (`task_name = f"CLASSIFY_C2S2_TO_{route}"`), antes de
fusionar `fs._map_pop_dispatch_metadata("robot2")` en el `cycle_event` vía
`update_entity_cycle(..., **metadata)` (los kwargs desconocidos para
`EntityCycle` se fusionan en `.metadata` sin pisar `pick_position`, ver
`cycle_tracker.update_entity_cycle`).

Verificado con test aislado (`types.MethodType` sobre `FactorySupervisor`):
un intruso resuelto a SCRAP no avanza el puntero, la pieza roja real
posterior sigue comparándose contra el mismo hueco y sí lo consume, y el
caso normal (sin intrusos) sigue funcionando igual que antes.

## Criterio de inicio/fin al comparar una corrida real contra la simulación

**NUNCA** usar `production_run.started_at` / `finished_at` como t0/t_fin de la
corrida real — esas columnas se escriben al confirmar el orden (antes de que
se mueva ningún robot) y al marcar la corrida como terminada en base de datos,
no al instante físico en que empieza/acaba la producción. Usarlas como ancla
introduce un sesgo constante (~20-25s de diferencia observados) que hace
parecer que la realidad va mucho más retrasada de lo que realmente va.

- **t0 real** = `started_at` del primer `cycle_event` de `xarm2`
  (`FEED_TO_C1S1` o `FEED_GREEN_TO_C3` de la primera pieza) — el instante en
  que xarm2 va a por la primera pieza del stack.
- **t_fin real** = instante en que termina la fase `RETURNING_HOME` del
  último `cycle_event` de `robot1` (dentro de su columna `phases` jsonb) —
  cuando robot1 vuelve a home tras depositar la última pieza. No usar
  `started_at + total_duration_s` del último ciclo de cualquier entidad sin
  comprobar primero cuál es realmente la última en terminar.

## Duración total simulada — `compute_expected_schedule` ya incluye el RETURN_HOME (arreglado 2026-07-07)

`compute_expected_schedule()` (en `factory/expected_schedule.py`) **descartaba**
los eventos de la simulación con `piece=None` antes de agrupar ciclos. El
evento `RETURN_HOME` sí lleva pieza (entra en el grupo), pero solo marca el
*inicio* de ese movimiento — el evento que marca su fin es un
`IDLE piece=None` inmediatamente después. Al descartarlo, el `dur`
calculado de **cada** ciclo de las 4 entidades que hacen `RETURN_HOME`
excluía el tiempo de vuelta a home (quedaba "escondido" como hueco antes del
siguiente ciclo en vez de parte de la barra) — no solo el último ciclo del
run, medido así en la corrida GGGGGGRRRRRRBBBBBB del 2026-07-07:

| entidad | tiempo de RETURN_HOME que faltaba por ciclo |
|---|---|
| robot1  | ~9.8s |
| robot2  | ~6.7s |
| xarm1   | ~1.8s |
| xarm2   | ~2.0s |

**Arreglado**: la función ya no descarta eventos `piece=None`; el agrupador
solo cierra un ciclo al ver un marcador de arranque o una pieza *real*
distinta — un evento sin pieza (como ese `IDLE`) siempre extiende el ciclo
abierto. Con esto, `dur`/`t_end` de cada ciclo ya reflejan el regreso a home
real, y `max(t_start+dur)` sobre todo el schedule coincide exactamente con
`optimizer_run.best_time_s` (verificado: 1188.1s en ambos, corrida del
2026-07-07) — ya no hace falta ir a esa tabla ni recalcular aparte para la
duración total.

## bantam y laser — NO extender su ciclo hasta que otra entidad los recoge (revertido/arreglado 2026-07-07)

Se probó primero añadir un track `WAITING_IDLE_TO_ROBOT2` en
`bantam_machine_process` para nombrar la espera entre `FINISHED` (puerta
abierta) y que robot2 recoja la pieza. **Revertido** — no era lo correcto.
Motivo: el `cycle_event` REAL de bantam (y de laser) se marca completo justo
en `FINISHED`, sin esperar a que robot2/xarm1 vengan a recogerlo — esa
recogida se registra como el ciclo PROPIO de robot2 (`BANTAM_TO_C4`) o de
xarm1 (`LASER_TO_C2S1`), no como parte del ciclo de bantam/laser. El fix
general del `RETURN_HOME` (piece=None ya no se descarta, ver arriba) extendía
el ciclo simulado de bantam/laser através del `IDLE piece=None` que dispara
robot2/xarm1 al recogerlo — pero ese `IDLE` lo causa la OTRA entidad, no
bantam/laser haciendo su propio regreso a home (no se mueven, son máquinas
fijas). Resultado antes de arreglarlo: bantam simulado se disparaba a
60-327s de duración frente a los ~49s reales — un desajuste artificial, no
un problema real.

**Arreglado con `SCHEDULE_HARD_END`** en `expected_schedule.py`:
`{"laser": {"FINISHED"}, "bantam": {"FINISHED"}}` — cierra el grupo del
ciclo inmediatamente al ver ese estado, sin esperar a un marcador o cambio
de pieza, así ningún evento posterior (venga de quien venga) lo extiende.
Verificado: bantam vuelve a ~48.5s simulado (vs ~49s real, diff ~0.5s) y
laser a ~22.8s (vs ~22-23s real) — comparación real↔mapa coherente otra vez,
sin tocar el total simulado (sigue en 1188.1s, bantam/laser nunca fueron la
entidad que determina el final de la corrida).

## Herramienta: comparación real vs. mapa + Gantt (`run_report.py`)

Dado un `run_id` (o la corrida más reciente si se omite), genera la tabla de
comparación ciclo a ciclo (real vs. mapa, con estado: coincidió / esperó al
mapa / timeout / descartado / sin equivalente) y un informe HTML con Gantt +
tabla de detalle.

```bash
source /opt/ros/*/setup.bash
source install/setup.bash

# tabla por terminal, corrida más reciente
python3 -m shipyard_pnp.factory.run_report

# corrida concreta + JSON + HTML (Gantt interactivo, para abrir en el navegador)
python3 -m shipyard_pnp.factory.run_report 20260707_140007_GGGGGGRRRRRRBBBBBB \
    --out results/ --html results/gantt_20260707_140007.html

# PDF real (vectorial, paginado) -- no depende del navegador ni de "imprimir"
python3 -m shipyard_pnp.factory.run_report 20260707_140007_GGGGGGRRRRRRBBBBBB \
    --pdf results/gantt_20260707_140007.pdf
```

Archivos: `factory/run_report.py` (lógica), `factory/run_report_template.html`
(plantilla del Gantt HTML interactivo) y `factory/run_report_pdf.py` (PDF
nativo con `reportlab`). Usa las mismas credenciales de DB que `db_writer.py`
(`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`, default
`100.115.213.16` / `twin_mes_db`).

**Sobre el PDF (2026-07-07)**: se probó primero "Guardar como PDF" desde el
HTML (botón + `window.print()`) pero no es fiable — el problema real no es
el scroll en pantalla, es que al imprimir el navegador trata el ancho de la
página como el viewport y **recorta** (no pagina) cualquier cosa más ancha
que la hoja; además `window.print()` puede no funcionar según dónde se vea
el artifact (iframe/webview embebido). Se abandonó ese enfoque. La solución
que funciona es `run_report_pdf.py`: genera el PDF directamente con
`reportlab` (instalado vía `pip3 install --user --break-system-packages
reportlab` — no está en apt sin sudo en esta máquina). Archivo real en
disco, ruta exacta que se pase en `--pdf`, sin pasar por el navegador para
nada. El Gantt va en **una única página horizontal** tan ancha como haga
falta (PDF admite páginas de tamaño arbitrario, muy por debajo del límite de
200in/lado de la especificación) — nada se comprime ni se corta. La tabla de
detalle sí se pagina normal, en A4 horizontal, por filas.

**Secciones del PDF (2026-07-07)**: además del Gantt y el detalle
cronológico, tiene "Detalle por componente" (mismas columnas, pero agrupado
por entidad con una fila de cabecera `entidad (N ciclos)` — usa
`by_entity`, ya calculado para el Gantt) y "Transferencias de piezas"
(de la tabla `piece_transfer`, agrupado por pieza con cabecera
`piece-XXX (N movimientos)`, mostrando el recorrido físico real: p.ej.
verde = `initial_stack → c3_location → final_green_stack`; roja =
`initial_stack → conveyor1 → laser_bed → conveyor2 → c4_location →
final_red_circle`). El renderizado de tabla paginada se factorizó en
`draw_table_pages()` (acepta filas normales y filas de cabecera de grupo),
reutilizado por las tres secciones.
