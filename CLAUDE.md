# shipyard_pnp — notas de contexto para Claude

## Set de corridas válidas para calibración/total-time: filtro correcto y el porqué del -25.97% (2026-07-08)

Tras el análisis de arriba, el usuario detectó dos fallos reales en mi
propio criterio de "corrida válida":

1. **`route='SCRAP'` no detecta intrusas mal enrutadas.** `20260708_
   175520_BR` pasaba mi filtro (0 filas con `route='SCRAP'`) pero tenía 2
   piezas `intruder-*` de ANTES del fix de forzado a SCRAP de hoy — se
   enrutaron a C4 como legítimas. El filtro correcto es
   `piece_id LIKE 'intruder-%'`, no `route='SCRAP'`.
2. **No basta con "sin descartes"** — hace falta que el 100% de los ciclos
   de la corrida coincidan con el mapa (`status in ("matched","followed")`
   en `run_report.build_report()`). Una corrida puede no tener ningún
   descarte ni intrusa y aun así tener un ciclo "sin equivalente en el
   mapa" que la invalida para comparar tiempos totales.

Con ambos filtros aplicados sobre las 29 corridas `COMPLETED`, bajan a 26;
`20260703_184708_RRRRRRBBBBBB` pasa igualmente ese filtro (sus 12 ciclos SÍ
tienen equivalente exacto en tarea+cycle_number) pero muestra un -25.97% de
error total — investigado con la traza cruda del simulador
(`system.state_changes`) y confirmado real, no ruido: **bantam se queda
lista a los 125.5s y el simulador no la recoge hasta los 539.95s** (~414s de
hambreado), porque `robot2_process`'s prioridad P1 (clasificar C2S2) gana
siempre que hay algo en C2S2, sin ningún mecanismo que ceda el turno —
mientras que el robot real sí lo tiene (ver sección de abajo). El usuario
pidió excluir esta corrida también por nombre, no solo por el filtro
automático, dado lo atípico del caso. **Set final: 25 corridas**, guardado
en `valid_runs.py` (scratchpad) para reutilizar. Con este set: mean
|diff%|=4.08%, mediana=4.54%, máximo=7.66% — sin ningún otro caso por
encima del 8%.

## Hambreado de bantam en el simulador: causa raíz encontrada con traza cruda, arreglo parcial aplicado (2026-07-08)

Diagnóstico exacto vía `system.state_changes` (traza cruda del SimPy) para
el orden de la corrida -25.97%: `c2s2_occupied` está en `True`
prácticamente el 100% del tiempo durante los 414s de hambreado — no es la
profundidad de la cola de `conveyor2`, es que el punto de recogida se
rellena casi sin descanso. Se probó (a petición explícita del usuario, tras
elegir esa opción sobre una recalibración conjunta de constantes) modelar
`conveyor2` como cola real completa en vez de un único punto de ocupación
— la condición de P2 ("recoger bantam") ahora exige
`not c2s2_occupied and not pieces_on_conveyor2` en vez de solo
`not c2s2_occupied`, replicando `count("conveyor2")==0` de
`classification_rules.py` exactamente. Verificado con la misma traza: el
cambio no mueve ni un segundo el resultado (bantam se sigue recogiendo a
t=539.95s clavado) porque `pieces_on_conveyor2` casi siempre valía 0 o 1
mientras `c2s2_occupied` ya bloqueaba por sí solo — la cola nunca fue el
cuello de botella real en este caso. Confirmado además con muestreo directo
de estado cada 1s: en los pocos instantes donde `c2s2_occupied=False`,
`c4_occupied=True` bloqueaba P2 de todas formas.

**La causa raíz real es un mecanismo de control que el simulador no tiene
en absoluto, no una condición de cola mal puesta**: `classification_rules.
py`'s `evaluate()`, cuando C2S2 tiene una pieza lista pero el mapa/horario
precalculado anticipa que el siguiente turno de robot2 debería ser
`BANTAM_TO_C4`, hace que el robot real se **detenga a propósito** (hasta
`MAP_GRACE_SEC`) en vez de clasificar de inmediato — cediendo la ventana a
bantam. El simulador es puramente reactivo/goloso: P1 (clasificar) gana
siempre que hay algo en C2S2, sin ningún mecanismo de "esperar a propósito
según lo que el propio horario anticipa". Portar ese mecanismo al
simulador es estructuralmente circular (el simulador es lo que *genera*
ese horario, no algo que pueda consultarlo mientras lo genera) — es una
reestructuración del motor de simulación, no un ajuste de condición.
Se dejó el cambio de cola real aplicado (es más fiel a la regla física y no
empeoró nada, aunque tampoco resolvió el caso concreto) y se paró antes de
acometer la reestructuración mayor, pendiente de decisión del usuario.

## Desfase real-vs-simulación: root cause confirmado para los 2 últimos REVISAR, ambos re-probados y re-revertidos con más datos (2026-07-08)

Con 29 corridas válidas (`status=COMPLETED`, 0 scrap, 0 discarded — incluye
ya la corrida limpia de 18 piezas intercaladas GRB×6), `run_calibration.py`
deja solo 2 tareas en REVISAR (el resto <5%): `robot2/CLASSIFY_C2S2_TO_
BANTAM` (+7.7%, n=21) y `xarm2/FEED_GREEN_TO_C3` (+5.5%, n=127). Se
investigó el ROOT CAUSE real de cada una leyendo el código de los adaptadores
reales (no solo ajustando constantes a ciegas):

- **`CLASSIFY_C2S2_TO_BANTAM`**: no es una constante mal calibrada, es una
  **fase física real que el simulador nunca modeló**. `robot2_adapter.py::
  _place_bantam()` (línea 176) llama a `self.move_home()` de forma
  incondicional tras despejar bantam, y el `cycle_event` real no cierra
  hasta que ese `MOVE_PIECE` completo (con el `move_home` incluido)
  termina — el comentario "no home command" de `classification_rules.py`
  describe lo que la orquestación CREE que pasa, no lo que el adaptador
  realmente hace.
- **`FEED_GREEN_TO_C3`**: aquí la estructura del simulador SÍ es correcta
  (comando de place separado del de home, igual que en la realidad) — es
  una constante mal calibrada. `xarm2_adapter.py::_place_to_c3` usa 3
  waypoints con velocidad decreciente (`30/100 → 25/80 → 20/60`) frente a
  los 2 waypoints a velocidad plena de `_place_to_c1s1` — un waypoint extra
  y una colocación final deliberadamente más lenta, exclusivos de la ruta
  GREEN/C3.

**Los dos se implementaron y se volvieron a revertir**, con el mismo
criterio ya establecido (medir el makespan total real-vs-sim en las 29
corridas, no solo el promedio de la tarea aislada):

- `ROBOT2_RETURN_BANTAM=5.2` (fase nueva, insertada antes de
  `bantam_robot2_clear.succeed()` para que retrase también el arranque del
  job de bantam igual que en la realidad): mean |diff%| 5.30%→5.33%, 12/29
  corridas peor vs 5 mejor. Mismo patrón que el intento anterior (10 peor/4
  mejor sobre 26 corridas) — confirma que NO es un artefacto de dataset
  pequeño, es un efecto estructural: añadir ese tiempo, se llame como se
  llame la fase, sigue siendo tiempo serie de robot2 antes de quedar IDLE,
  y empuja el makespan total más tarde en más corridas de las que arregla.
- `XARM2_PLACE_C3=5.94` (mismo valor ya probado antes): mean |diff%|
  5.30%→5.35%, mediana 4.54%→5.09%. Mismo patrón, ahora confirmado dos
  veces.

**Conclusión**: ambos desfases son reales y su causa física está
identificada con certeza (no es ruido ni mala calibración superficial),
pero ninguno de los dos se puede cerrar con un ajuste aislado de una sola
constante — el propio comentario del intento anterior ya lo decía ("needs a
coordinated multi-constant recalibration pass") y con 3 y 4 corroboraciones
independientes (2 intentos cada uno, datasets de 26 y 29 corridas) el
diagnóstico se sostiene. Quedan documentados en los comentarios de
`shipyard_sim.py::Config` con la magnitud exacta y la razón física, listos
para una pasada de recalibración coordinada si se aborda en el futuro —
mientras tanto, `ROBOT2_PLACE_BANTAM=14.0` y `XARM2_PLACE_C3=5.15` (valores
originales) se quedan como están.

## Bug de fondo real — una cámara de robot escribía directamente sobre EXPECTED, anulando toda la detección de mismatch (2026-07-08)

El usuario paró en seco toda la sesión de intrusos con una pregunta de
arquitectura, no de síntoma: **EXPECTED es software puro (`PieceTracker`) —
ninguna cámara de ningún robot puede jamás escribir sobre él, solo se
compara contra él.** Repasando el código con ese criterio se encontró que
eso era exactamente lo que llevaba pasando toda la sesión, en un sitio que
no era `classification_rules.py`.

`FactorySupervisor._apply_vision_result()` (`factory_supervisor.py:658`) es
un hook GENÉRICO que se ejecuta para **cualquier** mensaje de status
entrante que traiga `color`+`shape`, independientemente de qué comando esté
en curso. Escribía sobre `PieceTracker` para tres casos: `initial_stack`
(GlobalVision, la asignación inicial legítima), `conveyor2` (la visión LOCAL
de robot2 en C2S2) y `c4_location` (la visión local de robot1). Y crucial:
en `_on_status_msg` este hook se llama en la línea ~508, **ANTES** de
`vc.on_status_received(payload)` en la línea ~524 — que es lo que dispara el
callback `on_complete` de cada comando. Es decir: para el mismo mensaje de
status terminal (`task_state=COMPLETED`, `color=GREEN`, `shape=CIRCLE`) que
dispara `_on_vision_complete` en `classification_rules.py`, **este hook
genérico ya había sobreescrito `conveyor2` con el color de la cámara ANTES**
de que `_on_vision_complete` leyera `expected_color =
peek_first_piece_color("conveyor2")` para comparar. Resultado: `expected_
color` SIEMPRE era igual a `color` en el momento de leerlo, sin importar lo
que hubiera pasado físicamente — `color_mismatch` era estructuralmente
imposible de disparar, no por ningún bug de scoping ni de front/back de
cola, sino porque la propia arquitectura dejaba que la cámara se
autoconfirmara antes de que nadie pudiera compararla contra nada.

Esto explica retroactivamente por qué cada "arreglo" de esta sesión sobre
`color_mismatch` no podía haber funcionado nunca en la práctica, por
correcta que fuera su lógica interna — la comparación ya llegaba con los
dos valores idénticos por construcción.

**Arreglado en dos sitios:**
- `factory_supervisor.py::_apply_vision_result`: ahora SOLO escribe sobre
  `initial_stack` (única asignación legítima de identidad, la primera vez
  que GlobalVision determina el color real de una pieza física). Quitadas
  por completo las ramas de `conveyor2` y `c4_location`.
- `classification_rules.py::_on_vision_complete`: quitada la llamada
  `fs.pieces.assign_color_shape("conveyor2", color, shape)` que hacía
  exactamente lo mismo desde el lado de robot2. Verificado que no rompe
  nada: TODAS las llamadas de encaminado/logging que siguen
  (`_send_robot2_to_c4/_to_bantam/_to_ibs/_to_scrap`,
  `insert_vision_detection`) ya usaban `color`/`shape` como variables
  locales leídas directamente del resultado de visión, nunca releídas desde
  `PieceTracker` — así que el comportamiento de encaminado no cambia en
  absoluto, solo deja de corromperse el valor expuesto como EXPECTED.

Con esto, `expected_color` en `_on_vision_complete` refleja de verdad lo que
el pipeline decidió originalmente en `initial_stack` y que viaja sin tocar
por todas las transferencias intermedias (`transfer_piece`/
`transfer_via_gripper` nunca tocan color/shape) — la comparación
Expected-vs-Reality que se lleva "arreglando" toda la sesión por fin compara
dos valores genuinamente independientes. Pendiente de prueba física para
confirmarlo. `unloading_rules.py` (robot1/C3-C4) NO se ha tocado — su
propia escritura explícita en la línea 185 sigue ahí a propósito, ya que no
existe ningún mecanismo de comparación en ese lado todavía (decisión
explícita del usuario de aplazarlo, ver sección de abajo); si en el futuro
se implementa detección de intrusos para robot1, esa escritura tendrá que
eliminarse con el mismo criterio.

## Bug real — el propio `register_intruder` anulaba la alarma de mismatch que arreglamos antes (2026-07-08)

Tras el fix del `UnboundLocalError`, el usuario reportó que EXPECTED seguía
mostrando la pieza intrusa como si fuera una pieza legítima planeada.
Causa: `PieceTracker.snapshot()` (`piece_tracker.py:251`) construye
`pipeline.queues` iterando `self._queues` **sin filtrar nada** — y eso es
literalmente lo único que tanto `dashboard_node.py` como el `ml_node.py`
externo usan para saber "qué se espera en esta ubicación" (ver sección de
`ml_node.py` más abajo). `register_intruder` mete la pieza sintética en esa
misma cola (necesario para que seguir funcionando `peek_first_piece*`/
`transfer_piece`/`count()`), así que en cuanto se registra, EXPECTED pasaba
a mostrarla como si el pipeline la hubiera planeado.

Peor aún: esto **anulaba en silencio** la propia alarma de mismatch que se
arregló hace unas horas en esta misma sesión (el bug de `ml_node.py` que
nunca disparaba para un intruso). En cuanto la visión de robot2 le asigna
su propio color detectado (`assign_color_shape`), EXPECTED y Reality pasan
a coincidir trivialmente **consigo mismos** — la intrusa "coincide" porque
se compara contra su propio color, no contra nada planeado. La alarma deja
de disparar otra vez, por una razón completamente distinta a la original.

**Arreglado** filtrando en `snapshot()`: cualquier pieza cuyo `id` empiece
por `"intruder-"` se excluye de lo que se expone en `queues` (lo que se
publica en `/factory/system_state` → `pipeline.queues`), pero sigue
existiendo sin cambios en `self._queues` para todo lo demás (`count()`,
`peek_first_piece*`, `transfer_piece`/`transfer_via_gripper`,
`all_pieces_finished()` — el sistema debe seguir sabiendo que hay trabajo
pendiente hasta que la intrusa salga por completo). Efecto correcto tras el
fix: si SOLO hay una intrusa en `conveyor2` (caso simple), EXPECTED para esa
ubicación queda vacío/null mientras dure — exactamente la señal que debía
disparar la alarma desde el principio. Si hay una intrusa delante de una
pieza real rastreada (caso `color_mismatch`, ver `at_front=True` más abajo),
el filtro dejar pasar solo la pieza real: EXPECTED sigue mostrando
correctamente el color real esperado (p.ej. RED), no el de la intrusa.
`py_compile`/`pyflakes` limpios.

## Bug real — UnboundLocalError mataba el intruso simple en silencio (2026-07-08)

Probado en físico tras el fix de "at_front" (ver abajo): el usuario metió una
pieza que no debería estar en C2S2 (caso simple, `count("conveyor2")==0`,
NI SIQUIERA el caso de color_mismatch), robot2 fue a mirarla con visión y se
quedó bugueado en IDLE — nunca la scrapeó, nunca hizo nada más.

Confirmado con el log combinado real (`runtime_logs/full_system_20260708_182347.txt:152`,
`stdout`/`stderr` con `tee`, NO el log ROS por nodo que solo captura
`get_logger()`):

```
on_complete callback raised for 'CMD-niryo-robot2-...': cannot access
local variable 'piece_id' where it is not associated with a value
```

Causa: dentro del closure `on_complete` (definido dentro de
`_on_vision_complete(fs, piece_id, wait_info)`), el bloque
`if color_mismatch: piece_id = fs.pieces.register_intruder(...)` **asigna**
a `piece_id`. En Python, asignar a un nombre en cualquier punto de una
función lo convierte en variable **local a toda la función** — incluso las
lecturas de ANTES de esa asignación en el código (`is_registered_intruder =
... piece_id.startswith(...)`, la primera línea real del closure) pasan a
referirse a esa variable local todavía sin asignar, no al parámetro
capturado por el closure. Resultado: `UnboundLocalError` en la primerísima
línea, para CUALQUIER pieza — no solo el caso de color_mismatch (ese branch
ni siquiera se ejecuta para un intruso simple) — el simple hecho de que esa
asignación EXISTIERA en algún punto del código ya rompía la función entera,
siempre, incondicionalmente.

El crash ocurre dentro de `VendorClient._complete()`
(`vendor_client.py:265-277`), que envuelve la llamada al callback en un
`try/except` y solo loggea con `logging.getLogger(__name__)` (Python
estándar, no `rclpy.get_logger()`) — por eso no aparecía en el log
`[factory_supervisor]` de cada nodo, solo en el `.txt` combinado de
`bringup.sh`. Como `_complete()` ya había sacado el comando de
`_pending_by_command`/`_pending_by_resource` ANTES de invocar el callback,
`is_busy("robot2")` quedaba en `False` (el comando "se completó" a efectos
del VendorClient) pero `fs._classification_state` nunca se tocó (la
excepción saltó antes de llegar a cualquier línea que lo cambiara) —
quedaba congelado en `WAITING_VISION` para siempre, y `evaluate()` bloquea
ahí mismo en su primera línea (`if fs._classification_state in
_ROBOT2_BUSY_STATES: return`) sin importar que robot2 esté físicamente
IDLE. Ningún `MOVE_PIECE` se llegó a enviar, ningún `cycle_event` se
escribió — coincide exactamente con lo observado en la DB de esa corrida
(`20260708_182357_BR`: un único `command_log` para robot2, `CAPTURE_LOCAL_
VISION`, nada más).

**Arreglado** renombrando el parámetro del closure a `dispatched_piece_id`
y creando `piece_id = dispatched_piece_id` como la primera línea de
`on_complete` — así `piece_id` sigue siendo una variable local (para poder
reasignarla en el caso `color_mismatch`), pero ya está inicializada antes
de cualquier lectura, sin depender del scoping del closure exterior.
Verificado con `py_compile`/`pyflakes` limpio. Lección para el futuro:
nunca reasignar dentro de un closure un nombre que coincide con un
parámetro de la función que lo define — aunque sea solo en una rama
condicional, rompe todas las lecturas anteriores de ese nombre en toda la
función.

## Corrección — el fix de color_mismatch consumía la pieza real en vez de dejarla intacta (2026-07-08)

El fix de "segunda vuelta" (ver más abajo: "pero la cámara ve otra cosa")
tenía un error real, señalado por el usuario ("PUES CLARO QUE TIENE QUE SER
ROJO... NO SIGNIFICA QUE LE HAYA DADO EL CAMBIAZO"). Ese fix, ante un
mismatch (se esperaba RED, la cámara ve GREEN), hacía
`assign_color_shape("conveyor2", "GREEN", ...)` sobre el `piece_id`
**rastreado** (el RED real) y luego lo scrapeaba con ese mismo id — es decir,
trataba el mismatch como un cambiazo: la pieza roja real quedaba
completamente consumida/perdida, sin ningún rastro en `PieceTracker`, como
si nunca hubiera existido.

Eso es incorrecto: un intruso que se cuela por delante en C2S2 **no**
implica que la pieza esperada haya desaparecido — sigue rastreada, todavía
detrás en la cola (igual que el intruso original de `count()==0`, solo que
aquí SÍ hay algo real en cola). Arreglado añadiendo
`PieceTracker.register_intruder(location, at_front=False)`: con
`at_front=True` (`appendleft` en vez de `append`), la intrusa se registra
**delante** de la pieza rastreada sin tocarla. En
`classification_rules.py::_on_vision_complete`, ante `color_mismatch` ahora
se registra esa intrusa-al-frente, se reasigna la variable local `piece_id`
a su id sintético (y `fs.cycles.update_entity_cycle(..., piece_id=piece_id,
...)` para que el `cycle_event` de esta dispatch quede etiquetado con el id
correcto), y todo el flujo de scrap aguas abajo
(`transfer_via_gripper`/`transfer_piece`, que siempre hace `popleft()`)
consume solo la intrusa — la pieza rastreada real queda en índice 0 justo
después, así que el siguiente ciclo de clasificación (cuando el sensor
vuelva a OCCUPIED con la intrusa ya retirada) la vuelve a inspeccionar
normalmente, con su propio color/forma reales, sin haber sido tocada en
ningún momento.

## Robot1/C3-C4: paridad de intrusos investigada y aplazada a propósito (2026-07-08)

Tras arreglar el intruso de C2S2 (robot2, ver más abajo), se preguntó al
Claude de `shipyard_core` (vía `prompt_intruder_robot1_dudas.md`, respuesta
completa con código real de `robot1_rules.py`/`track_rules.py`) si el
patrón de robot2 debía replicarse también en robot1 (C3/C4). Hallazgos
clave de esa respuesta, por si se retoma más adelante:

- En `shipyard_core`, Robot1 usa DOS chequeos independientes sin veredicto
  compartido (a diferencia de Robot2, que cachea uno solo en
  `pending_robot_action`) — `TrackRules` decide intruder al mover la pieza,
  `Robot1Rules` decide PLACE/SCRAP por separado al leer la visión; pueden
  discrepar (p.ej. color coincide pero `shape_ok=False` fuerza SCRAP en el
  segundo chequeo aunque el primero no marcara intruder). Ni comentarios ni
  historial de commits explican si es intencional o deuda técnica — el repo
  llegó en un único commit.
- `shape_ok` en `shipyard_core` NUNCA compara contra una forma esperada
  (no existe tal comparación en ningún sitio) — solo exige que el ML haya
  devuelto un valor válido (`not in ("NONE","UNKNOWN","")`) en el momento de
  la captura. Un fallo de forma por sí solo ya fuerza SCRAP, igual de crítico
  que el de color, en ambos robots.
- El patrón "la pieza esperada se queda intacta en cola, llega en el
  siguiente ciclo" tiene sentido físico real en `shipyard_core` para
  `conveyor2` (cinta multi-pieza genuina, gateada por `len(cola)>0/==0`),
  pero NO para `c3_location`/`c4_location` (estaciones de un solo slot
  gateadas por sensor, con una única llamada que las llena y otra que las
  vacía en todo el repo) — ahí, "no popear la esperada" deja una entrada
  fantasma en la cola lógica mientras el sensor físico ya está FREE, no un
  tránsito real. Confirma que el enfoque ya usado en C2S2 aquí (el
  `piece_id` rastreado completa su propio ciclo como SCRAP con color/forma
  reales, sin crear entidad sintética que conviva con la esperada) es el
  equivalente correcto para estaciones de un solo slot — no haría falta el
  patrón "coexistencia en cola" salvo que apareciera aquí una cinta
  multi-pieza real equivalente a `conveyor2` de `shipyard_core`.
- `shipyard_core` no tiene ningún "hueco pendiente" tipo
  `_map_resolve_dispatch`: si el color pedido no se encuentra en el stack
  inicial, simplemente se descarta (no hay ningún `.insert(0, ...)` que lo
  reinserte) — el sistema asume que se recupera solo o se pierde, sin
  contabilidad. El mecanismo de "hueco que sigue debiéndose" de
  `shipyard_pnp` (`_map_resolve_dispatch`) no tiene equivalente allí.

**Decisión explícita del usuario: no implementar nada de esto en Robot1/
C3-C4 por ahora** — "por ahora no necesito que robot1 sea capaz de
scrapear, con que lo haga correctamente robot2 estoy contento". El manejo
de intrusos sigue existiendo solo en robot2/C2S2 (`classification_rules.py`,
ver sección de abajo); Robot1/C3-C4 no tiene ningún chequeo de
intruso/mismatch todavía. Si se retoma, el punto de partida es el patrón ya
usado en robot2 (`is_registered_intruder or color_mismatch` → forzar
`SCRAP`), adaptado a `unloading_rules.py`/`processing_rules.py`.

## Intruso físico en C2S2: dos bugs reales, confirmados con timestamps de la DB (2026-07-08)

El usuario dejó a mano una pieza intrusa (GREEN SQUARE, nunca alimentada por
el pipeline) en C2S2 mientras había una pieza azul terminada esperando en
bantam. robot2 se quedó parado en IDLE sin ir a por ninguna de las dos hasta
quitar el intruso.

**Bug 1 — deadlock real en `classification_rules.py::evaluate()`.**
`bantam_ready` exigía `fs.state.get_sensor("c2s2") != OCCUPIED` (el sensor
físico crudo) en vez de "hay una pieza rastreada esperando clasificar"
(`fs.pieces.count("conveyor2")`). Con el intruso puesto: `classify_ready`
era falso (count==0, nada que clasificar) Y `bantam_ready` también era falso
(sensor OCCUPIED) — **al mismo tiempo**, dejando a robot2 sin ninguna opción
válida pese a tener trabajo real esperando. Confirmado con
`resource_state_change`: bantam terminó `piece-006` a las 17:21:36.36,
`c2s2` estuvo `OCCUPIED` de 17:21:12 a 17:22:10.08, y robot2 arrancó
`BANTAM_TO_C4` a las 17:22:10.13 — 42ms después de que el sensor volviera a
`FREE`. Arreglado cambiando `bantam_ready` a
`fs.pieces.count("conveyor2") == 0` — un intruso sin pieza rastreada ya no
bloquea la recogida de bantam; una pieza real sin rastrear todavía bloquea
correctamente vía el propio `count>0` de `classify_ready` (mutuamente
excluyentes).

**Seguimiento el mismo día — un intruso ya no debía quedarse bloqueado para
siempre.** El fix del Bug 1 evita el deadlock, pero por diseño
`classify_ready` seguía exigiendo `count("conveyor2") > 0`, así que robot2
tampoco iba NUNCA a inspeccionar/retirar al intruso — se quedaba ocupando
C2S2 indefinidamente hasta que un humano lo quitara a mano (confirmado
directamente por el usuario probándolo). Decisión: si el sensor físico dice
que hay algo, robot2 tiene que ir a mirarlo con su propia visión y
encaminarlo según lo que detecte, tenga o no tenga PieceTracker una pieza
ahí. Quitado `count("conveyor2") > 0` de `classify_ready` (se queda solo con
el sensor + c4 libre). Para que esto no deje un fantasma a mitad de camino
(el C4 marcado ocupado sin que nadie lo track — robot1 lo habría ignorado en
`_next_pick_context` por no encontrar `peek_first_piece`), se añadió
`PieceTracker.register_intruder(location)`: si al ir a despachar
`count("conveyor2") == 0`, inyecta una pieza sintética (`intruder-<hex>`) en
la cola antes del despacho — se convierte en la cabeza automáticamente
(la cola estaba vacía), así que TODO el código existente
(`peek_first_piece*`, `assign_color_shape`, `transfer_via_gripper`, el
unload de robot1) sigue funcionando sin ningún caso especial más: la pieza
se inspecciona, se encamina a un destino final real según su color/forma
detectados, y sale completamente del sistema como cualquier otra —
en vez de quedarse como un fantasma que el sensor recuerda pero nadie
resuelve. Sigue contando como "intruder" en el bookkeeping del mapa
(`_map_resolve_dispatch` ya lo trataba así desde el primer fix de esta
sesión) — no consume el hueco esperado de ninguna pieza real.

**Corrección el mismo día — un intruso se encaminaba como si fuera
legítimo, en vez de descartarse.** El párrafo anterior decía "se encamina a
un destino final real según su color/forma detectados" -- **mal**. El
usuario lo probó en vivo: dos intrusos GREEN en C2S2 acabaron en C4 (porque
`_decide_route("GREEN") == "C4"`, igual que a una pieza GREEN real), en vez
de ir a scrap. Eso anula el propio sentido de marcarla como intruder. Pedido
explícito de replicar aquí el criterio de `shipyard_core`
(`shipyard_core/supervisor/rules/robot2_rules.py`/`track_rules.py`): un
mismatch expected/reality nunca se procesa como legítimo, siempre va a
scrap, sea cual sea el color detectado. Arreglado en
`_on_vision_complete` (`classification_rules.py`): si `piece_id` empieza por
`"intruder-"` (lo único que hace falta para saberlo, ya que
`register_intruder` siempre genera ese prefijo), la ruta se fuerza a
`"SCRAP"` sin consultar `_decide_route()` en absoluto.

**Segunda vuelta, mismo día — faltaba el caso "SÍ hay pieza rastreada pero
la cámara ve otra cosa" (pieza físicamente cambiada, no solo intruso sin
rastrear).** El fix anterior solo cubría `count("conveyor2")==0` (nada
rastreado en absoluto). Pregunta del usuario que lo destapó: "espero una
pieza ROJA rastreada, pero a mano dejo una VERDE en C2S2 -- ¿qué hace el
robot?" Respuesta con el fix anterior: nada la detectaba, `assign_color_
shape` pisaba el color rastreado a GREEN sin más, y `_decide_route("GREEN")`
la mandaba a C4 como si fuera legítima -- mismo bug, otra puerta de entrada.
Arreglado capturando `expected_color = fs.pieces.peek_first_piece_color(
"conveyor2")` ANTES de que `assign_color_shape` lo sobrescriba; si hay una
pieza rastreada (`expected_color` real, no `None`/`UNKNOWN`) y la cámara
detecta un color distinto (`color_mismatch`), se fuerza a `SCRAP` igual que
al intruso sin rastrear -- `is_intruder = is_registered_intruder or
color_mismatch`. En `shipyard_pnp_ws` no existe (ni hace falta) el concepto
de "la pieza esperada se queda intacta en cola para el siguiente ciclo" de
`shipyard_core` -- aquí el `piece_id` rastreado ES el objeto físico según el
FIFO, así que si la cámara demuestra que no es lo que creíamos, ese mismo
`piece_id` simplemente completa su ciclo como SCRAP (con el color/forma
REAL detectados grabados en la DB), sin crear una entidad sintética nueva.

**Bug 2 — la verificación de `ml_node.py` nunca se disparaba para un
intruso.** El bloque de comparación (`check_piece_match` + detección de
mismatch + alarma) vivía entero dentro de `if state["timer"] is not None:`
— es decir, solo se ejecutaba la primera vez tras un cambio de EXPECTED,
nunca más hasta el siguiente cambio. Un intruso no rastreado nunca cambia
EXPECTED (se queda en `[]` todo el rato), así que la comparación no se
disparaba jamás — de ahí que Reality mostrara `GREEN_SQUARE` con
Expected=`null` sin ninguna alarma. Arreglado: el grace period tras un
cambio de EXPECTED solo salta la comparación mientras dura esa ventana; ya
no evita que la comparación se ejecute cuando no ha habido ningún cambio
reciente — ahora corre cada frame.

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
