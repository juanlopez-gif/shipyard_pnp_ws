# Factory Analytics — Ideas de Análisis e Implementación

Este documento recoge ideas concretas de análisis y posibles extensiones del sistema,
basadas en los datos que ya se están recogiendo en `twin_mes_db.shipyard_pnp_ws`.

---

## 1. Datos disponibles (estado actual)

| Tabla | Qué contiene |
|---|---|
| `production_run` | Un registro por sesión de producción (run_id, orden original y optimizada, saving) |
| `piece` | Cada pieza con color, shape, posición inicial |
| `piece_transfer` | Todos los movimientos de pieza entre localizaciones |
| `piece_outcome` | Resultado final: ruta tomada, localización final, tiempo total |
| `cycle_event` | **Un ciclo por operación de robot/máquina**: entity, task_name, fases JSONB, duración, is_discarded |
| `vision_detection` | Cada detección de visión: sistema (globalvision/robot2_camera/robot1_camera), color, shape, slot_id |
| `robot_task` | Cada movimiento de robot con started_at/finished_at y resultado |
| `machine_job` | Cada job de laser o bantam con duración y resultado de puerta |
| `command_log` | Todos los comandos enviados por el FS a los VS |
| `ack_log` | Todos los acknowledgments recibidos |
| `status_log` | Todos los status terminales recibidos |
| `resource_state_change` | Cambios de estado de robots, máquinas y sensores con duración en estado previo |
| `queue_depth_sample` | Profundidad de colas (conveyor1/2, laser_bed, etc.) cada 5 s |
| `optimizer_run` | Resultados del optimizador: orden original vs. mejor, ahorro, método, permutaciones |

### Ejemplo de fases (robot1 / UNLOAD_C3)
```
CLASSIFY_AND_PICK  → 11.7 s
VACUUM_PICK        →  1.6 s
LIFT_AND_PLACE     → 16.2 s
VACUUM_RELEASE     →  1.4 s
RETURNING_HOME     → 10.6 s
────────────────────────────
TOTAL              → 41.5 s
```

### Tiempos medios por entidad (run de 6 piezas)
| Entity | Task | Avg (s) |
|---|---|---|
| xarm2 | FEED_TO_C1S1 | 13.6 |
| xarm2 | FEED_GREEN_TO_C3 | 15.4 |
| xarm1 | C1S2_TO_C2S1 | 15.8 |
| xarm1 | C1S2_TO_LASER | 15.3 |
| laser | PROCESS_RED | 22.7 |
| xarm1 | LASER_TO_C2S1 | 14.9 |
| robot2 | CLASSIFY_C2S2_TO_C4 | 33.6 |
| robot2 | CLASSIFY_C2S2_TO_BANTAM | 43.1 |
| robot2 | CLASSIFY_C2S2_TO_IBS | 31.1 |
| robot2 | IBS_TO_BANTAM | 37.1 |
| robot2 | BANTAM_TO_C4 | 36.6 |
| bantam | PROCESS_BLUE | 48.4 |
| robot1 | UNLOAD_C4 | 36.8 |
| robot1 | UNLOAD_C3 | 40.9 |

---

## 2. Análisis posibles con los datos actuales

### 2.1 Descomposición de tiempos por fase (ya disponible)
Los `phases` JSONB de `cycle_event` permiten ver exactamente dónde va el tiempo dentro de cada ciclo.

```sql
-- Tiempo medio por fase de robot1
SELECT
    phase_data ->> 'phase'              AS phase,
    round(AVG((phase_data ->> 'duration_s')::float)::numeric, 3) AS avg_s
FROM shipyard_pnp_ws.cycle_event,
     jsonb_array_elements(phases) AS phase_data
WHERE entity = 'robot1' AND is_discarded = FALSE
GROUP BY phase ORDER BY avg_s DESC;
```

**Utilidad**: identificar qué subfase es el cuello de botella real (¿el pick? ¿el place? ¿el home?).

---

### 2.2 Throughput por run (piezas/hora)
```sql
SELECT
    run_id,
    pieces_completed,
    round(EXTRACT(EPOCH FROM (finished_at - started_at))::numeric, 1) AS total_s,
    round((pieces_completed * 3600.0 /
           EXTRACT(EPOCH FROM (finished_at - started_at)))::numeric, 2) AS pieces_per_hour
FROM shipyard_pnp_ws.production_run
WHERE finished_at IS NOT NULL;
```

---

### 2.3 Ganancia real del optimizador (simulado vs. real)
El optimizador estima el ahorro con un modelo de simulación. Los datos reales de `piece_outcome.total_time_s` y `production_run` permiten comparar estimación vs. ejecución real.

```sql
SELECT
    o.original_time_s   AS sim_original_s,
    o.best_time_s       AS sim_optimized_s,
    o.saving_s          AS sim_saving_s,
    o.saving_pct        AS sim_saving_pct,
    EXTRACT(EPOCH FROM (r.finished_at - r.started_at)) AS real_total_s
FROM shipyard_pnp_ws.optimizer_run o
JOIN shipyard_pnp_ws.production_run r USING (run_id);
```

**Idea de implementación**: si el modelo de simulación usa tiempos fijos pero los tiempos reales varían (por variabilidad del robot), actualizar los tiempos del simulador con los promedios reales de `cycle_event` para mejorar la predicción del ahorro.

---

### 2.4 Utilización de recursos (% tiempo activo)
`resource_state_change` tiene la duración en cada estado. Se puede calcular cuánto tiempo cada robot estuvo IDLE vs. GOING_TO_POSITION vs. PICKING, etc.

```sql
SELECT
    resource_id,
    to_state,
    round(SUM(duration_in_prev_s)::numeric, 1) AS total_s,
    round(100.0 * SUM(duration_in_prev_s) /
          SUM(SUM(duration_in_prev_s)) OVER (PARTITION BY resource_id), 1) AS pct
FROM shipyard_pnp_ws.resource_state_change
WHERE run_id = (SELECT run_id FROM shipyard_pnp_ws.production_run ORDER BY started_at DESC LIMIT 1)
GROUP BY resource_id, to_state
ORDER BY resource_id, pct DESC;
```

**Utilidad**: identificar qué robots pasan más tiempo esperando (IDLE) vs. trabajando — cuello de botella sistémico.

---

### 2.5 Latencia comando → ack → status
```sql
SELECT
    c.domain_id,
    c.task_name,
    round(AVG(a.latency_ms)::numeric, 1) AS avg_ack_ms,
    round(MIN(a.latency_ms)::numeric)    AS min_ack_ms,
    round(MAX(a.latency_ms)::numeric)    AS max_ack_ms
FROM shipyard_pnp_ws.command_log c
JOIN shipyard_pnp_ws.ack_log a USING (command_id)
WHERE a.latency_ms IS NOT NULL
GROUP BY c.domain_id, c.task_name
ORDER BY avg_ack_ms DESC;
```

**Utilidad**: detectar dominios con alta latencia de red o procesamiento lento.

---

### 2.6 Profundidad de colas a lo largo del tiempo
`queue_depth_sample` tiene muestras de conveyor1, conveyor2, laser_bed, etc. cada 5 s.

```sql
SELECT
    sampled_at,
    location,
    depth
FROM shipyard_pnp_ws.queue_depth_sample
WHERE run_id = (SELECT run_id FROM shipyard_pnp_ws.production_run ORDER BY started_at DESC LIMIT 1)
ORDER BY sampled_at, location;
```

**Visualización posible**: gráfica de profundidad de colas a lo largo del tiempo → identifica momentos de saturación (conveyor2 lleno mientras robot2 está ocupado con bantam).

---

### 2.7 Ciclos descartados y análisis de fallos
Cuando un ciclo falla (`is_discarded = TRUE`), el `discarded_reason` explica la causa.

```sql
SELECT
    entity,
    task_name,
    discarded_reason,
    COUNT(*) AS n_failures,
    round(AVG(total_duration_s)::numeric, 2) AS avg_time_before_fail_s
FROM shipyard_pnp_ws.cycle_event
WHERE is_discarded = TRUE
GROUP BY entity, task_name, discarded_reason
ORDER BY n_failures DESC;
```

**Utilidad**: tasa de fallo por entidad, cuánto tiempo se pierde por fallo, si hay patrones (p.ej. globalvision falla más con ciertas piezas).

---

### 2.8 Trazabilidad completa de una pieza
Con `piece_id` como hilo conductor, se puede reconstruir todo el ciclo de vida de una pieza.

```sql
-- Traza completa de piece-001
SELECT 'transfer'    AS tipo, ts, from_loc || ' → ' || to_loc AS detalle FROM shipyard_pnp_ws.piece_transfer  WHERE piece_id = 'piece-001'
UNION ALL
SELECT 'vision',            started_at, vision_system || ': ' || COALESCE(detected_color,'?') || '/' || COALESCE(detected_shape,'?') FROM shipyard_pnp_ws.vision_detection WHERE piece_id = 'piece-001'
UNION ALL
SELECT 'cycle_' || entity,  started_at::timestamptz, task_name || ' (' || round(total_duration_s::numeric,1) || 's)' FROM shipyard_pnp_ws.cycle_event      WHERE piece_id = 'piece-001'
ORDER BY 2;
```

---

## 3. Ideas de implementación futura

### 3.1 Actualización automática del modelo del simulador
El optimizador usa tiempos fijos hardcoded (p.ej. `CLASSIFY_AND_PICK = 12 s`).
**Propuesta**: al final de cada run, calcular los promedios reales de `cycle_event` por `(entity, task_name)` y actualizar el modelo de simulación. El optimizador de la siguiente run usará tiempos más precisos.

```python
# En dashboard_node.py, al aplicar resultados de un run:
real_times = db.get_average_cycle_times()  # FROM cycle_event GROUP BY entity, task_name
simulator.update_times(real_times)
```

---

### 3.2 Dashboard de análisis en tiempo real
Ampliar el dashboard existente con una pestaña de analytics que muestre:
- Gantt chart de ciclos de entidades solapados en el tiempo (con datos de `cycle_event.started_at`)
- Gráfica de throughput acumulado de piezas por run
- Tabla de tiempos de fase en vivo (durante producción, con fases abiertas)

---

### 3.3 Detección automática de anomalías
Con suficientes runs, se puede calcular media ± σ por `(entity, task_name)`. Si un ciclo supera media + 2σ, disparar una alarma en `alarm_event`.

```sql
-- Umbral de anomalía por tarea
SELECT entity, task_name,
       AVG(total_duration_s)          AS mean_s,
       STDDEV(total_duration_s)       AS std_s,
       AVG(total_duration_s) + 2 * STDDEV(total_duration_s) AS threshold_s
FROM shipyard_pnp_ws.cycle_event
WHERE is_discarded = FALSE
GROUP BY entity, task_name;
```

---

### 3.4 Análisis de concordancia visión
GlobalVision detecta color en el stack inicial. Robot1 y robot2 hacen una segunda clasificación local al recoger. Se puede medir la tasa de discordancia (GlobalVision dijo RED, robot1 dice BLUE).

```sql
SELECT
    gv.detected_color  AS globalvision_color,
    r1.detected_color  AS robot_color,
    COUNT(*) AS n
FROM shipyard_pnp_ws.vision_detection gv
JOIN shipyard_pnp_ws.vision_detection r1
  ON gv.piece_id = r1.piece_id
 AND r1.vision_system IN ('robot1_camera', 'robot2_camera')
WHERE gv.vision_system = 'globalvision'
GROUP BY 1, 2
ORDER BY n DESC;
```

**Utilidad**: tasa de error de GlobalVision vs. clasificación local → decide si aumentar confianza en una u otra.

---

### 3.5 Optimizador adaptativo multi-run
Con varios runs acumulados en `optimizer_run`, se puede analizar:
- ¿Cuándo la heurística supera al brute force?
- ¿Cuál es el saving real vs. predicho para distintas composiciones de lote?
- Ajustar el `BRUTE_FORCE_THRESHOLD` basándose en el tiempo de optimizer vs. ahorro obtenido.

---

### 3.6 Balanceo de carga bantam/IBS
Actualmente el IBS se usa cuando el bantam está ocupado. Con los datos de `machine_job` y `cycle_event` se puede analizar cuánto tiempo pierde cada pieza BLUE esperando al bantam, y si convendría un segundo bantam o rediseñar la política de cola IBS.

---

## 4. Queries de referencia rápida

```sql
-- Último run
SELECT run_id, original_order, optimized_order, pieces_completed,
       EXTRACT(EPOCH FROM (finished_at - started_at)) AS total_s
FROM shipyard_pnp_ws.production_run ORDER BY started_at DESC LIMIT 1;

-- Tiempos por entidad y tarea
SELECT entity, task_name,
       COUNT(*) AS n,
       round(AVG(total_duration_s)::numeric, 2) AS avg_s,
       round(STDDEV(total_duration_s)::numeric, 2) AS std_s
FROM shipyard_pnp_ws.cycle_event
WHERE is_discarded = FALSE
GROUP BY entity, task_name ORDER BY entity, task_name;

-- Desglose de fases (media)
SELECT phase_data->>'phase' AS phase,
       round(AVG((phase_data->>'duration_s')::float)::numeric, 3) AS avg_s
FROM shipyard_pnp_ws.cycle_event,
     jsonb_array_elements(phases) phase_data
WHERE entity = 'robot1'
GROUP BY 1 ORDER BY avg_s DESC;

-- Ciclos descartados
SELECT entity, task_name, discarded_reason, total_duration_s, ts
FROM shipyard_pnp_ws.cycle_event WHERE is_discarded = TRUE ORDER BY ts;

-- Trazabilidad de pieza
SELECT 'transfer' AS tipo, ts::text, from_loc||'→'||to_loc AS detalle
FROM shipyard_pnp_ws.piece_transfer WHERE piece_id = 'piece-001'
UNION ALL
SELECT 'vision', started_at::text, vision_system||': '||COALESCE(detected_color,'?')
FROM shipyard_pnp_ws.vision_detection WHERE piece_id = 'piece-001'
UNION ALL
SELECT 'cycle:'||entity, started_at::text, task_name||' ('||round(total_duration_s::numeric,1)||'s)'
FROM shipyard_pnp_ws.cycle_event WHERE piece_id = 'piece-001'
ORDER BY 2;
```
