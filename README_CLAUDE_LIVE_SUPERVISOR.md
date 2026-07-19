# Claude como supervisor de despacho en vivo: idea y plan de implementacion

## Resumen

La idea no seria que Claude controle directamente los robots. Claude no deberia mandar joints, trayectorias, velocidades ni movimientos de bajo nivel. Eso ya lo hacen los controladores actuales y debe seguir siendo asi.

La idea viable es usar Claude como **supervisor de despacho de alto nivel**: el sistema fisico genera una lista cerrada de acciones seguras y Claude solo puede elegir una de esas opciones. Despues, una capa determinista vuelve a validar la decision antes de ejecutar nada. Si Claude tarda, falla, responde mal o elige una accion invalida, el sistema ignora esa decision y usa el fallback reactivo actual.

Arquitectura objetivo:

```text
Sensores / estado real
        |
        v
Factory Supervisor genera acciones fisicamente validas
        |
        v
Claude elige SOLO entre esas opciones permitidas
        |
        v
Safety layer verifica precondiciones
        |
        v
Robot ejecuta con controladores actuales
        |
        v
Si Claude tarda, falla o elige algo invalido: fallback reactivo
```

## Estamos lejos?

Para control directo de robots en vivo, si: estamos lejos y no seria una buena direccion. Un LLM no debe estar en el bucle de servo ni decidir posiciones articulares.

Para supervision de alto nivel, no estamos tan lejos. El sistema ya tiene piezas importantes:

- `factory_supervisor.py` concentra el estado y coordina decisiones.
- Los planners ya tienen puntos discretos de decision: `classification_rules.py`, `processing_rules.py`, `unloading_rules.py`.
- El mapa actual ya implementa espera protegida con `MAP_GRACE_SEC`.
- `_map_next()`, `_map_should_wait()` y `_map_note_dispatch()` ya separan intencion del mapa, espera y fallback.
- Los vendor adapters ya encapsulan los movimientos reales: el planner manda tareas, no joints.
- La DB ya permite auditar corridas, ciclos, eventos y decisiones aplicadas.

Por tanto, el trabajo no seria "darle el robot a Claude". El trabajo seria construir una interfaz segura para que Claude pueda actuar como una politica de despacho enchufable.

## Principio de seguridad

Claude nunca puede inventar acciones. Solo puede devolver un identificador de accion que ya fue generado por el Factory Supervisor.

Ejemplo de respuesta aceptable:

```json
{
  "decision_id": "20260716-robot2-00042",
  "selected_action": "WAIT_FOR_BANTAM",
  "max_wait_s": 8.0,
  "confidence": 0.72,
  "reason": "Bantam is predicted to finish soon and C4 is free."
}
```

Ejemplo de respuesta prohibida:

```json
{
  "move_joint": [-0.2, 1.1, 2.0, 0.1, 0.6, -0.4]
}
```

La capa de seguridad debe rechazar cualquier respuesta que:

- No sea JSON valido.
- No incluya el `decision_id` correcto.
- Elija una accion que no esta en `valid_actions`.
- Proponga un `max_wait_s` superior al limite configurado.
- Llegue fuera del deadline.
- Contradiga sensores actuales.
- Intente incluir comandos de bajo nivel.
- Llegue cuando el robot ya no esta en el mismo estado.

## Que decisiones podria tomar Claude

La primera version debe limitarse a decisiones discretas donde ya existe una alternativa segura:

| Entidad | Conflicto | Acciones posibles |
|---|---|---|
| `robot2` | C2S2 vs Bantam vs IBS | clasificar C2S2, descargar Bantam a C4, mover IBS a Bantam, esperar |
| `xarm1` | laser terminado vs pieza en C1S2 | retirar laser, mover C1S2 a laser, mover C1S2 a C2S1, esperar |
| `robot1` | C3 terminado vs C4 terminado/proximo | descargar C3, descargar C4, esperar |
| `xarm2` | siguiente pieza del stack | elegir siguiente pieza permitida o esperar nueva vision |

La primera prueba deberia hacerse solo con `robot2`, porque es donde ya se ha demostrado el valor del `WAIT` con los mapas dinamicos.

## Formato de entrada a Claude

Claude no necesita ver todo el sistema. Debe recibir un snapshot pequeno, determinista y sin informacion innecesaria:

```json
{
  "decision_id": "20260716-robot2-00042",
  "entity": "robot2",
  "decision_point": "C2S2_BANTAM_IBS",
  "deadline_ms": 800,
  "current_time_s": 384.2,
  "state": {
    "robot2": "IDLE",
    "c2s2": {"occupied": true, "piece_id": "piece-007", "color": "RED"},
    "c4": {"occupied": false},
    "bantam": {"state": "WORKING", "eta_s": 5.5, "piece_id": "piece-004"},
    "ibs": {"occupied": false},
    "intruder": false
  },
  "valid_actions": [
    {
      "id": "CLASSIFY_C2S2_TO_IBS",
      "preconditions": ["robot2_idle", "c2s2_occupied", "ibs_free"]
    },
    {
      "id": "WAIT_FOR_BANTAM",
      "max_wait_s": 8.0,
      "preconditions": ["robot2_idle", "c4_free", "bantam_working_or_finished"]
    }
  ],
  "fallback_action": "CLASSIFY_C2S2_TO_IBS",
  "objective": "minimize_makespan_without_blocking_upstream"
}
```

Puntos importantes:

- La lista `valid_actions` la genera el sistema, no Claude.
- El `fallback_action` siempre existe.
- El deadline es corto y obligatorio.
- El estado debe estar congelado con un `decision_id`; si el estado cambia, la respuesta queda obsoleta.

## Arquitectura propuesta en el repo

Una implementacion limpia podria tener estos modulos:

```text
src/shipyard_pnp/shipyard_pnp/factory/
  ai_dispatch/
    __init__.py
    action_models.py          # dataclasses / schemas de DecisionRequest y DecisionResponse
    valid_actions.py          # genera acciones permitidas desde FactorySupervisor
    safety_filter.py          # revalida precondiciones antes de ejecutar
    claude_client.py          # cliente API, timeout, retries controlados
    shadow_logger.py          # registra que habria elegido Claude
    policy.py                 # off / shadow / guarded / disabled
```

Y los planners actuales no deberian llamar a Claude directamente. Deberian llamar a una politica comun:

```python
decision = fs.dispatch_policy.choose(
    entity="robot2",
    decision_point="C2S2_BANTAM_IBS",
    valid_actions=valid_actions,
    fallback_action=fixed_action,
    state_snapshot=snapshot,
)
```

La politica decide segun modo:

- `disabled`: usa siempre fallback actual.
- `shadow`: pregunta a Claude, registra la respuesta, pero ejecuta fallback.
- `guarded`: pregunta a Claude y ejecuta solo si safety_filter aprueba.
- `offline`: usa Claude/simulacion para generar mapas antes de ejecutar.

## Configuracion propuesta

La activacion deberia ser explicita por variables de entorno o parametros ROS:

```text
AI_DISPATCH_MODE=disabled|shadow|guarded|offline
AI_DISPATCH_ENTITIES=robot2,xarm1,robot1
AI_DISPATCH_TIMEOUT_MS=800
AI_DISPATCH_MAX_WAIT_S=8.0
AI_DISPATCH_MAX_CONSECUTIVE_TIMEOUTS=3
CLAUDE_API_KEY=...
CLAUDE_MODEL=...
```

Valores seguros por defecto:

- `AI_DISPATCH_MODE=disabled`
- `AI_DISPATCH_ENTITIES=robot2`
- `AI_DISPATCH_TIMEOUT_MS=800`
- `AI_DISPATCH_MAX_CONSECUTIVE_TIMEOUTS=3`

Si se producen tres timeouts seguidos, el sistema deberia cambiar automaticamente a `disabled` durante el resto de la corrida y registrar el evento.

## Primer MVP concreto

El MVP mas razonable seria:

1. Implementar `valid_actions.py` solo para `robot2`.
2. Implementar `safety_filter.py` solo para las acciones de `robot2`.
3. Implementar `policy.py` con modo `disabled` y `shadow`.
4. Registrar cada decision en `operator_event`.
5. Correr varias corridas reales en `shadow`: Claude decide, pero no ejecuta.
6. Comparar decisiones Claude vs fixed vs mapa dinamico.
7. Solo si los datos son buenos, activar `guarded` en una corrida corta.

Este MVP no necesita tocar trayectorias, vendor adapters ni controladores. Solo toca el nivel de despacho.

## Plan de implementacion

### Fase 0 - Documento y criterios de seguridad

Objetivo: dejar claro que Claude solo puede elegir entre acciones permitidas.

Entregables:

- Este README.
- Lista de decisiones candidatas por robot.
- Definicion de limites: deadline, max wait, modo shadow obligatorio, fallback.

Resultado esperado: acuerdo de arquitectura antes de tocar hardware.

### Fase 1 - `valid_actions` determinista

Objetivo: extraer de los planners actuales una funcion que enumere acciones fisicamente posibles.

Ejemplo:

```python
get_valid_actions(fs, "robot2") -> [
    Action("CLASSIFY_C2S2_TO_IBS"),
    Action("WAIT_FOR_BANTAM"),
]
```

Esto es la pieza mas importante. Si esta funcion esta bien hecha, Claude queda encerrado en una lista segura.

Riesgo: medio. Hay que tener cuidado de no duplicar mal la logica existente de `classification_rules.py`, `processing_rules.py` y `unloading_rules.py`.

### Fase 2 - Safety filter

Objetivo: revalidar justo antes de ejecutar.

Aunque `valid_actions` dijera hace 500 ms que `C4` estaba libre, puede dejar de estarlo. El safety filter debe volver a comprobar:

- Robot idle.
- Sensor esperado.
- Maquina terminada o en estado compatible.
- Destino libre.
- No intruder.
- Vendor no busy.
- Decision no caducada.

Si falla cualquier precondicion: fallback.

Riesgo: bajo-medio. Es codigo determinista y testeable.

### Fase 3 - Cliente Claude en modo `shadow`

Objetivo: Claude decide, pero no controla.

En este modo:

1. El sistema genera `DecisionRequest`.
2. Se manda a Claude con timeout.
3. Se parsea la respuesta.
4. Se registra que habria elegido.
5. El sistema ejecuta exactamente lo que ejecutaria hoy.

Esto permite medir:

- Latencia real de API.
- Porcentaje de respuestas validas.
- Cuantas veces coincide con fixed.
- Cuantas veces coincide con el mapa dinamico.
- Cuantas veces propone algo que el safety filter rechazaria.

Riesgo: bajo, porque no toca comportamiento fisico.

### Fase 4 - Replay y simulacion

Objetivo: probar Claude contra estados historicos y simulados antes de dejarlo decidir en vivo.

Fuentes de datos:

- `cycle_event`
- `piece_transfer`
- `status_log`
- mapas dinamicos ya validados
- simulador `shipyard_sim`

Metricas:

- Validez JSON.
- Latencia p50/p95/p99.
- Acciones rechazadas por safety.
- Makespan simulado si se siguiera su decision.
- Diferencia frente a fixed y frente a mapa dinamico.

Riesgo: bajo. Todo offline.

### Fase 5 - `guarded` en robot2 solo

Objetivo: primera prueba real limitada.

Condiciones:

- Solo `robot2`.
- Solo conflicto C2S2/Bantam/IBS.
- Solo cuando no hay intruder.
- Timeout corto.
- Max wait acotado.
- Fallback inmediato a politica actual.
- Logging completo en DB.

La primera accion candidata seria permitir que Claude elija entre:

- `CLASSIFY_C2S2_TO_*`
- `BANTAM_TO_C4`
- `WAIT_FOR_BANTAM`
- fallback fixed

Riesgo: medio. Es la primera fase donde una decision de Claude puede cambiar la corrida, pero sigue dentro de acciones validadas.

### Fase 6 - Expandir a xArm1 y robot1

Una vez robot2 funcione:

- xArm1: decidir entre retirar laser terminado o procesar C1S2.
- robot1: decidir entre descargar C3, descargar C4 o esperar C4 si esta a punto.

Riesgo: medio. Estas decisiones pueden afectar mas al flujo global y necesitan buena definicion de estados `working`, `finished`, `eta` y buffers.

### Fase 7 - Modo hibrido con mapa dinamico

La opcion mas potente no es sustituir el mapa dinamico. Es combinar ambos:

- El mapa dinamico sigue siendo la referencia principal.
- Claude solo interviene cuando la realidad se desvia del mapa.
- Claude puede elegir el mejor fallback entre acciones seguras.

Eso evita depender de Claude en cada decision y lo usa donde mas valor tiene: cuando el sistema se sale del plan previsto.

## Logging obligatorio

Cada decision debe quedar auditada. Como minimo:

```json
{
  "run_id": "...",
  "decision_id": "...",
  "entity": "robot2",
  "mode": "shadow|guarded",
  "state_hash": "...",
  "valid_actions": ["CLASSIFY_C2S2_TO_IBS", "WAIT_FOR_BANTAM"],
  "fallback_action": "CLASSIFY_C2S2_TO_IBS",
  "claude_action": "WAIT_FOR_BANTAM",
  "accepted": true,
  "rejection_reason": null,
  "latency_ms": 642,
  "executed_action": "WAIT_FOR_BANTAM"
}
```

Inicialmente podria guardarse como `operator_event`. Si el experimento crece, conviene crear una tabla dedicada:

```text
shipyard_pnp_ws.ai_dispatch_decision
```

## Riesgos principales

### Latencia

Una API externa puede tardar demasiado o variar mucho. Solucion:

- deadline estricto;
- fallback local;
- modo shadow antes de guarded;
- no usar Claude para ciclos de control rapido;
- opcionalmente preguntar de forma anticipada cuando se detecta que se aproxima un conflicto.

### No determinismo

Claude puede responder distinto ante estados parecidos. Solucion:

- temperatura baja;
- JSON schema estricto;
- lista cerrada de acciones;
- logging;
- comparacion offline;
- safety filter obligatorio.

### Accion valida pero suboptima

Claude puede elegir una accion segura pero peor. Solucion:

- primero shadow mode;
- comparar contra mapa dinamico;
- usar simulacion para replay;
- empezar solo con robot2;
- activar `guarded` solo en estados donde el historico muestre que Claude aporta valor.

### Dependencia de internet/API

Si la API cae, el sistema no puede detenerse. Solucion:

- fallback siempre local;
- si hay tres timeouts seguidos, desactivar modo Claude durante la corrida;
- registrar evento y seguir con politica reactiva.

## Criterios para pasar de fase

No deberia probarse en hardware con control real hasta cumplir:

- Mas de 95% de respuestas JSON validas en shadow.
- p95 de latencia por debajo del deadline configurado o estrategia anticipada funcionando.
- 0 acciones aceptadas que violen precondiciones en replay.
- Safety filter con tests unitarios.
- Al menos varias corridas simuladas donde no empeore frente al fallback.
- Boton/configuracion para desactivar Claude inmediatamente.
- Logging suficiente para reconstruir cada decision.

## Veredicto

No estamos lejos de un prototipo serio de **Claude como supervisor de despacho en shadow mode**. Eso podria implementarse de forma incremental porque el sistema ya tiene mapa, fallback, sensores, planners discretos y auditoria.

Si estamos lejos de un sistema donde Claude "controle el robot" en el sentido fuerte. Esa no deberia ser la meta. La meta defendible es:

> Claude propone decisiones de despacho de alto nivel; el Factory Supervisor decide que acciones existen; la safety layer decide si se permite ejecutar; los controladores actuales siguen moviendo los robots.

Ese enfoque es viable, defendible academicamente y compatible con el sistema actual.
