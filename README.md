# Shipyard Pick & Place — Sistema de Automatización de Fábrica

**Fecha de este documento:** 19 de junio de 2026  
**Stack:** ROS 2 Jazzy · Python 3.12 · Ubuntu 24.04  
**Arquitectura:** Plug-and-Plan (FS → VS · Command / Ack / Status)

---

## Índice

1. [Visión general](#1-visión-general)
2. [Arquitectura del sistema](#2-arquitectura-del-sistema)
3. [Hardware y red](#3-hardware-y-red)
4. [Nodos ROS 2](#4-nodos-ros-2)
5. [Protocolo de comunicación](#5-protocolo-de-comunicación)
6. [Rutas de producción por color](#6-rutas-de-producción-por-color)
7. [Factory Supervisor — núcleo de coordinación](#7-factory-supervisor--núcleo-de-coordinación)
8. [Planificador — reglas por módulo](#8-planificador--reglas-por-módulo)
9. [Principio de sensores soberanos](#9-principio-de-sensores-soberanos)
10. [Vendor Supervisors — capa de hardware](#10-vendor-supervisors--capa-de-hardware)
11. [Trackers internos](#11-trackers-internos)
12. [Configuración](#12-configuración)
13. [Arranque del sistema](#13-arranque-del-sistema)
14. [Base de datos](#14-base-de-datos)
15. [Bugs resueltos](#15-bugs-resueltos)
16. [Estado actual y pendientes](#16-estado-actual-y-pendientes)

---

## 1. Visión general

Sistema de automatización de fábrica Pick & Place que procesa piezas de tres colores (ROJO, VERDE, AZUL) a través de una línea de producción robotizada. El sistema utiliza una arquitectura de dos capas:

- **Factory Supervisor (FS):** Coordinador MES-level. Toma todas las decisiones de planificación, hace seguimiento de piezas y ciclos, y envía comandos a los dominios de hardware.
- **Vendor Supervisors (VS):** Un nodo ROS 2 por dominio de hardware. Recibe comandos del FS, ejecuta el trabajo real sobre el hardware y publica estado de vuelta.

El FS no sabe *cómo* mueve un brazo; los VS no saben *por qué* se mueve una pieza. La separación es estricta.

---

## 2. Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────────────┐
│                     FACTORY SUPERVISOR                          │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ PieceTracker│  │ StateTracker │  │    CycleTracker       │  │
│  └─────────────┘  └──────────────┘  └───────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    PLANIFICADOR                            │ │
│  │  initialization · feeding · conveyor · processing         │ │
│  │  classification · unloading · shutdown                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │               VendorClient × 7                             │ │
│  │  (niryo · ufactory · laser · globalvision ·               │ │
│  │   green_conveyors · arduino_vacuum · bantam)               │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────┬───────────────────────────────────────────────┘
                  │  ROS 2 topics  (command / ack / status)
   ┌──────────────┼──────────────────────────────────────┐
   │              │                                      │
   ▼              ▼                                      ▼
NiryoVS    UFactoryVS    LaserVS   GlobalVisionVS   GreenConveyorsVS
                                   ArduinoVacuumVS   BantamVS
```

### Flujo de un comando

```
FS.send_command()
   └─► VendorClient.send_command()   ← publica JSON en /{domain}_factory/command
         └─► VS._on_command_raw()    ← recibe, valida, llama handle_task()
               └─► publish_ack()     ← /{domain}_factory/ack
               └─► TaskRunner.run()  ← hilo de hardware
                     └─► publish_status() RUNNING / COMPLETED / FAILED
                                          /{domain}_factory/status
FS.on_status()
   └─► VendorClient.on_status_received()
         └─► on_complete callback()  ← siguiente paso de la regla
   └─► evaluate_rules()              ← si terminal O sensor_updated
```

---

## 3. Hardware y red

| Equipo | Modelo | IP | Puerto/Conexión |
|---|---|---|---|
| Robot Niryo 1 | Ned2 | 192.168.0.195 | /robot1 namespace |
| Robot Niryo 2 | Ned2 | 192.168.0.244 | /robot2 namespace |
| xArm 1 | UFACTORY Lite6 | 192.168.0.254 | /xarm1 namespace |
| xArm 2 | UFACTORY Lite6 | 192.168.0.168 | /xarm2 namespace |
| Láser | HTTP API | 192.168.0.173 | HTTP REST |
| Bantam CNC | Simulado + ZMQ door | 192.168.0.171:5555 | ZMQ REQ/REP |
| Arduino (vacío) | Serial | /dev/ttyACM1 | 9600 baud |
| Arduino (cintas verdes) | Serial | /dev/ttyACM0 | 115200 baud |
| Cámara global | USB OpenCV | /dev/video0 | camera_index=0 |

### Sensores IR físicos (activo a LOW)

| Sensor | Cinta | Pin Niryo | Descripción |
|---|---|---|---|
| c1s1 | Conveyor 1 | DI5 (robot1) | Entrada cinta 1 — pieza depositada por xArm2 |
| c1s2 | Conveyor 1 | DI1 (robot1) | Salida cinta 1 — pieza lista para xArm1 |
| c2s1 | Conveyor 2 | DI5 (robot2) | Entrada cinta 2 — pieza depositada por xArm1 |
| c2s2 | Conveyor 2 | DI1 (robot2) | Salida cinta 2 — pieza lista para robot2 |

### Sensores virtuales (sin hardware IR)

| Sensor | Quién escribe | Descripción |
|---|---|---|
| c3 | `feeding_rules` | Posición de pickup de robot1 para piezas VERDES |
| c4 | `classification_rules` | Posición de pickup de robot1 para piezas ROJA/AZUL |

---

## 4. Nodos ROS 2

### factory_supervisor
- **Ejecutable:** `factory_supervisor`
- **Descripción:** Coordinador principal. Fases: BOOT → RUNNING → SHUTTING_DOWN → STOPPED.
- **Timers:** planner 0.5 s · watchdog 1.0 s · system_state_pub 2.0 s
- **Callback groups:** ReentrantCallbackGroup (ack/status) · MutuallyExclusiveCallbackGroup (planner, watchdog, dashboard, order)
- **Executor:** MultiThreadedExecutor(num_threads=4)
- **Tópicos suscritos:** `/{domain}_factory/ack`, `/{domain}_factory/status`, `/supervisor/set_optimized_order`
- **Tópicos publicados:** `/{domain}_factory/command`, `/factory/system_state`

### niryo_vendor_supervisor
- **Ejecutable:** `niryo_vendor_supervisor`
- **Modo:** `hardware` (configurado en hardware_ports.yaml)
- **Recursos gestionados:** robot1, robot2, conveyor1, conveyor2, vision_robot1, vision_robot2, robot2_niryo_vacuum
- **Parámetros:** mode, robot1_namespace, robot1_ip, robot2_namespace, robot2_ip, service_wait_timeout_sec (10 s), command_timeout_sec (45 s), settle_time_sec (0.2 s), vacuum_delay_sec (0.5 s), sensor_poll_interval_sec (0.2 s), conveyor_run_timeout_sec (30 s)
- **TaskRunners independientes:** robot1 · robot2 · conveyor1 · conveyor2 (ejecución concurrente)
- **Timer de polling de sensores IR:** cada 0.2 s en hardware mode
- **Executor:** MultiThreadedExecutor(num_threads=4)

### ufactory_vendor_supervisor
- **Ejecutable:** `ufactory_vendor_supervisor`
- **Modo:** `dry_run` (actualmente, cambiar a hardware para producción real)
- **Recursos:** xarm1, xarm2
- **Parámetros:** mode, xarm1_namespace (/xarm1), xarm2_namespace (/xarm2), command_timeout_sec (35 s), default_speed (30.0), default_acc (100.0), settle_time_sec (0.5 s), gripper_delay_sec (0.5 s)
- **TaskRunners:** uno por xArm, paralelo
- **Executor:** MultiThreadedExecutor(num_threads=4)

### laser_vendor_supervisor
- **Ejecutable:** `laser_vendor_supervisor`
- **Modo:** HTTP API
- **Parámetros:** laser_ip (192.168.0.173), gcode_dir, default_gcode (happyface.gcode), job_duration_sec (2.0), wait_time_before_start_sec (2.0), http_timeout_sec (10.0)
- **Seguridad:** lista blanca de archivos gcode, lista negra de fragmentos (bloquea S25)
- **Timeout FS:** 300 s para RUN_JOB

### globalvision_vendor_supervisor
- **Ejecutable:** `globalvision_vendor_supervisor`
- **Descripción:** Cámara USB + OpenCV. Detecta slot_id, color y shape de piezas en el stack inicial.
- **Parámetros:** camera_index (0), color_threshold_pct (5.0%), show_window (false por defecto)
- **Tareas soportadas:** INITIALIZE_DOMAIN, SCAN_STACK, LOCATE_NEXT_PIECE, GET_INVENTORY, RESET
- **Ventana de preview:** activable con `--ros-args -p show_window:=true` (20fps, tecla Q/ESC cierra)

### green_conveyors_vendor_supervisor
- **Ejecutable:** `green_conveyors_vendor_supervisor`
- **Descripción:** Controla cintas Arduino de salida (conveyor3 canal B, conveyor4 canal A)
- **Parámetros:** port (/dev/ttyACM0), baudrate (115200), conveyor3_speed (9000), conveyor4_speed (9000), conveyor3_direction (REV), conveyor4_direction (FWD)
- **Tareas:** RUN_CONVEYOR, STOP_CONVEYOR, SET_SPEED

### arduino_vacuum_vendor_supervisor
- **Ejecutable:** `arduino_vacuum_vendor_supervisor`
- **Descripción:** Control del sistema de vacío Arduino para robot1
- **Parámetros:** port (/dev/ttyACM1), baudrate (9600), pick_hold_sec (0.5), release_hold_sec (0.3)
- **Tareas:** PICK, RELEASE, OFF

### bantam_vendor_supervisor
- **Ejecutable:** `bantam_vendor_supervisor`
- **Descripción:** CNC Bantam con control de puerta ZMQ y simulación de mecanizado
- **Parámetros:** processing_time_sec (25.0 — simulado), door_timeout_sec (12 s), door_zmq_address (tcp://192.168.0.171:5555)
- **Timeout FS:** 600 s para RUN_JOB

### dashboard_node
- **Ejecutable:** `dashboard_node`
- **Estado:** Nodo en el launch file, desarrollo PENDIENTE (no implementar hasta decisión explícita)

---

## 5. Protocolo de comunicación

### Tópicos por dominio

```
/{domain}_factory/command   →  FS publica, VS suscribe
/{domain}_factory/ack       →  VS publica, FS suscribe
/{domain}_factory/status    →  VS publica, FS suscribe
```

Dominos: `niryo`, `ufactory`, `laser`, `globalvision`, `green_conveyors`, `arduino_vacuum`, `bantam`

### Estructura de un comando

```json
{
  "command_id": "niryo-0042-1718755800.123",
  "domain_id": "niryo",
  "resource_id": "conveyor1",
  "task": "RUN_NIRYO_CONVEYOR",
  "piece_id": "piece-001",
  "source": "C1S1",
  "target": "C1S2",
  "route": "RED",
  "parameters": {"conveyor_id": "conveyor1"},
  "correlation_id": null,
  "hmac": "..."
}
```

### Estructura de un ACK

```json
{
  "command_id": "niryo-0042-...",
  "domain_id": "niryo",
  "resource_id": "conveyor1",
  "accepted": true,
  "reason": null
}
```

### Estructura de un STATUS

```json
{
  "command_id": "niryo-0042-...",
  "domain_id": "niryo",
  "resource_id": "conveyor1",
  "task": "RUN_NIRYO_CONVEYOR",
  "task_state": "COMPLETED",
  "resource_state": "STOPPED",
  "piece_id": "piece-001",
  "source": "C1S1",
  "target": "C1S2",
  "route": "RED",
  "result": {
    "code": "STOPPED_AT_EXIT_SENSOR",
    "sensor_id": "c1s2",
    "state": "OCCUPIED"
  }
}
```

### Estados de tarea (TaskState)

`RECEIVED` → `RUNNING` → `COMPLETED` | `FAILED` | `REJECTED` | `TIMEOUT` | `CANCELED`

Los estados terminales son: COMPLETED, FAILED, REJECTED, TIMEOUT, CANCELED.

### SENSOR_UPDATE autónomo

Los VS de Niryo emiten STATUS autónomos con `command_id="AUTO"` cuando el polling de sensores detecta un cambio:

```json
{
  "command_id": "AUTO",
  "task": "SENSOR_UPDATE",
  "task_state": "COMPLETED",
  "resource_id": "c1s2",
  "resource_state": "OCCUPIED",
  "result": {"code": "SENSOR_UPDATE", "sensor_id": "c1s2", "state": "OCCUPIED"}
}
```

Estos mensajes son ignorados por `VendorClient.on_status_received()` (no correlacionan con pending commands) pero procesados directamente por `FactorySupervisor._apply_sensor_result()`, que actualiza el StateTracker y dispara `evaluate_rules()` inmediatamente.

### HMAC (Phase 1-5: warn-only)

El sistema incluye infraestructura HMAC en `shared/messages.py` y `config/hmac_secrets.yaml`. En las fases actuales (1-5) una fallo de HMAC genera un WARNING pero NO rechaza el comando. Se activará enforcement estricto en fases posteriores.

---

## 6. Rutas de producción por color

```
RED:   initial_stack → conveyor1 → laser_bed → conveyor2 → c4_location → final_red_stack
BLUE:  initial_stack → conveyor1 → conveyor2 → bantam_bed → c4_location → final_blue_stack
GREEN: initial_stack → c3_location → final_green_stack
```

### Descripción detallada por color

**ROJO:**
1. xArm2 recoge del stack (globalvision da slot_id)
2. xArm2 deposita en c1s1 (cinta 1 entrada)
3. Cinta 1 arranca cuando c1s1=OCCUPIED y c1s2=FREE → para cuando c1s2=OCCUPIED
4. xArm1 recoge de c1s2 → deposita en LASER_BED
5. Láser graba (happyface.gcode)
6. xArm1 recoge de LASER_BED → deposita en c2s1 (espera si c2s1=OCCUPIED)
7. Cinta 2 arranca cuando c2s1=OCCUPIED y (c2s2=FREE ó _c2s2_committed) → para en c2s2
8. Robot2 hace visión local en c2s2
9. Robot2 recoge de c2s2 → deposita en c4_location, arranca conveyor4
10. Robot1 clasifica y recoge de c4 (espera c4_settle_sec=14.5 s) → vacío → deposita en final_red_stack

**AZUL:**
1–4. Igual que ROJO hasta c1s2
4. xArm1 recoge de c1s2 → deposita directamente en c2s1 (sin láser)
5–7. Igual que ROJO
8. Robot2 hace visión local → decide BANTAM
9. Robot2 deposita en bantam_bed, Bantam mecaniza (25 s simulados)
10. Robot2 recoge de bantam_bed → deposita en c4_location
11. Robot1 igual que ROJO

**VERDE:**
1. xArm2 recoge del stack → deposita directamente en c3_location
2. Conveyor3 arranca → para después de c3_settle_sec=10 s
3. Robot1 clasifica y recoge de c3 → deposita en final_green_stack (bypassa conveyor1, xArm1, conveyor2, robot2 completamente)

---

## 7. Factory Supervisor — núcleo de coordinación

**Archivo:** `factory/factory_supervisor.py`

### Estado del planificador

```python
self.planner_phase         # PlannerPhase: BOOT | RUNNING | SHUTTING_DOWN | STOPPED
self._feeding_state        # "IDLE" | "WAITING_VISION" | "WAITING_XARM2_PICK" | ...
self._processing_state     # "IDLE" | "WAITING_XARM1_TO_LASER" | "WAITING_LASER" |
                           # "LASER_DONE_WAITING_C2S1" | "WAITING_XARM1_TO_C2S1" | ...
self._classification_state # "IDLE" | "WAITING_VISION" | "WAITING_ROBOT2_TO_C4" | ...
self._unloading_state      # "IDLE" | "WAITING_CLASSIFY_PICK" | "WAITING_VACUUM_PICK" | ...
self._shutdown_state       # "IDLE" | paso actual de shutdown
```

### Campos de estado críticos

```python
self._c2s2_committed: bool     # True: robot2 va a recoger de c2s2 → conveyor2 puede arrancar
self._pending_laser_piece_id   # ID de pieza cuando laser termina y c2s1 está ocupado
self._c3_deposit_time: float   # timestamp de último depósito en c3 (settle guard)
self._c4_deposit_time: float   # timestamp de último depósito en c4 (settle guard)
self.c3_settle_sec: float      # 10.0 s — tiempo que robot1 espera antes de recoger de c3
self.c4_settle_sec: float      # 14.5 s — tiempo que robot1 espera antes de recoger de c4
```

### Ciclo principal

```
Timer 0.5 s → evaluate_rules()
  BOOT:         initialization_rules.evaluate()
  RUNNING:      feeding → conveyor → processing → classification → unloading
  SHUTTING_DOWN: shutdown_rules.evaluate()
```

Adicionalmente, `evaluate_rules()` se dispara INMEDIATAMENTE cuando `on_status()` recibe:
- Un mensaje con `task_state` terminal (COMPLETED/FAILED/REJECTED/TIMEOUT/CANCELED)
- Un `SENSOR_UPDATE` con cambio de estado (`sensor_updated=True`)

Esto garantiza que un cambio físico en un sensor IR dispara la evaluación de reglas sin esperar los 500 ms del timer.

### Watchdog (1 s)

Llama `VendorClient.check_timeout()` en todos los dominios. Si un comando supera su timeout (por defecto 120 s, overrides por tarea) se completa con `TIMEOUT`.

### Timeouts por tarea

| Tarea | Timeout |
|---|---|
| INITIALIZE_DOMAIN | 30 s |
| SCAN_STACK | 15 s |
| LOCATE_NEXT_PIECE | 10 s |
| GOTO_PICK_POSITION | 60 s |
| LIFT_AND_PLACE | 60 s |
| RETURN_HOME | 60 s |
| RUN_NIRYO_CONVEYOR | 30 s |
| PICK / RELEASE | 5 s |
| RUN_JOB (laser) | 300 s |
| RUN_JOB (bantam) | 600 s |
| Default | 120 s |

### Log de estado periódico (cada 10 s en RUNNING)

```
[state] proc=IDLE feed=IDLE class=IDLE unload=IDLE |
        c1s1=FREE c1s2=OCCUPIED c2s1=FREE c2s2=FREE c4=FREE |
        xarm1=IDLE xarm2=IDLE robot1=IDLE robot2=IDLE |
        conv1=1 laser=0 conv2=0
```

### Stack inicial (hardcoded en factory_supervisor.py)

```python
INITIAL_STACK_ORDER = [
    {"id": "piece-001", "color": "RED", "shape": None},
    {"id": "piece-002", "color": "RED", "shape": None},
    {"id": "piece-003", "color": "RED", "shape": None},
    {"id": "piece-003", "color": "RED", "shape": None},
]
```

El color/shape son hints para globalvision. Si se pone `None`, globalvision los detecta automáticamente.

---

## 8. Planificador — reglas por módulo

### 8.1 initialization_rules.py

Secuencia de arranque en orden de dependencia:

```
arduino_vacuum → green_conveyors → globalvision → ufactory → niryo → laser → bantam → RUNNING
```

Cada dominio espera COMPLETED antes de iniciar el siguiente. Si un dominio falla, reintenta en el próximo tick. Si el VS no tiene suscriptor aún (no ha arrancado), espera y avisa sin bloquear.

### 8.2 feeding_rules.py

**Precondiciones para arrancar:**
- `_feeding_state == "IDLE"`
- `initial_stack` tiene piezas
- `xarm2 == IDLE` y no busy en ufactory
- `c1s1 == FREE` (hardware IR — sensor soberano)
- globalvision no busy
- Si la próxima pieza es VERDE: `c3 == FREE`

**Flujo:**
1. `LOCATE_NEXT_PIECE` (globalvision) → obtiene slot_id, color, shape
2. Si VERDE: `MOVE_PIECE xarm2 → C3` → `c3=OCCUPIED` (virtual), arranca conveyor3, espera HOME
3. Si no VERDE: `MOVE_PIECE xarm2 → C1S1`

**Callback `_on_xarm2_to_c1_complete`:**
- `pieces.transfer("initial_stack", "conveyor1")`
- `cycles.start_cycle(piece_id)`
- `xarm2 = IDLE`
- **NO escribe c1s1=OCCUPIED** (el sensor IR de hardware ya lo hizo o lo hará; escribirlo aquí crea una condición de carrera)

### 8.3 conveyor_rules.py

**Cinta 1:**
- Arranca cuando: `c1s1=OCCUPIED`, `conveyor1=STOPPED`, `c1s2=FREE`
- Para automáticamente cuando el VS detecta que `c1s2=OCCUPIED` (el VS gestiona el loop de polling internamente)

**Cinta 2:**
- Arranca cuando: `c2s1=OCCUPIED`, `conveyor2=STOPPED`, y (`c2s2=FREE` O `_c2s2_committed=True`)
- `_c2s2_committed` se activa en `_on_vision_complete` (robot2 se ha comprometido a recoger)
- Se limpia cuando `_conveyor2_rules` efectivamente arranca la cinta
- Así conveyor2 arranca ~14 s antes de que el sensor físico detecte la pieza recogida

**Callback `_on_conveyor_done`:**
- Solo actualiza `conveyor_id = STOPPED`
- **No escribe ningún sensor** (sensores soberanos)

### 8.4 processing_rules.py

**Precondiciones:**
- `_processing_state == "IDLE"`
- `conveyor1` tiene piezas
- `c1s2 == OCCUPIED`
- `xarm1 == IDLE` y no busy en ufactory

**Decisión por color:**

```python
if color == "RED":
    # c2s1 NO se comprueba aquí — va al láser, no a c2s1
    _send_xarm1_to_laser(fs, piece_id)
else:
    if c2s1 != FREE:
        return  # espera
    _send_xarm1_direct_to_c2(fs, piece_id, color)
```

**Estado `LASER_DONE_WAITING_C2S1`:**

Cuando el láser termina pero c2s1 sigue ocupado, el procesador entra en este estado. El siguiente tick de `evaluate_rules()` (disparado cuando c2s1 cambia a FREE por el sensor IR) envía a xArm1 de LASER_BED a C2S1.

```python
if fs._processing_state == "LASER_DONE_WAITING_C2S1":
    if c2s1 == FREE and not xarm1.is_busy():
        _send_xarm1_laser_to_c2(fs, fs._pending_laser_piece_id)
    return
```

**Logs de processing:**
```
[processing] xarm1 → LASER_BED: piece=piece-001
[processing] xarm1 LASER_BED → C2S1: piece=piece-001
```

### 8.5 classification_rules.py

**Precondiciones:**
- `_classification_state == "IDLE"`
- `conveyor2` tiene piezas
- `c2s2 == OCCUPIED`
- `c4 == FREE`
- `robot2 == IDLE` y no busy en niryo

**Flujo:**
1. `CAPTURE_LOCAL_VISION` (robot2 en C2S2) → obtiene color, shape
2. En `_on_vision_complete`: establece `_c2s2_committed = True`, log `c2s2_committed=True`
3. Enruta según color:
   - RED/GREEN → `MOVE_PIECE robot2 C2S2 → C4`
   - BLUE + bantam libre → `MOVE_PIECE robot2 C2S2 → BANTAM_BED`
   - BLUE + bantam ocupado, o UNKNOWN → `MOVE_PIECE robot2 C2S2 → SCRAP`

**`_on_robot2_to_c4_complete`:**
- `pieces.transfer("conveyor2", "c4_location")`
- `state.update_sensor("c4", OCCUPIED)` ← c4 es virtual, OK
- `_c4_deposit_time = time.time()`
- Arranca conveyor4 + auto-stop tras c4_settle_sec
- Envía robot2 a HOME

**No escribe c2s2** en ningún callback (sensor soberano).

### 8.6 unloading_rules.py

**Precondiciones:**
- `_unloading_state == "IDLE"`
- `robot1 == IDLE` y no busy
- arduino_vacuum no busy

**Lógica de selección:**
- Priorita c4 sobre c3
- Respeta settle time (`c4_settle_sec=14.5 s`, `c3_settle_sec=10 s`)

**Flujo:**
1. `CLASSIFY_AND_PICK` (robot1 en C4 o C3): robot1 va a posición, hace visión local, pick
2. `PICK` (arduino_vacuum): activa succión
3. En `_on_vacuum_pick_complete`: escribe `c3/c4 = FREE` (virtual — la pieza ya está en el aire)
4. `LIFT_AND_PLACE` (robot1): lleva la pieza al destino final
5. `RELEASE` (arduino_vacuum)
6. `RETURN_HOME` (robot1)
7. `cycles.complete_cycle()` → `db.insert_cycle_complete()`

**Destinos finales por color y forma:**

| Color | Forma | Destino |
|---|---|---|
| RED | cualquiera | FINAL_RED_STACK |
| RED | CIRCLE | FINAL_RED_CIRCLE |
| GREEN | cualquiera | FINAL_GREEN_STACK |
| GREEN | CIRCLE | FINAL_GREEN_CIRCLE |
| BLUE | cualquiera | FINAL_BLUE_STACK |
| BLUE | CIRCLE | FINAL_BLUE_CIRCLE |
| UNKNOWN | — | SCRAP |

### 8.7 shutdown_rules.py

Se activa cuando `pieces.all_pieces_finished() == True` (initial_stack vacío Y todas las ubicaciones intermedias vacías). Envía STOP/RESET a todos los dominios en orden inverso.

---

## 9. Principio de sensores soberanos

### Regla fundamental

**Los sensores físicos c1s1, c1s2, c2s1, c2s2 son SOBERANOS. Ningún callback de robot, ninguna regla del planificador, ningún VS excepto el de Niryo tiene permitido escribir su estado.**

La única fuente de verdad para estos sensores es el hardware IR, leído por `NiryoConveyorAdapter.poll_sensors()` cada 200 ms y publicado como SENSOR_UPDATE autónomo.

### Por qué esta regla existe

Antes de implementarla, los callbacks de los robots escribían manualmente los sensores "para ayudar" al planificador. Esto causaba condiciones de carrera fatales:

**Ejemplo del bug crítico de c1s1:**
```
t=0:   hardware c1s1 → OCCUPIED  (xArm2 depositó la pieza)
t=0:   conveyor1 arranca inmediatamente
t=2:   hardware c1s1 → FREE  (la pieza se movió a c1s2)
t=3:   _on_xarm2_to_c1_complete() dispara TARDE
t=3:   ← escribía c1s1=OCCUPIED  (INCORRECTO — pieza ya no está aquí)
t=3:   conveyor adapter tiene _last_sensor_states["c1s1"]="FREE"
       nunca re-emite FREE porque ya está en "FREE"
t=3:   supervisor queda con c1s1=OCCUPIED permanentemente
t=33:  conveyor1 timeout con 30 s sin pieza
t=33:  xArm2 nunca puede depositar la siguiente pieza
RESULTADO: solo 1 de 4 piezas procesadas
```

### Sensores y quién los escribe

| Sensor | Tipo | Escrito por |
|---|---|---|
| c1s1 | Físico IR | `niryo_vendor_supervisor._publish_auto_sensor()` |
| c1s2 | Físico IR | `niryo_vendor_supervisor._publish_auto_sensor()` |
| c2s1 | Físico IR | `niryo_vendor_supervisor._publish_auto_sensor()` |
| c2s2 | Físico IR | `niryo_vendor_supervisor._publish_auto_sensor()` |
| c3 | Virtual | `feeding_rules._on_xarm2_to_c3_complete()` y `unloading_rules._on_vacuum_pick_complete()` |
| c4 | Virtual | `classification_rules._on_robot2_to_c4_complete()` y `unloading_rules._on_vacuum_pick_complete()` |

### Verificación

```bash
grep -rn 'update_sensor.*c1s1\|update_sensor.*c1s2\|update_sensor.*c2s1\|update_sensor.*c2s2' \
     src/shipyard_pnp/shipyard_pnp/factory/planner/
# Resultado: cero ocurrencias
```

### Mecanismo `_c2s2_committed`

El flag `_c2s2_committed` resuelve el problema del retraso de conveyor2 sin violar los sensores soberanos:

**Problema:** El sensor c2s2 pasa de OCCUPIED a FREE cuando robot2 físicamente levanta la pieza. Eso ocurre ~14 s después de que la visión termina. Si conveyor2 espera hasta que el hardware confirme c2s2=FREE, la cinta se retrasa 14 s innecesariamente.

**Solución:** En `_on_vision_complete`, cuando robot2 confirma que va a recoger la pieza:
```python
fs._c2s2_committed = True
# NO se escribe c2s2=FREE — el hardware lo hará cuando sea cierto
```

En `_conveyor2_rules`:
```python
c2s2_clear = c2s2 == SensorState.FREE or fs._c2s2_committed
if c2s1 == OCCUPIED and conveyor2 == STOPPED and c2s2_clear:
    fs._c2s2_committed = False  # consumir el flag
    # arrancar conveyor2
```

---

## 10. Vendor Supervisors — capa de hardware

### BaseVendorSupervisor

**Archivo:** `vendors/common/base_vendor_supervisor.py`

Clase base abstracta para todos los VS. Proporciona:
- Wiring ROS 2: `cmd_sub`, `ack_pub`, `status_pub`
- Parsing y validación JSON de comandos entrantes
- Verificación HMAC (warn-only en fases 1-5)
- `publish_ack()` y `publish_status()` helpers
- `TaskRunner` base para uso opcional por subclases
- `InternalBus` base (para uso inter-adapter interno)
- Interfaz abstracta `handle_task(cmd) → (accepted, reason)`

### TaskRunner

**Archivo:** `vendors/common/task_runner.py`

Ejecuta funciones de hardware en un hilo daemon. No bloquea el hilo ROS 2. Proporciona `is_running()`, `run(task_fn, on_complete, on_error)` y `join()`.

### NiryoConveyorAdapter

**Archivo:** `vendors/niryo/niryo_conveyor_adapter.py`

Gestiona una cinta Niryo con sensores IR:
- `run_until_exit_sensor()`: arranca la cinta, hace polling de sensores hasta que el sensor de salida se activa, para la cinta. Si timeout: **para el hardware físico antes de lanzar TimeoutError** (fix importante).
- `poll_sensors()`: lee todos los pines configurados, compara con `_last_sensor_states`, emite solo cambios. Retorna lista de dicts con `sensor_id, state, raw, pin, active_low`.
- `initialize()`: inicializa cinta, para, fuerza lectura de sensores con `force=True`.

**Pin logic:**
```python
raw_value = driver.read_digital_io(cfg["pin"])
active_low = cfg.get("active_low", True)   # true para estos sensores
occupied = not raw_value if active_low else raw_value
```

### NiryoVendorSupervisor — polling autónomo de sensores

```python
# Timer cada 200 ms (solo en hardware mode)
def _poll_sensors_once(self):
    for conveyor in self.conveyors.values():
        updates = conveyor.poll_sensors(self._publish_auto_sensor)
        # log raw a DEBUG para diagnóstico

def _publish_auto_sensor(self, sensor_id, state):
    self.get_logger().info(f"[sensor] {sensor_id} → {state}")
    self.publish_status(command_id="AUTO", task="SENSOR_UPDATE", ...)
```

Cada cambio de sensor aparece en terminal:
```
[sensor] c1s2 → OCCUPIED
[sensor] c1s1 → FREE
```

Para ver el nivel raw de pin:
```bash
ros2 run shipyard_pnp niryo_vendor_supervisor --ros-args \
     --log-level niryo_vendor_supervisor:=DEBUG
```

### LocalVisionAdapter (robot1 y robot2)

**Archivo:** `vendors/niryo/local_vision_adapter.py`

Suscribe al topic de video comprimido del Niryo (`/robot2/niryo_robot_vision/compressed_video_stream`). Realiza N capturas (default: 15) con timeout configurable (8 s), con umbral de detección (0.03). En dry_run retorna el color configurado en `vision_default_color`.

### Robot2Adapter

**Archivo:** `vendors/niryo/robot2_adapter.py`

Implementa `capture_local_vision()` y `move_piece(source, target)`. Internamente orquesta vision_adapter y robot2_niryo_vacuum_adapter en la secuencia correcta. Robot2 y sus recursos (vision_robot2, robot2_niryo_vacuum) comparten el mismo TaskRunner en el VS.

### Robot1Adapter

**Archivo:** `vendors/niryo/robot1_adapter.py`

Implementa `classify_and_goto_pick(position)`, `lift_and_place(target)`, `move_home()`. Se coordina con vision_robot1 internamente. Usa el Arduino vacuum externamente (el FS serializa las llamadas).

### XArm1Adapter / XArm2Adapter

**Archivos:** `vendors/ufactory/xarm1_adapter.py`, `vendors/ufactory/xarm2_adapter.py`

Wrapping del driver Lite6. XArm1 implementa `move_piece(source, target, route)` para las rutas C1S2→LASER_BED, LASER_BED→C2S1, C1S2→C2S1. XArm2 implementa `move_piece(pick_slot, target)` para INITIAL_STACK→C1S1 y INITIAL_STACK→C3.

### Lite6ServiceDriver

**Archivo:** `vendors/ufactory/lite6_service_driver.py`

Driver de bajo nivel para UFACTORY Lite6 via ROS 2 service calls (`xarm_api`). En dry_run simula timing realista sin mover hardware.

### GlobalVisionCameraAdapter

**Archivo:** `vendors/globalvision/camera_adapter.py`

OpenCV + SlotInventory. Detecta piezas en el stack inicial. `LOCATE_NEXT_PIECE` retorna `slot_id`, `color`, `shape` para la siguiente pieza a procesar.

---

## 11. Trackers internos

### StateTracker

**Archivo:** `factory/state_tracker.py`

Tabla de estado coarse de todos los recursos. No thread-safe — protegido por `FactorySupervisor._state_lock`.

Categorías: robots, conveyors, sensors, machines, vacuum, vision, domain_online.

Método `apply_resource_state(resource_id, state_str)`: usado por `on_status()` para despachar actualizaciones de resource_state entrantes.

### PieceTracker

**Archivo:** `factory/piece_tracker.py`

Single source of truth para la ubicación de todas las piezas. Usa `deque` por ubicación. Ubicaciones:

```
initial_stack → xarm2_gripper → c3_location → conveyor1 → xarm1_gripper →
laser_bed → conveyor2 → robot2_gripper → c4_location → bantam_bed →
robot1_gripper → final_red_stack / final_blue_stack / final_green_stack /
               final_red_circle / final_blue_circle / final_green_circle /
               robot1_scrap / robot2_scrap
```

`all_pieces_finished()`: True cuando initial_stack vacío Y todas las ubicaciones intermedias vacías (excluye sinks).

Cada `transfer_piece()` llama `db.insert_piece_transfer()`.

### CycleTracker

**Archivo:** `factory/cycle_tracker.py`

Mide tiempo de ciclo por pieza. `start_cycle(piece_id)` cuando xArm2 deposita en c1s1. `complete_cycle(piece_id, color, shape, route)` cuando robot1 completa el depósito final.

Proporciona `get_throughput_last_n(20)` en piezas/hora y `snapshot()` con estadísticas.

---

## 12. Configuración

### hardware_ports.yaml

Archivo principal de configuración de hardware en `src/shipyard_pnp/config/hardware_ports.yaml`.

Cada VS carga su sección correspondiente buscando primero en la ruta fuente (`../../../config/hardware_ports.yaml` relativo al VS) y luego en el share de ament.

### factory_layout.yaml

Define las ubicaciones del pipeline y las rutas por color. No se carga en runtime (es documentación de arquitectura), pero la lógica del planificador lo implementa fielmente.

### vendor_registry.yaml

Define los recursos por dominio. Referencia para entender qué gestiona cada VS.

### topic_acl.yaml

Lista blanca de tópicos permitidos por dominio (para auditoría de seguridad).

### globalvision_rois.yaml

Configuración de Regions of Interest para la cámara global. Ejemplo disponible en `globalvision_rois.example.yaml`.

---

## 13. Arranque del sistema

### Build

```bash
cd /home/isecapstone/shipyard_pnp_ws
colcon build --packages-select shipyard_pnp
source install/setup.bash
```

### Lanzar el sistema completo (hardware)

```bash
ros2 launch shipyard_pnp pnp_full_system.launch.py \
    niryo_mode:=hardware \
    ufactory_mode:=hardware \
    globalvision_camera_device:=/dev/video0 \
    globalvision_show_window:=false
```

### Lanzar en modo simulación (dry_run)

```bash
ros2 launch shipyard_pnp pnp_full_system.launch.py \
    niryo_mode:=dry_run \
    ufactory_mode:=dry_run
```

### Lanzar vendor supervisors individualmente

```bash
ros2 launch shipyard_pnp vendor_niryo.launch.py
ros2 launch shipyard_pnp vendor_ufactory.launch.py
ros2 launch shipyard_pnp vendor_globalvision.launch.py
ros2 launch shipyard_pnp vendor_green_conveyors.launch.py
```

### Diagnóstico de sensores IR (nivel raw)

```bash
ros2 run shipyard_pnp niryo_vendor_supervisor \
    --ros-args --log-level niryo_vendor_supervisor:=DEBUG
```

### Monitorizar sensores en tiempo real

```bash
ros2 topic echo /niryo_factory/status | grep SENSOR_UPDATE
```

### Enviar orden optimizada externamente

```bash
ros2 topic pub /supervisor/set_optimized_order std_msgs/msg/String \
    '{"data": "{\"order\": [\"piece-001\", \"piece-003\", \"piece-002\"]}"}'
```

---

## 14. Base de datos

### Estado actual: StubDBWriter

`factory/db_writer.py` contiene `StubDBWriter` (en uso) y `RealDBWriter` (implementado, no activado).

`StubDBWriter` loguea a DEBUG todas las transferencias y ciclos completados.

### RealDBWriter (implementado, pendiente de activar)

Requiere `psycopg2`. DSN configurada en `hardware_ports.yaml`:
```yaml
database:
  dsn: "postgresql://shipyard:password@localhost:5432/shipyard_pnp"
```

Tablas esperadas:

```sql
CREATE TABLE piece_transfers (
    piece_id TEXT,
    color TEXT,
    shape TEXT,
    from_location TEXT,
    to_location TEXT,
    transferred_at TIMESTAMPTZ,
    piece_age_sec FLOAT,
    history_json JSONB
);

CREATE TABLE cycle_records (
    piece_id TEXT,
    color TEXT,
    shape TEXT,
    route TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cycle_time_sec FLOAT
);
```

Para activar `RealDBWriter`: modificar `factory_supervisor.py` línea `self.db = db_writer.StubDBWriter()` a `self.db = db_writer.RealDBWriter(dsn)`.

---

## 15. Bugs resueltos

### Bug 1 — xArm1 no recogía la siguiente pieza de c1s2 para piezas ROJAS

**Síntoma:** xArm1 esperaba a que la pieza anterior llegara a c2s2 antes de ir a recoger la siguiente pieza roja en c1s2.

**Causa:** `processing_rules.evaluate()` comprobaba `c2s1 != FREE → return` antes de evaluar el color. Para piezas ROJAS (que van al láser, no a c2s1), esa comprobación era incorrecta.

**Fix:** La comprobación de c2s1 solo se hace para piezas no-ROJAS. Se añadió el estado `LASER_DONE_WAITING_C2S1` para el momento post-láser.

---

### Bug 2 — conveyor2 con ~22 s de retraso

**Síntoma:** Conveyor2 no arrancaba hasta ~22 s después de que robot2 recogía la pieza.

**Causa:** El código anterior limpiaba c2s2=FREE solo cuando robot2 completaba el depósito en c4, no cuando recogía de c2s2. El sensor físico tardaba ~14 s más en cambiar.

**Fix:** El flag `_c2s2_committed` permite a conveyor2 arrancar inmediatamente cuando robot2 confirma que va a recoger, sin falsificar el estado del sensor físico.

---

### Bug 3 — c1s1=OCCUPIED cuando estaba físicamente FREE (bug crítico)

**Síntoma:** xArm2 solo procesó 1 de 4 piezas. c1s1 quedaba permanentemente OCCUPIED. Timeout de 30 s en conveyor1 sin pieza.

**Causa:** Timeline de la carrera:
```
t=0:  hardware c1s1 → OCCUPIED  (pieza depositada)
t=0:  conveyor1 arranca inmediatamente
t=2:  hardware c1s1 → FREE  (pieza en c1s2)
t=3:  _on_xarm2_to_c1_complete() dispara (TARDE)
t=3:  escribía fs.state.update_sensor("c1s1", OCCUPIED)  ← stale!
t=3:  conveyor adapter _last_sensor_states["c1s1"] ya es "FREE"
      nunca re-emite la corrección
t=33: conveyor1 timeout → xArm2 bloqueado para siempre
```

**Fix:** Eliminado completamente `fs.state.update_sensor("c1s1", SensorState.OCCUPIED)` de `_on_xarm2_to_c1_complete`. El sensor IR ya se encargó (o se encargará) de reportar el estado correcto.

---

### Bug 4 — timeout de conveyor no paraba el motor físico

**Síntoma:** Al producirse un timeout en `run_until_exit_sensor()`, el motor de la cinta seguía girando físicamente.

**Fix:** Añadida llamada a `driver.control_conveyor(control_on=False)` antes de lanzar `TimeoutError`.

---

### Bug 5 — c1s1 no aparecía en el log de estado periódico

**Síntoma:** El log `[state]` mostraba c1s2, c2s1, c2s2, c4 pero no c1s1.

**Fix:** Añadido `c1s1={self.state.get_sensor('c1s1').name}` al formato del log.

---

### Bug 6 — evaluate_rules() no se disparaba en cambios de sensor

**Síntoma:** El planificador tardaba hasta 500 ms en reaccionar a cambios de sensor IR.

**Fix:** `on_status()` ahora dispara `evaluate_rules()` inmediatamente si `task_state` es terminal O si `_apply_sensor_result()` detectó un cambio de sensor (`sensor_updated=True`):
```python
trigger = terminal or sensor_updated
if trigger:
    self.evaluate_rules()
```

---

## 16. Estado actual y pendientes

### Implementado y funcional

- [x] Arquitectura Plug-and-Plan completa con 7 dominios
- [x] Protocolo Command/Ack/Status con correlación por command_id
- [x] HMAC infrastructure (warn-only, Phase 1-5)
- [x] Inicialización secuencial de dominios con retry
- [x] Rutas RED, BLUE, GREEN completamente implementadas
- [x] Sensores soberanos — c1s1/c1s2/c2s1/c2s2 solo hardware
- [x] Sensores virtuales c3/c4 escritos por lógica
- [x] Flag `_c2s2_committed` para conveyor2 sin delay
- [x] Estado `LASER_DONE_WAITING_C2S1` para xArm1 post-láser
- [x] Disparo inmediato de reglas en cambio de sensor
- [x] Log `[sensor] {id} → {STATE}` en cada cambio
- [x] Log de estado periódico cada 10 s (incluye c1s1)
- [x] Log raw de pin en DEBUG
- [x] Timeout de conveyor para el motor antes de lanzar error
- [x] PieceTracker con historial completo de ubicaciones
- [x] CycleTracker con throughput y estadísticas
- [x] StubDBWriter (log) + RealDBWriter (psycopg2, pendiente activar)
- [x] Settle time guards para c3 (10 s) y c4 (14.5 s)
- [x] Robot1 con visión local y destino por color+shape (incluye CIRCLE)
- [x] Robot2 con visión local en c2s2
- [x] Bantam CNC con puerta ZMQ y fallback a SCRAP
- [x] Conveyor3 y Conveyor4 Arduino con auto-stop por timer
- [x] GlobalVision con preview opcional
- [x] xArm2 paralelo a xArm1 (TaskRunners independientes en UFactory VS)
- [x] Robot1 paralelo a robot2 (TaskRunners independientes en Niryo VS)
- [x] Watchdog de timeouts en todos los dominios

### Pendientes / no implementado

- [ ] **RealDBWriter activado** — implementación lista, falta wiring en `factory_supervisor.py` y creación de tablas PostgreSQL
- [ ] **dashboard_node** — nodo en el launch file pero sin implementación (decisión explícita de diferir)
- [ ] **Ciclo completo de 4 piezas ROJAS verificado en hardware** — arquitectura lista, pendiente test real
- [ ] **ufactory_mode:=hardware en producción** — actualmente en dry_run para los xArms
- [ ] **LASER_DONE_WAITING_C2S1 verificado en hardware** — path nuevo, no probado en real
- [ ] **Enforcement HMAC estricto** — infraestructura lista, actualmente warn-only
- [ ] **Ruta BLUE completa con Bantam real** — Bantam simulado (25 s delay), puerta ZMQ pendiente de test
