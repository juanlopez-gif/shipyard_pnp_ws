# Shipyard 4.0 — Database Design

**Schema:** `shipyard_pnp_ws`  
**Host:** `100.115.213.16` | **DB:** `twin_mes_db` | **User:** `twin_mes_db`

---

## Filosofía de diseño

La base de datos acumula datos de **múltiples ejecuciones** (runs). Todo dato escrito lleva `run_id` para que sea posible aislar, comparar y filtrar cualquier producción concreta.

El `run_id` es generado una sola vez al arrancar `db_writer.py`:

```
20260619_143022_BGBGRR
└─────────────────────┘└────┘
  timestamp de arranque      iniciales de cada pieza del stack
```

---

## Entidades y tablas

### `production_run` — una ejecución de producción completa

Registro maestro. Se crea al arrancar. Se cierra al terminar.

| Columna | Tipo | Descripción |
|---|---|---|
| `run_id` | TEXT PK | `20260619_143022_BGBGRR` |
| `started_at` | TIMESTAMPTZ | Momento de arranque del nodo |
| `finished_at` | TIMESTAMPTZ | NULL hasta completar/abortar |
| `status` | TEXT | `RUNNING` / `COMPLETED` / `ABORTED` |
| `original_order` | JSONB | `["BLUE","GREEN","RED",...]` — orden inicial del stack |
| `optimized_order` | JSONB | Orden aplicado por el optimizador (NULL si no se usó) |
| `optimizer_savings_s` | FLOAT | Segundos ahorrados según SimPy |
| `total_pieces` | INT | Piezas en el stack al inicio |
| `pieces_completed` | INT | Piezas que llegaron a clasificación final |
| `git_commit` | TEXT | Hash del commit activo (para correlacionar versiones) |
| `config_snapshot` | JSONB | `{"c3_settle_sec":10.0,"c4_settle_sec":14.5,...}` |

---

### `piece` — tabla maestra de piezas

Una fila por pieza física. No cambia durante la producción.

| Columna | Tipo | Descripción |
|---|---|---|
| `piece_id` | TEXT | `piece-001` |
| `run_id` | TEXT FK | |
| `color` | TEXT | `BLUE` / `RED` / `GREEN` |
| `shape` | TEXT | `CIRCLE` / `SQUARE` / `TRIANGLE` — NULL hasta visión |
| `initial_position` | INT | Posición en el stack (1..N) |
| `created_at` | TIMESTAMPTZ | |

---

### `piece_transfer` — cada movimiento de pieza por el pipeline

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `piece_id` | TEXT FK | |
| `from_loc` | TEXT | `initial_stack` / `conveyor1` / `laser_bed`... |
| `to_loc` | TEXT | |
| `moved_by` | TEXT | `robot1` / `xarm1` / `conveyor1` / `system` |
| `ts` | TIMESTAMPTZ | |
| `piece_age_s` | FLOAT | Segundos desde que se creó la pieza |
| `history_json` | JSONB | Historial completo de ubicaciones de la pieza |

---

### `piece_outcome` — resultado final de cada pieza

| Columna | Tipo | Descripción |
|---|---|---|
| `piece_id` | TEXT PK | |
| `run_id` | TEXT FK | |
| `route_taken` | TEXT | `laser` / `bantam` / `laser_bantam` |
| `final_location` | TEXT | `c3` / `c4` / `unloaded` / `lost` |
| `total_time_s` | FLOAT | Tiempo total desde initial_stack hasta destino final |
| `completed` | BOOLEAN | |
| `completed_at` | TIMESTAMPTZ | |

---

### `cycle_event` — timing de ciclo end-to-end por pieza

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `piece_id` | TEXT FK | |
| `color` | TEXT | |
| `shape` | TEXT | |
| `route` | TEXT | |
| `started_at` | TIMESTAMPTZ | Momento en que robot1 la tomó del stack |
| `completed_at` | TIMESTAMPTZ | Momento de clasificación final |
| `cycle_time_s` | FLOAT | `completed_at - started_at` |

---

### `robot_task` — cada tarea ejecutada por un robot

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `command_id` | TEXT | UUID del comando (FK → `command_log`) |
| `robot_id` | TEXT | `robot1` / `robot2` / `xarm1` / `xarm2` |
| `task_name` | TEXT | `PICK` / `PLACE` / `VISION` / `HOME` / `INITIALIZE_DOMAIN` |
| `piece_id` | TEXT FK nullable | |
| `source` | TEXT | |
| `target` | TEXT | |
| `started_at` | TIMESTAMPTZ | |
| `finished_at` | TIMESTAMPTZ | |
| `duration_s` | FLOAT | |
| `result` | TEXT | `COMPLETED` / `FAILED` / `TIMEOUT` |
| `error_detail` | TEXT | |

---

### `machine_job` — cada proceso de laser o bantam

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `command_id` | TEXT FK | |
| `machine_id` | TEXT | `laser` / `bantam` |
| `piece_id` | TEXT FK | |
| `started_at` | TIMESTAMPTZ | |
| `finished_at` | TIMESTAMPTZ | |
| `duration_s` | FLOAT | |
| `door_open_at` | TIMESTAMPTZ | Solo bantam: cuando se abre la puerta |
| `door_close_at` | TIMESTAMPTZ | Solo bantam: cuando se cierra |
| `door_duration_s` | FLOAT | Tiempo que tardó la puerta (overhead) |
| `result` | TEXT | |

---

### `vision_detection` — cada vez que la visión procesa

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `vision_system` | TEXT | `vision_robot1` / `vision_robot2` / `globalvision_camera` |
| `piece_id` | TEXT FK nullable | |
| `detected_color` | TEXT | |
| `detected_shape` | TEXT | |
| `slot_id` | TEXT | Para globalvision: posición física en stack |
| `started_at` | TIMESTAMPTZ | |
| `duration_s` | FLOAT | |
| `success` | BOOLEAN | |

---

### `resource_state_change` — cada cambio de estado de cualquier recurso

Base del OEE y los Gantt reales.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `resource_id` | TEXT | `robot1` / `conveyor1` / `laser` / `c3`... |
| `resource_type` | TEXT | `robot` / `conveyor` / `machine` / `sensor` / `vision` / `vacuum` |
| `from_state` | TEXT | |
| `to_state` | TEXT | |
| `ts` | TIMESTAMPTZ | |
| `duration_in_prev_s` | FLOAT | Tiempo en el estado anterior (calculado al insertar) |

---

### `queue_depth_sample` — profundidad de cola por ubicación en el tiempo

Muestrea cada N segundos. Permite análisis de backpressure.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `sampled_at` | TIMESTAMPTZ | |
| `location` | TEXT | `initial_stack` / `conveyor1` / `laser_bed`... |
| `depth` | INT | Piezas en esa ubicación en ese instante |

---

### `command_log` — todo comando enviado por el supervisor a un dominio

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `command_id` | TEXT UNIQUE | UUID generado por VendorClient |
| `domain_id` | TEXT | `bantam` / `niryo` / `ufactory` / `laser`... |
| `resource_id` | TEXT | `robot1` / `xarm1` / `bantam`... |
| `task_name` | TEXT | |
| `piece_id` | TEXT nullable | |
| `source` | TEXT | |
| `target` | TEXT | |
| `route` | TEXT | |
| `parameters` | JSONB | |
| `sent_at` | TIMESTAMPTZ | |
| `correlation_id` | TEXT | Para agrupar comandos relacionados |

---

### `ack_log` — respuestas de los dominios al supervisor

Un `command_id` puede tener múltiples acks: `RUNNING` → `COMPLETED` / `FAILED`.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `command_id` | TEXT FK | |
| `domain_id` | TEXT | |
| `resource_id` | TEXT | |
| `task_state` | TEXT | `RUNNING` / `COMPLETED` / `FAILED` / `TIMEOUT` |
| `resource_state` | TEXT | `WORKING` / `IDLE` / `ERROR`... |
| `result` | JSONB | Bloque result completo del ack |
| `received_at` | TIMESTAMPTZ | |
| `latency_ms` | INT | `received_at - command_log.sent_at` |

---

### `status_log` — mensajes intermedios de `/bantam_factory/status` etc.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK | |
| `domain_id` | TEXT | |
| `resource_id` | TEXT | |
| `topic` | TEXT | `/bantam_factory/status` |
| `resource_state` | TEXT | |
| `task_state` | TEXT | |
| `code` | TEXT | `CLOSING_DOOR` / `JOB_COMPLETE`... |
| `result` | JSONB | |
| `command_id` | TEXT FK nullable | |
| `published_at` | TIMESTAMPTZ | |

---

### `optimizer_run` — cada ejecución del optimizador de la dashboard

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK nullable | NULL si se lanzó antes del WAITING_FOR_ORDER |
| `original_order` | JSONB | |
| `best_order` | JSONB | |
| `original_time_s` | FLOAT | |
| `best_time_s` | FLOAT | |
| `saving_s` | FLOAT | |
| `saving_pct` | FLOAT | |
| `method` | TEXT | `brute_force` / `heuristic` |
| `permutations_evaluated` | INT | |
| `optimizer_runtime_s` | FLOAT | Cuánto tardó el SimPy en correr |
| `applied` | BOOLEAN | Si el usuario hizo Confirm & Apply |
| `applied_at` | TIMESTAMPTZ | |

---

### `operator_event` — acciones manuales del operador

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK nullable | |
| `event_type` | TEXT | `START_PRODUCTION` / `APPLY_ORDER` / `EMERGENCY_STOP` / `RESTART_DOMAIN` |
| `description` | TEXT | |
| `ts` | TIMESTAMPTZ | |

---

### `alarm_event` — alertas y fallos del sistema

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `run_id` | TEXT FK nullable | |
| `severity` | TEXT | `WARNING` / `ERROR` / `CRITICAL` |
| `resource_id` | TEXT | Recurso que generó la alarma |
| `description` | TEXT | |
| `context_snapshot` | JSONB | Estado completo del sistema en ese momento |
| `triggered_at` | TIMESTAMPTZ | |
| `resolved_at` | TIMESTAMPTZ | NULL hasta resolverse |

---

## Cadena causal completa

```
production_run
  └── piece
        ├── piece_transfer          (cada movimiento)
        ├── piece_outcome           (resultado final)
        └── cycle_event             (tiempo total)
  └── robot_task  ←──── command_log ←── ack_log
  └── machine_job ←──── command_log ←── ack_log
                                    └── status_log
  └── vision_detection
  └── resource_state_change
  └── queue_depth_sample
  └── optimizer_run
  └── operator_event
  └── alarm_event
```

---

## Consultas clave

```sql
-- Reconstruir la cadena completa de un comando
SELECT c.sent_at, 'CMD' AS type, c.task_name, c.resource_id, NULL AS code
FROM command_log c WHERE c.command_id = 'abc123'
UNION ALL
SELECT a.received_at, 'ACK', a.task_state, a.resource_state, NULL
FROM ack_log a WHERE a.command_id = 'abc123'
UNION ALL
SELECT s.published_at, 'STATUS', s.task_state, s.resource_state, s.code
FROM status_log s WHERE s.command_id = 'abc123'
ORDER BY 1;

-- Comparar tiempo de ciclo medio entre dos runs
SELECT run_id, COUNT(*), ROUND(AVG(cycle_time_s)::numeric, 2) AS avg_s
FROM cycle_event GROUP BY run_id ORDER BY run_id;

-- Utilización de cada robot en un run
SELECT robot_id,
       ROUND(100.0 * SUM(duration_s) / MAX(total_s), 1) AS utilization_pct
FROM robot_task
JOIN (SELECT EXTRACT(EPOCH FROM (finished_at - started_at)) AS total_s
      FROM production_run WHERE run_id = '20260619_143022_BGBGRR') r ON TRUE
WHERE run_id = '20260619_143022_BGBGRR' AND result = 'COMPLETED'
GROUP BY robot_id;

-- Overhead de la puerta bantam
SELECT piece_id, door_duration_s, duration_s,
       ROUND(100.0 * door_duration_s / duration_s, 1) AS door_pct
FROM machine_job WHERE machine_id = 'bantam' ORDER BY door_duration_s DESC;

-- Backpressure en conveyor2
SELECT DATE_TRUNC('second', sampled_at), AVG(depth)
FROM queue_depth_sample
WHERE location = 'conveyor2' AND run_id = '20260619_143022_BGBGRR'
GROUP BY 1 ORDER BY 1;
```

---

## Notas de implementación

- El esquema se crea automáticamente en `db_writer.py` con `CREATE SCHEMA IF NOT EXISTS` y `CREATE TABLE IF NOT EXISTS`.
- `RealDBWriter.__init__()` llama a `_ensure_schema()` antes de cualquier inserción.
- `StubDBWriter` no cambia — sigue siendo el writer por defecto durante desarrollo.
- La transición a `RealDBWriter` se hace en `factory_supervisor.py` cambiando `StubDBWriter()` por `RealDBWriter()`.
- El `run_id` fluye por todo el sistema: es generado en `RealDBWriter.__init__()` y pasado a cada `insert_*()` automáticamente — el código llamador no necesita conocerlo.
