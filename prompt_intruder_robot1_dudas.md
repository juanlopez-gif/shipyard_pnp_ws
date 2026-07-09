# Prompt para el Claude que trabaja en shipyard_core

## Contexto

Estoy portando a `shipyard_pnp` (repo distinto, arquitectura distinta:
`classification_rules.py`/`unloading_rules.py` con funciones `evaluate()`,
un `PieceTracker` con colas FIFO por ubicación, sin clases `Robot1Rules`/
`Robot2Rules`/`TrackRules`) el mecanismo de expected-vs-reality que ya
tenéis funcionando en `shipyard_core` para detectar piezas intrusas
(`pending_robot_action`, `vision_expected`, `create_intruder_piece_in_location`,
scrap forzado en mismatch).

Ya implementé y verifiqué en vivo la parte de **Robot2/C2S2**:

- Si `PieceTracker` no tiene NINGUNA pieza rastreada en `conveyor2` pero el
  sensor de C2S2 está ocupado, se registra una pieza sintética
  (`intruder-<hex>`) justo antes de despachar la visión, se inspecciona con
  la cámara real de robot2, y se fuerza `route="SCRAP"` sin pasar por la
  función normal de encaminado (antes se enviaba a C4/BANTAM como si fuera
  legítima, según el color detectado — bug real, confirmado por el usuario
  metiendo intrusos GREEN que acababan en C4).
- Si SÍ hay una pieza rastreada (p.ej. se esperaba RED) pero la cámara real
  de robot2 detecta un color distinto (p.ej. GREEN) al capturarla, también
  se fuerza `SCRAP` — capturo el color esperado (`peek_first_piece_color`)
  ANTES de que la asignación de visión lo sobrescriba, comparo, y si no
  coincide trato el resultado como intruso.

No quiero reinventar el resto a ciegas. Preguntas concretas, con código real
por favor (no descripciones a alto nivel):

## Preguntas concretas

1. **Robot1 (C3/C4) — ¿por qué dos chequeos independientes en vez de uno
   cacheado como Robot2?** Según lo que me pasasteis antes, `TrackRules`
   (al mover físicamente la pieza) y `Robot1Rules` (al decidir PLACE vs
   SCRAP) recalculan el veredicto por separado, y puede haber casos donde
   no coincidan (TrackRules dice "no intruder" por color pero Robot1Rules
   manda SCRAP igual por `shape_ok=False`). ¿Es una asimetría intencional
   (Robot1 necesita el chequeo de forma que Robot2 no tiene en el mismo
   punto) o es deuda técnica que os gustaría que Robot1 también usara un
   único veredicto cacheado como Robot2? Enséñame el código real de
   `robot1_rules.py:158-183` y `track_rules.py:240-275` completos si hay
   más contexto relevante alrededor de esas líneas.

2. **¿Por qué comprobáis también `shape_ok` (forma), no solo color?**
   `color_ok`, `shape_ok`, `color_matches` — las tres fuerzan SCRAP si
   fallan. En mi caso, para Robot2/C2S2 solo comparo color (la forma casi
   nunca se conoce de antemano en `shipyard_pnp` salvo que
   `stack_status` — un topic externo — ya la haya resuelto en el momento
   del feed). ¿La comprobación de forma en vuestro caso es igual de crítica
   que la de color, o es más una salvaguarda secundaria? ¿Qué pasa en
   vuestro sistema si `expected_shape` es `UNKNOWN`/no se conoce todavía —
   se salta esa comprobación o cuenta como fallo automático?

3. **El mecanismo de "la pieza esperada se queda intacta en su cola,
   llegará en el siguiente ciclo" — ¿cómo es posible físicamente?**
   `create_intruder_piece_in_location` crea la pieza intrusa DIRECTAMENTE
   en el gripper, sin hacer pop de la cola de origen — dejando la pieza
   esperada "aún ahí". Pero si el sensor/estación (C2S2, C3, C4) solo
   puede tener UN objeto físico a la vez, ¿cómo puede la pieza intrusa Y la
   esperada coexistir "en la misma cola"? ¿Es que `expected_queues`
   (aunque esté muerto para lectura) SÍ modela una cola física de varias
   piezas en tránsito hacia esa estación, y la intrusa se detectó ANTES de
   que la esperada llegara físicamente (es decir, la intrusa se coló
   delante en la cinta real)? Necesito entender el modelo físico exacto
   para saber si en `shipyard_pnp` (donde una pieza rastreada en
   `conveyor2` YA significa "está físicamente ahí, confirmado por
   PLACE_DONE real") tiene sentido replicar esto, o si mi solución actual
   (el `piece_id` rastreado simplemente completa su propio ciclo como
   SCRAP con el color/forma real grabados, sin crear una entidad
   sintética) es el equivalente correcto para una arquitectura donde no
   existe esa cola física intermedia.

4. **¿Qué pasa con el "hueco" del mapa/orden esperado cuando una pieza
   legítima nunca llega porque fue sustituida por un intruso?** En
   `shipyard_pnp` tenemos un mecanismo de map-guidance
   (`_map_resolve_dispatch`) que, si el resultado no coincide con lo que el
   mapa esperaba, lo registra como "intruder" en una alarma pero NO avanza
   el puntero del mapa — el hueco sigue debiéndose y se compara de nuevo en
   el siguiente disparo de esa entidad. ¿Tenéis un equivalente — algo que
   recuerde "todavía debo una pieza RED en esta posición del plan" después
   de que un intruso GREEN ocupara su sitio y fuera escrapeado? ¿O el
   sistema simplemente asume que la pieza real perdida se recupera sola en
   algún punto posterior?

Pégame los fragmentos de código reales (con nombre de archivo y líneas) que
respondan a esto — no hace falta que expliques nada de `shipyard_pnp`, esa
adaptación la hago yo después con esta información.
