# Shipyard PnP - memoria tecnica completa del sistema

**Fecha de referencia:** 2026-07-16  
**Workspace:** `/home/isecapstone/shipyard_pnp_ws`  
**Paquete ROS 2 principal:** `shipyard_pnp`  
**Stack:** ROS 2 Jazzy, Python 3.12, PostgreSQL, SimPy, OpenCV/YOLO, dashboards HTTP propios  

Este documento es la memoria maestra del repositorio. La idea es que una persona que nunca haya visto el testbed pueda entender:

- que hace el sistema fisico,
- como se conectan supervisor, vendors, dashboards, MES, simulacion y base de datos,
- que nodos ROS 2 existen,
- que topics se usan,
- que tablas hay en PostgreSQL,
- que archivos del repo son utiles y cual es su responsabilidad,
- donde tocar si se quiere cambiar una ruta, una pose, una prioridad, un mapa dinamico o una vista del dashboard.

No sustituye a los informes de validacion de mapas dinamicos. Es el mapa general del sistema.

---

## 1. Resumen ejecutivo

El sistema Shipyard PnP es una celula fisica de pick-and-place con piezas de tres colores:

- `RED`: pasa por conveyor1, laser, conveyor2, robot2, C4, robot1 y stack final rojo.
- `BLUE`: pasa por conveyor1, conveyor2, robot2, Bantam, C4, robot1 y stack final azul.
- `GREEN`: bypass directo por xArm2 hacia C3, luego robot1 y stack final verde.

La arquitectura es Plug-and-Plan:

- **Factory Supervisor (FS):** coordinador central. Decide que accion debe ocurrir, mantiene el estado global, mueve piezas en el modelo esperado, registra ciclos en DB y publica `/factory/system_state`.
- **Vendor Supervisors (VS):** una frontera por dominio fisico. Cada vendor recibe comandos, ejecuta hardware real o dry-run y devuelve ACK/STATUS. No decide la produccion global.
- **Adapters:** codigo interno de cada vendor que sabe hablar con el robot, maquina, Arduino, camara o driver concreto.
- **Dashboard principal:** puerto `8080`. Sirve UI operacional, optimizador de orden inicial, carga de mapa dinamico y snapshot del sistema.
- **MES dashboard:** puerto `8082`. Lee DB, telemetria, SCADA/status, work centers, historicos y analitica.
- **Simulacion y dynamic maps:** generan offline un mapa predefinido de orden y decisiones de despacho. En ejecucion real el mapa se sigue solo si las precondiciones fisicas son seguras; si no, espera un margen y cae a politica reactiva.

La frontera clave es:

```text
Factory Supervisor decide QUE hacer
Vendor Supervisor ejecuta COMO hacerlo
Adapter conoce los detalles privados del hardware
DB/MES observan, auditan y reportan
Simulacion genera mapas antes de la corrida
```

---

## 2. Arquitectura global

```text
                         operador / dashboard
                                |
                                v
                    +--------------------------+
                    |   dashboard_node :8080   |
                    | optimize / load map / UI |
                    +-------------+------------+
                                  |
                     /supervisor/set_optimized_order
                                  |
                                  v
+------------------------------------------------------------------------+
|                          factory_supervisor                            |
|                                                                        |
|  StateTracker        PieceTracker        CycleTracker        DBWriter   |
|      |                    |                   |                  |       |
|      +--------------------+-------------------+------------------+       |
|                              planner rules                             |
|       initialization / feeding / conveyors / processing /               |
|       classification / unloading / shutdown                             |
|                                                                        |
|          VendorClient x 7        map guidance        system_state       |
+----+---------+---------+---------+---------+---------+---------+--------+
     |         |         |         |         |         |         |
     v         v         v         v         v         v         v
  niryo   ufactory    laser  globalvision  green    arduino   bantam
   VS        VS        VS        VS       conveyors  vacuum      VS
                                            VS        VS
     |         |         |         |         |         |         |
  robot1   xArm1     laser     camera    conv3/4   robot1    CNC/door
  robot2   xArm2                                      vacuum
  conv1
  conv2
  local vision
```

Flujos auxiliares:

```text
/factory/system_state -> dashboard_node
/factory/system_state -> ml_node.py externo
/factory/run_id       -> dashboard_node y ml_node.py externo
vendor status topics  -> twin_bridge_node -> MuJoCo digital twin topics
joint_states/status   -> joint_telemetry_writer -> mes_pnp_v2.*_joint_telemetry
shipyard_pnp_ws DB    -> mes_analytics_worker -> mes_pnp_v2.wc_metrics_history
shipyard_pnp_ws DB    -> MES_dashboard :8082
```

---

## 3. Flujo fisico de produccion

### 3.1 Layout conceptual

```text
initial_stack
    |
    | xArm2
    |       RED/BLUE                         GREEN
    v                                       v
  C1S1 -> conveyor1 -> C1S2              C3/conveyor3
                         |                  |
                         | xArm1            | robot1
                         v                  v
        RED -> laser_bed -> C2S1       final_green_stack/circle
        BLUE/GREEN -> C2S1
                         |
                    conveyor2
                         v
                       C2S2
                         |
                      robot2
          +--------------+----------------+
          |              |                |
         RED           BLUE             mismatch/intruder
          |              |                |
         C4       Bantam / IBS           scrap
          |              |
          +------- C4 <--+
                  |
               robot1
                  |
     final_red / final_blue / scrap
```

### 3.2 Rutas por color

| Color | Ruta logica esperada |
|---|---|
| `RED` | `initial_stack -> conveyor1 -> laser_bed -> conveyor2 -> c4_location -> final_red_*` |
| `BLUE` | `initial_stack -> conveyor1 -> conveyor2 -> bantam_bed/IBS -> c4_location -> final_blue_*` |
| `GREEN` | `initial_stack -> c3_location -> final_green_*` |

El archivo que formaliza esta idea es `src/shipyard_pnp/config/factory_layout.yaml`.

### 3.3 Estaciones y sensores

| Estacion | Significado |
|---|---|
| `C1S1` | Entrada conveyor1. Deposito de xArm2 para rojas/azules. |
| `C1S2` | Salida conveyor1. Pickup de xArm1. |
| `C2S1` | Entrada conveyor2. Deposito de xArm1. |
| `C2S2` | Salida conveyor2. Pickup de robot2. |
| `C3` | Handoff para verdes. Deposito xArm2, retirada robot1. |
| `C4` | Handoff final para rojas/azules/verdes desviadas. Deposito robot2, retirada robot1. |
| `IBS` | Intermediate Blue Stack. Buffer de azules si Bantam no esta libre. |
| `Bantam` | Proceso azul. |
| `Laser` | Proceso rojo. |

Sensores fisicos Niryo:

- `c1s1`, `c1s2` en robot1/conveyor1.
- `c2s1`, `c2s2` en robot2/conveyor2.

Sensores virtuales controlados por software:

- `c3`: se marca por eventos de xArm2/conveyor3 y settle time.
- `c4`: se marca por eventos de robot2/conveyor4 y settle time.

---

## 4. Runtime ROS 2

### 4.1 Launch principal

Archivo:

- `src/shipyard_pnp/launch/pnp_full_system.launch.py`

Este launch levanta:

- driver ROS 2 de Niryo, si `niryo_mode=hardware`;
- dos drivers xArm Lite6:
  - xArm1: `192.168.0.254`, namespace `xarm1`;
  - xArm2: `192.168.0.168`, namespace `xarm2`;
- todos los vendor supervisors;
- `factory_supervisor`;
- `dashboard_node`;
- `twin_bridge_node`;
- `joint_telemetry_writer`;
- `mes_analytics_worker`;
- `mes_dashboard`.

Argumentos principales:

| Launch arg | Default | Uso |
|---|---:|---|
| `niryo_mode` | `hardware` | Modo del vendor Niryo. |
| `ufactory_mode` | `hardware` | Modo del vendor UFactory. |
| `globalvision_camera_device` | `/dev/video0` | Camara global. |
| `globalvision_show_window` | `true` | Preview OpenCV. |

Nota: `hardware_ports.yaml` tiene `ufactory.mode: dry_run`, pero el launch principal pasa `ufactory_mode=hardware` por defecto al nodo. Para saber el modo efectivo hay que mirar el launch usado en esa corrida.

### 4.2 Ejecutables ROS 2 registrados

Archivo:

- `src/shipyard_pnp/setup.py`

Console scripts:

| Ejecutable | Modulo |
|---|---|
| `factory_supervisor` | `shipyard_pnp.factory.factory_supervisor:main` |
| `dashboard_node` | `shipyard_pnp.nodes.dashboard_node:main` |
| `niryo_vendor_supervisor` | `shipyard_pnp.vendors.niryo.niryo_vendor_supervisor:main` |
| `ufactory_vendor_supervisor` | `shipyard_pnp.vendors.ufactory.ufactory_vendor_supervisor:main` |
| `ufactory_parallel_test` | `shipyard_pnp.vendors.ufactory.ufactory_parallel_test:main` |
| `laser_vendor_supervisor` | `shipyard_pnp.vendors.laser.laser_vendor_supervisor:main` |
| `globalvision_vendor_supervisor` | `shipyard_pnp.vendors.globalvision.globalvision_vendor_supervisor:main` |
| `globalvision_preview` | `shipyard_pnp.vendors.globalvision.globalvision_preview:main` |
| `green_conveyors_vendor_supervisor` | `shipyard_pnp.vendors.green_conveyors.green_conveyors_vendor_supervisor:main` |
| `arduino_vacuum_vendor_supervisor` | `shipyard_pnp.vendors.arduino_vacuum.arduino_vacuum_vendor_supervisor:main` |
| `bantam_vendor_supervisor` | `shipyard_pnp.vendors.bantam.bantam_vendor_supervisor:main` |
| `twin_bridge_node` | `shipyard_pnp.nodes.twin_bridge_node:main` |
| `mes_dashboard` | `shipyard_pnp.nodes.MES_dashboard:main` |
| `mes_analytics_worker` | `shipyard_pnp.nodes.mes_analytics_worker:main` |
| `joint_telemetry_writer` | `shipyard_pnp.nodes.joint_telemetry_writer:main` |
| `mock_vendor_supervisor` | `shipyard_pnp.vendors.common.mock_vendor_supervisor:main` |

---

## 5. Contratos, dominios y topics

### 5.1 Dominios vendor

Archivo:

- `src/shipyard_pnp/shipyard_pnp/shared/contracts.py`
- `src/shipyard_pnp/config/vendor_registry.yaml`

Dominios:

| Domain | Recursos |
|---|---|
| `niryo` | `robot1`, `robot2`, `conveyor1`, `conveyor2`, `vision_robot1`, `vision_robot2`, `robot2_niryo_vacuum` |
| `ufactory` | `xarm1`, `xarm2` |
| `laser` | `laser` |
| `globalvision` | `globalvision_camera` |
| `green_conveyors` | `conveyor3`, `conveyor4` |
| `arduino_vacuum` | `arduino_vacuum` |
| `bantam` | `bantam`, `bantam_door` |

### 5.2 Topics command / ack / status

Cada dominio tiene exactamente tres topics norte-sur:

| Domain | Command | ACK | Status |
|---|---|---|---|
| `niryo` | `/niryo_factory/command` | `/niryo_factory/ack` | `/niryo_factory/status` |
| `ufactory` | `/ufactory_factory/command` | `/ufactory_factory/ack` | `/ufactory_factory/status` |
| `laser` | `/laser_factory/command` | `/laser_factory/ack` | `/laser_factory/status` |
| `globalvision` | `/globalvision_factory/command` | `/globalvision_factory/ack` | `/globalvision_factory/status` |
| `green_conveyors` | `/green_conveyors_factory/command` | `/green_conveyors_factory/ack` | `/green_conveyors_factory/status` |
| `arduino_vacuum` | `/arduino_vacuum_factory/command` | `/arduino_vacuum_factory/ack` | `/arduino_vacuum_factory/status` |
| `bantam` | `/bantam_factory/command` | `/bantam_factory/ack` | `/bantam_factory/status` |

Topics globales:

| Topic | Publica | Suscribe | Uso |
|---|---|---|---|
| `/factory/system_state` | `factory_supervisor` | `dashboard_node`, `ml_node.py` externo | Snapshot vivo del sistema. |
| `/factory/run_id` | `factory_supervisor` | `dashboard_node`, `ml_node.py` externo | Run actual para persistencia y correlacion. |
| `/supervisor/set_optimized_order` | `dashboard_node` | `factory_supervisor` | Aplicar orden optimizado o mapa dinamico. |
| `/shipyard/acl_events` | FS y VS | observadores/debug | Eventos de ACL/HMAC/proprietary boundary. |
| `stack_status` | `ml_node.py` externo | `factory_supervisor` | Estado real del stack inicial por slot, color y shape. |

Topics del digital twin publicados por `twin_bridge_node`:

| Topic | Tipo | Valor |
|---|---|---|
| `/xarm1/vacuum_state` | `std_msgs/String` | `ON` / `OFF` |
| `/xarm2/vacuum_state` | `std_msgs/String` | `ON` / `OFF` |
| `/robot1/vacuum_state` | `std_msgs/String` | `ON` / `OFF` |
| `/robot2/vacuum_state` | `std_msgs/String` | `ON` / `OFF` |
| `/factory/conveyor_1/status` | `std_msgs/String` | `RUNNING` / `STOPPED` |
| `/factory/conveyor_2/status` | `std_msgs/String` | `RUNNING` / `STOPPED` |
| `/factory/conveyor_small/status` | `std_msgs/String` | `RUNNING` / `STOPPED` |
| `/bantam/door_state` | `std_msgs/String` | `OPEN`, `CLOSED`, `MOVING_TO_OPEN`, `MOVING_TO_CLOSED` |
| `/laser/status` | `std_msgs/String` | `IDLE`, `WORKING`, `FINISHED` |

Topics de telemetria articular leidos por `joint_telemetry_writer`:

| Robot | Topic |
|---|---|
| `robot1` | `/robot1/joint_states` |
| `robot2` | `/robot2/joint_states` |
| `xarm1` | `/xarm1/joint_states` |
| `xarm2` | `/xarm2/joint_states` |

### 5.3 Estructura de mensajes

Archivos:

- `src/shipyard_pnp/shipyard_pnp/shared/messages.py`
- `src/shipyard_pnp/shipyard_pnp/shared/time_ids.py`
- `src/shipyard_pnp/shipyard_pnp/shared/acl_guard.py`

Un comando incluye:

```json
{
  "command_id": "CMD-niryo-robot2-...",
  "domain_id": "niryo",
  "resource_id": "robot2",
  "task": "CLASSIFY_C2S2_TO_BANTAM",
  "piece_id": "piece-004",
  "source": "C2S2",
  "target": "BANTAM",
  "route": "BLUE",
  "parameters": {},
  "correlation_id": "...",
  "issued_at": "...",
  "nonce": "...",
  "auth": "..."
}
```

El ACK confirma recepcion/aceptacion. El STATUS informa progreso y terminalidad:

- `RECEIVED`
- `RUNNING`
- `COMPLETED`
- `FAILED`
- `REJECTED`
- `TIMEOUT`
- `CANCELED`

Estados principales:

| Tipo | Estados |
|---|---|
| Robot | `NOT_INITIALIZED`, `INITIALIZING`, `IDLE`, `GOING_TO_POSITION`, `WAITING_FOR_VISION`, `PICKING`, `PICK_DONE`, `PLACING`, `PLACE_DONE`, `AT_PICK_POSITION`, `AT_PLACE_POSITION`, `RETURNING_HOME`, `ERROR` |
| Conveyor | `STOPPED`, `RUNNING`, `ERROR` |
| Sensor | `FREE`, `OCCUPIED`, `ERROR`, `UNKNOWN` |
| Vision | `IDLE`, `SCANNING`, `PROCESSING`, `RESULT_READY`, `ERROR` |
| Vacuum | `IDLE`, `PICKING`, `PICK_DONE`, `RELEASING`, `RELEASE_DONE`, `ERROR` |
| Machine | `NOT_INITIALIZED`, `IDLE`, `PREPARING`, `WORKING`, `FINISHED`, `WAITING_PICKUP`, `ERROR` |
| Planner | `BOOT`, `INITIALIZING`, `WAITING_FOR_ORDER`, `RUNNING`, `SHUTTING_DOWN`, `STOPPED` |

### 5.4 ACL y frontera propietaria

`acl_guard.py` y `messages.py` implementan comprobaciones para que no crucen datos internos de vendor. Se rechazan o reportan claves como:

- `joint`
- `joint_states`
- `angle`
- `servo`
- `register`
- `gpio`
- `pin`
- `raw_image`
- `image`
- `frame`
- `hsv`
- `mask`
- `contour`
- `roi_pixels`
- `gcode_line`
- `serial_bytes`
- `tool_torque`
- `motor_current`

Principio:

- Permitido cruzar: resultado de coordinacion, por ejemplo `color`, `shape`, `slot_id`, `resource_state`, `task_state`.
- No permitido cruzar: datos privados de implementacion, imagen cruda, thresholds, joints directos o comandos servo.

---

## 6. Factory Supervisor

Archivo principal:

- `src/shipyard_pnp/shipyard_pnp/factory/factory_supervisor.py`

Responsabilidades:

- crear `StateTracker`, `PieceTracker`, `CycleTracker` y `RealDBWriter`;
- publicar comandos a todos los vendors;
- recibir ACK/STATUS;
- mantener correlacion de comandos pendientes;
- aplicar reglas de planner;
- publicar `/factory/system_state`;
- publicar `/factory/run_id`;
- recibir orden optimizado o mapa dinamico desde dashboard;
- recibir `stack_status` desde el nodo de vision externo;
- registrar eventos/ciclos/estado en PostgreSQL;
- proteger la ejecucion de mapas con precondiciones fisicas y timeout.

### 6.1 Timers

| Periodo | Metodo | Uso |
|---:|---|---|
| `0.5 s` | `evaluate_rules` | Ejecuta planner. |
| `1.0 s` | `watchdog` | Timeouts de comandos. |
| `0.5 s` | `_publish_system_state` | Snapshot UI/MES/vision. |
| `5.0 s` | `_publish_run_id` | Run ID latched. |
| `10.0 s` | `_sample_queue_depths` | Muestras de colas para DB. |

### 6.2 Callback groups

| Grupo | Tipo | Uso |
|---|---|---|
| `ack_status_cbg` | `ReentrantCallbackGroup` | ACK y STATUS de vendors. |
| `planner_cbg` | `MutuallyExclusiveCallbackGroup` | Evaluacion del planner. |
| `watchdog_cbg` | `MutuallyExclusiveCallbackGroup` | Timeout watchdog. |
| `dashboard_cbg` | `MutuallyExclusiveCallbackGroup` | System state y run id. |
| `order_cbg` | `MutuallyExclusiveCallbackGroup` | Orden optimizado/mapa desde dashboard. |

El supervisor usa `threading.RLock` para proteger estado compartido.

### 6.3 Estado interno importante

| Variable | Significado |
|---|---|
| `planner_phase` | Fase global del sistema. |
| `_feeding_state` | Estado local del modulo de alimentacion xArm2. |
| `_processing_state` | Estado local xArm1/laser. |
| `_classification_state` | Estado local robot2/Bantam/IBS/C4. |
| `_unloading_state` | Estado local robot1/C3/C4. |
| `_shutdown_state` | Estado de apagado. |
| `_pending_laser_piece_id` | Pieza que esta asociada al laser. |
| `_pending_bantam_piece` | Pieza que esta asociada a Bantam. |
| `_c3_deposit_time` | Timestamp de ultimo deposito en C3. |
| `_c4_deposit_time` | Timestamp de ultimo deposito en C4. |
| `c3_settle_sec` | Espera antes de permitir retirada de C3. Actualmente `10.0`. |
| `c4_settle_sec` | Espera antes de permitir retirada de C4. Actualmente `14.5`. |
| `_stack_status` | Slot -> color/shape leido por `ml_node.py`. |
| `_stack_status_fresh_since_idle` | Evita usar shape viejo de un slot recargado. |
| `_inflight_pick_source` | Source real que se vacia al `PICK_DONE`. |
| `_inflight_place_target` | Target real que se llena al `PLACE_DONE`. |
| `_place_done_via_hook` | Evita doble transferencia en PieceTracker. |

### 6.4 Orden inicial actual

En `factory_supervisor.py`, `INITIAL_STACK_ORDER` es la lista que xArm2 usa como pedido inicial. En el estado leido para esta memoria esta configurada para una prueba corta:

```python
["RED", "RED"]
```

Esto se cambia a menudo para pruebas fisicas. No debe interpretarse como configuracion permanente de producto.

### 6.5 VendorClient

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/vendor_client.py`

`VendorClient` encapsula:

- publisher ROS 2 del dominio;
- envio JSON firmado;
- pending commands por `command_id`;
- pending commands por `resource_id` si el dominio permite concurrencia;
- ACK timeout default `5 s`;
- STATUS timeout default `120 s`;
- overrides por task:
  - `INITIALIZE_DOMAIN`: `30 s`
  - `SCAN_STACK`: `15 s`
  - `LOCATE_NEXT_PIECE`: `10 s`
  - `GOTO_PICK_POSITION`: `60 s`
  - `LIFT_AND_PLACE`: `60 s`
  - `RETURN_HOME`: `60 s`
  - `RUN_NIRYO_CONVEYOR`: `30 s`
  - `PICK`: `5 s`
  - `RELEASE`: `5 s`

La regla practica: el planner no debe mandar un comando si `VendorClient.is_busy(...)` indica que ese recurso/dominio ya tiene trabajo pendiente.

### 6.6 System state

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/system_state_publisher.py`

Publica un JSON con schema:

```text
shipyard.pnp.system_state.v1
```

Incluye:

- `published_at`
- `planner_phase`
- `initial_order`
- `domains`
- `resources`
- `pipeline`
- `cycles`
- `stack_status`

Este topic es la fuente principal para el dashboard operacional y para el proceso de vision externo `ml_node.py`.

---

## 7. Trackers internos

### 7.1 StateTracker

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/state_tracker.py`

Mantiene estado grueso de:

- robots: `robot1`, `robot2`, `xarm1`, `xarm2`;
- conveyors: `conveyor1`, `conveyor2`, `conveyor3`, `conveyor4`;
- sensors: `c1s1`, `c1s2`, `c2s1`, `c2s2`, `c3`, `c4`;
- machines: `laser`, `bantam`;
- vacuum: `arduino_vacuum`;
- vision: `vision_robot1`, `vision_robot2`, `globalvision_camera`;
- online status de dominios.

No decide rutas. Solo mantiene estado observable.

### 7.2 PieceTracker

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/piece_tracker.py`

Es la fuente de verdad esperada para donde esta cada pieza. Localizaciones:

```text
initial_stack
xarm2_gripper
c3_location
conveyor1
xarm1_gripper
laser_bed
conveyor2
robot2_gripper
c4_location
bantam_bed
intermediate_blue_stack
robot1_gripper
final_red_stack
final_blue_stack
final_green_stack
final_red_circle
final_blue_circle
final_green_circle
robot1_scrap
robot2_scrap
```

Funciones conceptuales:

- crear piezas desde `INITIAL_STACK_ORDER`;
- reordenar por resultado de optimizador;
- mover pieza por gripper;
- mover pieza directo;
- asignar color/shape/slot;
- registrar intrusos;
- publicar snapshot de pipeline.

Un detalle critico: el FS mueve una pieza fuera de la cola origen en el instante `PICK_DONE` real, no al final del comando. Esto evita que el modelo esperado arrastre piezas equivocadas si el robot vuelve a home dentro del mismo comando.

### 7.3 CycleTracker

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/cycle_tracker.py`

Registra ciclos por entidad:

- `xarm2`
- `xarm1`
- `laser`
- `robot2`
- `bantam`
- `robot1`

Cada ciclo puede tener fases. Por ejemplo, un ciclo de robot1 puede incluir:

- vision/pick;
- vacuum pick;
- lift/place;
- vacuum release;
- return home.

La tabla final en DB es `shipyard_pnp_ws.cycle_event`.

---

## 8. Planner

Los modulos de planner viven en:

- `src/shipyard_pnp/shipyard_pnp/factory/planner/`

Regla general:

```text
las precondiciones fisicas siempre mandan primero
el mapa dinamico solo decide entre acciones fisicamente validas o permite esperar un margen acotado
si el margen expira, fallback reactivo seguro
```

### 8.1 `initialization_rules.py`

Arranca dominios y recursos. Secuencia conceptual:

1. Espera a que los subscribers de vendors esten descubiertos.
2. Inicializa dominios.
3. Pasa de `BOOT`/`INITIALIZING` a `WAITING_FOR_ORDER` o `RUNNING`.

Evita mandar comandos antes de que exista un subscriber real en el topic command del dominio.

### 8.2 `feeding_rules.py`

Controla xArm2 y global vision para alimentar piezas del `initial_stack`.

Rutas:

- `RED` y `BLUE`: xArm2 mueve de `INITIAL_STACK` a `C1S1`.
- `GREEN`: xArm2 mueve de `INITIAL_STACK` a `C3`.

Condiciones importantes:

- xArm2 debe estar `IDLE`;
- globalvision debe estar libre;
- `stack_status` debe estar fresco desde que xArm2 esta idle;
- para rojas/azules, C1S1/conveyor1 no debe estar bloqueado;
- para verdes, C3 debe estar disponible y luego se arranca conveyor3 con auto-stop.

La forma/shape viene de `stack_status` externo cuando existe. La camara global propia detecta color/slot, pero la shape real se superpone desde `ml_node.py`.

### 8.3 `conveyor_rules.py`

Controla conveyors:

- conveyor1: C1S1 -> C1S2.
- conveyor2: C2S1 -> C2S2.
- conveyor3/conveyor4: conveyors Arduino sin sensor de salida fisico, controlados por eventos y auto-stop.

Niryo conveyors paran por IR de salida. Los green conveyors se paran por temporizador porque no tienen el mismo modelo de sensores.

### 8.4 `processing_rules.py`

Controla xArm1 y laser.

Rutas:

- `RED` en C1S2:
  1. xArm1 `C1S2_TO_LASER`
  2. laser `PROCESS_RED`
  3. xArm1 `LASER_TO_C2S1`
- `BLUE` o `GREEN` en C1S2:
  1. xArm1 `C1S2_TO_C2S1`

Conflicto principal:

- si hay pieza lista en C1S2 y laser terminado a la vez, la politica fija tiende a retirar laser primero;
- con mapa dinamico, el expected schedule puede guiar otra decision o permitir espera controlada.

### 8.5 `classification_rules.py`

Controla robot2, Bantam, IBS y C4.

Acciones relevantes:

- `CLASSIFY_C2S2_TO_C4`
- `CLASSIFY_C2S2_TO_BANTAM`
- `CLASSIFY_C2S2_TO_IBS`
- `CLASSIFY_C2S2_TO_SCRAP`
- `IBS_TO_BANTAM`
- `BANTAM_TO_C4`

Puntos de decision:

- `P1`: clasificar pieza en C2S2.
- `P2`: descargar Bantam terminado a C4.
- `P3`: drenar IBS hacia Bantam.

La politica fija original era razonable pero rigida. El mapa dinamico permite que la misma situacion local pueda resolverse de forma distinta segun el futuro previsto de la corrida.

Ejemplo conceptual:

```text
C2S2 tiene pieza roja
Bantam tiene pieza azul terminada
C4 esta libre

Politica fija: puede priorizar siempre C2S2.
Mapa dinamico: puede decidir descargar Bantam primero si reduce makespan global.
```

### 8.6 `unloading_rules.py`

Controla robot1 para descargar C3 y C4.

Acciones:

- `UNLOAD_C3`
- `UNLOAD_C4`

Secuencia robot1/vacuum:

1. `niryo/robot1`: `GOTO_PICK_POSITION`
2. `arduino_vacuum`: `PICK`
3. `niryo/robot1`: `LIFT_AND_PLACE`
4. `arduino_vacuum`: `RELEASE`
5. `niryo/robot1`: `RETURN_HOME`

La politica reactiva compara timestamps de disponibilidad de C3/C4 y suele retirar la que lleva mas tiempo esperando. El mapa dinamico puede elegir C3, C4 o esperar dentro del margen si eso coincide con el schedule esperado.

### 8.7 `shutdown_rules.py`

Apagado ordenado. Para conveyors:

- stop conveyor1;
- stop conveyor2;
- stop conveyor3;
- stop conveyor4;

El objetivo es dejar actuadores en estado seguro cuando el run termina o entra en shutdown.

### 8.8 Matriz de condiciones fisicas para disparar acciones

Esta es una de las secciones mas importantes del sistema. El mapa dinamico, el optimizador o cualquier politica superior **no pueden saltarse estas condiciones**. Una accion solo se dispara si el estado fisico observado permite ejecutarla con seguridad.

Regla general:

```text
mapa / politica / optimizador propone intencion
        |
        v
planner comprueba condiciones fisicas reales
        |
        +-- si son verdaderas: send_command(...)
        |
        +-- si no son verdaderas pero el mapa esperaba esa accion:
        |       esperar hasta MAP_GRACE_SEC
        |
        +-- si expira o hay desviacion:
                fallback reactivo seguro
```

#### xArm2 - alimentacion desde stack inicial

| Accion | Condiciones necesarias antes de disparar |
|---|---|
| `globalvision/LOCATE_NEXT_PIECE` | `_feeding_state == IDLE`; hay piezas en `initial_stack`; `xarm2 == IDLE`; `globalvision` no busy; `ufactory/xarm2` no busy; `stack_status_is_fresh() == True`; si la siguiente esperada es `GREEN`, `c3 == FREE`; si no, `c1s1 == FREE`. |
| `xarm2 MOVE_PIECE INITIAL_STACK -> C1S1` | `LOCATE_NEXT_PIECE` termino `COMPLETED`; existe `slot_id`; la vision confirma color distinto de `GREEN`; la entrada `c1s1` habia sido validada como `FREE` antes de vision; se registra `pick_source=initial_stack` y `place_target=conveyor1`. |
| `xarm2 MOVE_PIECE INITIAL_STACK -> C3` | `LOCATE_NEXT_PIECE` termino `COMPLETED`; existe `slot_id`; la vision confirma `GREEN`; se revalida `c3 == FREE` despues de vision; se registra `pick_source=initial_stack` y `place_target=c3_location`. |
| `conveyor3 RUN_CONVEYOR` | Solo despues de `PLACE_DONE` en C3; `c3` pasa a `OCCUPIED`; se guarda `_c3_deposit_time`; se programa `STOP_CONVEYOR` tras `c3_settle_sec`. |
| `xarm2 MOVE_XARM_HOME` tras verde | Solo despues de colocar en C3 y arrancar conveyor3. La pieza ya esta depositada; el home es parte del ciclo de feed verde. |

Detalle fino: para C3 el codigo revalida `c3` despues de vision porque entre la primera decision y el resultado de camara puede haber cambiado la realidad. Para C1S1 actualmente la validacion fuerte ocurre antes de vision, porque C1S1 es el unico destino posible de no-verdes en esa rama.

#### Conveyor1 y Conveyor2

| Accion | Condiciones necesarias antes de disparar |
|---|---|
| `conveyor1 RUN_NIRYO_CONVEYOR` | `niryo/conveyor1` no busy; `c1s1 == OCCUPIED`; `conveyor1 == STOPPED`; `c1s2 == FREE`. |
| `conveyor2 RUN_NIRYO_CONVEYOR` | `niryo/conveyor2` no busy; `c2s1 == OCCUPIED`; `conveyor2 == STOPPED`; `c2s2 == FREE`. |

Importante: conveyor2 exige `c2s2 == FREE` fisicamente. No basta con que robot2 haya fotografiado la pieza; la pieza sigue en C2S2 hasta que robot2 la recoge con `MOVE_PIECE`.

#### xArm1 - C1S2, laser y C2S1

Primero se exige:

```text
xarm1 == IDLE
ufactory/xarm1 no busy
```

Luego se calculan dos posibles readiness:

```python
retrieve_ready =
    laser == FINISHED
    and c2s1 == FREE

c1s2_ready =
    PieceTracker tiene pieza en conveyor1
    and c1s2 == OCCUPIED
```

| Accion | Condiciones necesarias antes de disparar |
|---|---|
| `xarm1 MOVE_PIECE C1S2 -> C2S1` | `c1s2_ready`; pieza esperada en `conveyor1`; color distinto de `RED`; `c2s1 == FREE`; mapa no esta dentro de una espera prioritaria por `LASER_TO_C2S1`. |
| `xarm1 MOVE_PIECE C1S2 -> LASER_BED` | `c1s2_ready`; pieza esperada color `RED`; `laser == IDLE`; mapa no esta dentro de una espera prioritaria por otra accion lista. |
| `laser RUN_JOB PROCESS_RED` | Se dispara solo despues de que xArm1 haya colocado la pieza en `laser_bed`; el ciclo xArm1 `C1S2_TO_LASER` termino `COMPLETED`; el estado del laser pasa a `PREPARING/WORKING`. |
| `xarm1 MOVE_PIECE LASER_BED -> C2S1` | `retrieve_ready`; `laser == FINISHED`; `c2s1 == FREE`; `xarm1 == IDLE`; `ufactory/xarm1` no busy. |

Si `retrieve_ready` y `c1s2_ready` son verdaderos a la vez, el mapa puede decidir. Si el mapa no tiene opinion, la regla reactiva favorece retirar laser terminado. Si solo una accion esta lista pero el mapa esperaba la otra, xArm1 puede esperar hasta `MAP_GRACE_SEC`; no actua hasta que la otra accion sea fisicamente posible.

#### Robot2 - C2S2, Bantam, IBS, C4 y scrap

Primero se exige:

```text
_classification_state no esta en _ROBOT2_BUSY_STATES
robot2 == IDLE
niryo/robot2 no busy
```

Readiness principales:

```python
classify_ready =
    c2s2 == OCCUPIED
    and c4 == FREE

bantam_ready =
    _pending_bantam_piece is not None
    and c4 == FREE
```

| Accion | Condiciones necesarias antes de disparar |
|---|---|
| `robot2 CAPTURE_LOCAL_VISION C2S2` | `classify_ready`; es decir, C2S2 fisicamente ocupado y C4 libre; robot2 libre. Si `PieceTracker` no tiene pieza en `conveyor2`, se registra un `intruder-*` para poder inspeccionarlo y retirarlo. |
| `robot2 MOVE_PIECE C2S2 -> C4` | Vision local termino `COMPLETED`; ruta resuelta `C4` para `RED` o `GREEN`; C4 habia sido validado `FREE` antes de iniciar vision; se registra `pick_source=conveyor2`, `place_target=c4_location`. |
| `robot2 MOVE_PIECE C2S2 -> BANTAM_BED` | Vision local termino `COMPLETED`; color `BLUE`; `bantam == IDLE`; `bantam` vendor no busy en el momento de decidir ruta; robot2 toma pieza de C2S2 y la deja en Bantam. |
| `robot2 MOVE_PIECE C2S2 -> IBS_BED` | Vision local termino `COMPLETED`; color `BLUE`; Bantam no esta disponible; robot2 toma pieza de C2S2 y la aparca en `intermediate_blue_stack`. |
| `robot2 MOVE_PIECE C2S2 -> SCRAP` | Vision local detecta `UNKNOWN`, intruso registrado o mismatch de color respecto a lo esperado; se fuerza ruta `SCRAP`; no se permite que un intruso consuma una entrada normal del mapa. |
| `bantam RUN_JOB PROCESS_BLUE` | Se dispara solo despues de que robot2 haya colocado una pieza azul en `bantam_bed`; Bantam pasa a `PREPARING/WORKING`; al terminar se setea `_pending_bantam_piece`. |
| `robot2 MOVE_PIECE IBS_BED -> BANTAM_BED` | `_classification_state == IDLE`; hay piezas en `intermediate_blue_stack`; `bantam == IDLE`; `bantam` vendor no busy; robot2 libre. |
| `robot2 MOVE_PIECE BANTAM_BED -> C4` | `bantam_ready`; `_pending_bantam_piece` existe; `c4 == FREE`; robot2 libre; no exige que `conveyor2` este vacio porque fisicamente esta accion no toca C2S2. |
| `conveyor4 RUN_CONVEYOR` | Solo despues de `PLACE_DONE` en C4; `c4` pasa a `OCCUPIED`; se guarda `_c4_deposit_time`; se programa `STOP_CONVEYOR` tras `c4_settle_sec`. |

Detalle fino muy importante:

- `classify_ready` no exige `PieceTracker.count("conveyor2") > 0`. Si hay un objeto fisico en C2S2 no rastreado, robot2 debe poder inspeccionarlo y limpiarlo como intruso.
- `bantam_ready` no exige `PieceTracker.count("conveyor2") == 0`. Descargar Bantam a C4 no toca el conveyor2.
- El codigo actual exige `c4 == FREE` antes de iniciar vision de C2S2, incluso si luego la pieza resulta azul y va a Bantam/IBS. Es una puerta conservadora porque antes de vision no se conoce la ruta real.

#### Robot1 - descarga final desde C3/C4

Primero se exige:

```text
_unloading_state == IDLE
robot1 == IDLE
niryo/robot1 no busy
arduino_vacuum no busy
```

Readiness:

```python
c4_ready =
    c4 == OCCUPIED
    and now >= _c4_deposit_time + c4_settle_sec

c3_ready =
    c3 == OCCUPIED
    and now >= _c3_deposit_time + c3_settle_sec
```

| Accion | Condiciones necesarias antes de disparar |
|---|---|
| `robot1 CLASSIFY_AND_PICK C4` | `c4_ready`; existe pieza esperada en `c4_location`; robot1 libre; vacuum libre; mapa no esta esperando C3, o espera agotada, o mapa espera C4. |
| `robot1 CLASSIFY_AND_PICK C3` | `c3_ready`; existe pieza esperada en `c3_location`; robot1 libre; vacuum libre; mapa no esta esperando C4, o espera agotada, o mapa espera C3. |
| `arduino_vacuum PICK` | `CLASSIFY_AND_PICK` termino `COMPLETED`; robot1 esta en posicion de pick con pieza; entonces se activa vacuum. |
| `robot1 LIFT_AND_PLACE` | `arduino_vacuum PICK` termino `COMPLETED`; la pieza se transfiere en `PieceTracker` desde `c3_location/c4_location` a `robot1_gripper`; el sensor C3/C4 se marca `FREE`. |
| `arduino_vacuum RELEASE` | `LIFT_AND_PLACE` termino `COMPLETED`; robot1 esta en destino final. |
| `robot1 RETURN_HOME` | `RELEASE` termino `COMPLETED`; la pieza se transfiere desde `robot1_gripper` al destino final; luego se manda home. |

Si C3 y C4 estan listas a la vez:

- si el mapa espera una de ellas y esta fisicamente lista, se ejecuta esa;
- si el mapa no tiene opinion, se elige la que termino/settled antes;
- si solo una esta lista pero el mapa esperaba la otra, robot1 espera hasta `MAP_GRACE_SEC`;
- si no aparece a tiempo, descarga la lista por fallback.

#### Maquinas y vendors

| Accion | Condiciones necesarias |
|---|---|
| `INITIALIZE_DOMAIN` | El command subscriber del dominio existe (`command_subscriber_count >= 1`); el vendor no esta busy; se inicializa en orden `arduino_vacuum -> green_conveyors -> globalvision -> ufactory -> niryo -> laser -> bantam`. |
| `laser RUN_JOB` | Pieza roja ya colocada en `laser_bed`; comando anterior de xArm1 termino `COMPLETED`; laser no debe estar busy por `VendorClient`. |
| `bantam RUN_JOB` | Pieza azul ya colocada en `bantam_bed`; robot2 termino su place; Bantam no busy. |
| `green_conveyors STOP_CONVEYOR` | Se programa despues de `RUN_CONVEYOR`; si el Arduino compartido esta busy, se reintenta con backoff para no dejar conveyor3/4 corriendo. |

#### Que puede y que no puede hacer el mapa dinamico

| Caso | Puede el mapa forzarlo? | Comportamiento |
|---|---:|---|
| C4 lleno y mapa pide `BANTAM_TO_C4` | No | Robot2 espera si aplica; si no se libera a tiempo, fallback. |
| Bantam no termino y mapa pide `BANTAM_TO_C4` | No | Espera hasta `MAP_GRACE_SEC`; luego clasifica C2S2 si esta listo. |
| C3 no settled y mapa pide `UNLOAD_C3` | No | Robot1 espera; no recoge hasta que `now >= deposit_time + settle`. |
| C2S2 ocupado por intruso | No fuerza ruta normal | Robot2 registra intruso, inspecciona y manda scrap si corresponde. |
| `stack_status` no fresco tras xArm2 idle | No | xArm2 no alimenta siguiente pieza hasta recibir snapshot fresco. |
| Vendor/recurso busy | No | `send_command` levanta busy error si una regla intenta mandar; las reglas deben esperar. |
| Sensor contradice el mapa | No | Sensor manda; mapa queda pendiente o se registra timeout/intruder. |

En resumen: **el mapa decide prioridades, no elimina interlocks fisicos**.

---

## 9. Dynamic maps y simulacion

### 9.1 Idea central

El mapa dinamico no es IA controlando robots en vivo. Es:

```text
simulacion offline antes de Confirm & Apply
    -> orden inicial optimizado
    -> expected_schedule con decisiones de despacho
    -> mapa congelado para esa composicion
    -> ejecucion real protegida por sensores y timeouts
```

Si la accion prevista no es fisicamente posible:

1. el robot espera hasta `MAP_GRACE_SEC`;
2. si aparece la condicion esperada, sigue el mapa;
3. si no aparece, vuelve a la politica reactiva segura.

En `factory_supervisor.py`:

- `map_guidance_enabled`: parametro booleano;
- `MAP_GRACE_SEC`: actualmente `15.0`;
- `_expected_schedule`: mapa/ciclos esperados;
- `_map_pointer`: indice por entidad;
- `_map_wait_since`: inicio de espera controlada;
- `_map_last_dispatch_info`: metadata que luego aparece en ciclos.

### 9.2 Archivos de simulacion

| Archivo | Uso |
|---|---|
| `src/shipyard_pnp/shipyard_pnp/nodes/shipyard_sim.py` | Simulacion SimPy base de la celula. |
| `src/shipyard_pnp/shipyard_pnp/nodes/shipyard_sim_search.py` | Simulacion orientada a busqueda de ordenes. |
| `src/shipyard_pnp/shipyard_pnp/nodes/dispatch_search2.py` | Simulador de despacho con decisiones alternativas. |
| `src/shipyard_pnp/shipyard_pnp/nodes/beam_search.py` | Beam search / rollouts para mapas dinamicos. |
| `src/shipyard_pnp/shipyard_pnp/factory/expected_schedule.py` | Convierte simulacion/mapa en schedule esperado por entidad. |
| `src/shipyard_pnp/shipyard_pnp/factory/dynamic_schedule.py` | Carga mapas JSON por composicion para dashboard/supervisor. |

### 9.3 Generacion offline

Script:

- `scripts/generate_dynamic_map.py`

Proceso:

1. Recibe una composicion u orden, por ejemplo `BRGBRGBRG`.
2. Cuenta piezas `BLUE`, `RED`, `GREEN`.
3. Stage 1: simula ordenes con prioridad fija:
   - exhaustivo si el espacio es pequeno;
   - muestreo directo si supera `--sample-cap`.
4. Stage 2: ejecuta `beam_search` sobre los `--top-k` mejores candidatos.
5. Replay del mejor path para obtener `expected_schedule`.
6. Guarda JSON atomico en:

```text
src/shipyard_pnp/config/dynamic_maps/{n_blue}b{n_red}r{n_green}g.json
```

Campos del JSON:

- `map_id`
- `composition`
- `requested_order`
- `best_order`
- `best_time_s`
- `fixed_reference_order`
- `fixed_reference_time_s`
- `saving_s`
- `decision_path`
- `expected_schedule`
- `search_stats`
- `config_hash`
- `generated_at`

### 9.4 Registro distribuido de mapas

Script:

- `scripts/dynamic_map_registry.py`

Tabla:

- `shipyard_pnp_ws.dynamic_map_registry`

Estados:

- `PENDING`
- `IN_PROGRESS`
- `COMPLETED`
- `VALIDATED`

Uso:

- coordinar varios ordenadores generando mapas;
- evitar duplicar composiciones;
- sincronizar mapas locales y docs de validacion;
- marcar mapas validados en hardware.

### 9.5 Batches overnight

Scripts:

- `scripts/run_overnight_dynamic_maps.sh`
- `scripts/run_overnight_dynamic_maps_12to15pc.sh`
- `scripts/run_overnight_dynamic_maps_15pc.sh`
- `scripts/run_overnight_dynamic_maps_18pc.sh`
- `scripts/run_parallel_dynamic_maps_12to15pc.sh`
- `scripts/run_5lane_dynamic_maps_50comp.sh`

Estos scripts estan pensados para dejar busquedas largas corriendo, con logs en:

```text
results/dynamic_map_generation_logs/
```

### 9.6 Dataset actual

Directorio de mapas:

- `src/shipyard_pnp/config/dynamic_maps/`

En la inspeccion actual hay decenas de mapas JSON, incluyendo composiciones validadas como:

- `3b3r3g.json`
- `4b4r3g.json`
- `4b5r0g.json`
- `5b4r0g.json`
- `5b5r2g.json`
- `5b5r5g.json`
- `6b6r6g.json`
- `2b2r6g.json`

Documento historico:

- `README_DYNAMIC_MAP_HISTORY.md`

Resumen del estado documentado ahi:

- 8 composiciones validadas fisicamente;
- mejoras reales en casos congestionados de aproximadamente `12.0%` a `18.3%`;
- caso control `2B/2R/6G` sin mejora significativa, dentro del ruido fisico;
- dataset simulado de 87 composiciones segun la tabla historica.

---

## 10. Vendors y adapters

### 10.1 Base comun

Directorio:

- `src/shipyard_pnp/shipyard_pnp/vendors/common/`

Archivos:

| Archivo | Responsabilidad |
|---|---|
| `base_vendor_supervisor.py` | Clase base para VS. Suscribe command, valida ACL/HMAC, publica ACK/STATUS. |
| `task_runner.py` | Ejecuta hardware en un thread para no bloquear executor ROS. |
| `internal_bus.py` | Bus interno simple para eventos dentro de vendor. |
| `mock_vendor_supervisor.py` | Vendor fake para pruebas sin hardware. |

Patron:

```text
command topic -> BaseVendorSupervisor._on_command_raw
              -> handle_task(cmd)
              -> publish_ack(...)
              -> TaskRunner.run(...)
              -> publish_status(RUNNING/COMPLETED/FAILED)
```

### 10.2 Niryo vendor

Directorio:

- `src/shipyard_pnp/shipyard_pnp/vendors/niryo/`

Recursos:

- `robot1`
- `robot2`
- `conveyor1`
- `conveyor2`
- `vision_robot1`
- `vision_robot2`
- `robot2_niryo_vacuum`

Archivos:

| Archivo | Responsabilidad |
|---|---|
| `niryo_vendor_supervisor.py` | Nodo vendor. Recibe comandos Niryo, crea adapters, publica sensores autonomos. |
| `niryo_service_driver.py` | Wrapper de servicios/actions Niryo ROS 2. |
| `robot1_adapter.py` | Movimientos de robot1 para C3/C4, clasificacion local, pick/place con vacuum externo. |
| `robot2_adapter.py` | Movimientos de robot2 para C2S2, Bantam, IBS, C4 y scrap. |
| `niryo_conveyor_adapter.py` | Control conveyors Niryo y lectura sensores de salida. |
| `niryo_ir_adapter.py` | Lectura IR. |
| `local_vision_adapter.py` | Vision local con YOLO para robot1/robot2. |
| `robot2_niryo_vacuum_adapter.py` | Vacuum interno de robot2. |

Tareas relevantes:

- `INITIALIZE_DOMAIN`
- `MOVE_ROBOT`
- `MOVE_PIECE`
- `CAPTURE_LOCAL_VISION`
- `RUN_NIRYO_CONVEYOR`
- `STOP_NIRYO_CONVEYOR`
- `READ_IR_SENSOR`
- `SENSOR_UPDATE`
- `GOTO_PICK_POSITION`
- `CLASSIFY_AND_PICK`
- `LIFT_AND_PLACE`
- `RETURN_HOME`
- `PICK`
- `RELEASE`
- `RESET`

Notas:

- Robot2 usa vacuum Niryo interno.
- Robot1 no controla directamente su vacuum artesanal; el FS coordina `arduino_vacuum`.
- Las camaras locales pueden devolver `color` y `shape` como resultado coordinado, pero no imagen cruda ni parametros internos.

### 10.3 UFactory vendor

Directorio:

- `src/shipyard_pnp/shipyard_pnp/vendors/ufactory/`

Recursos:

- `xarm1`
- `xarm2`

Archivos:

| Archivo | Responsabilidad |
|---|---|
| `ufactory_vendor_supervisor.py` | Nodo vendor. Permite concurrencia por recurso xArm. |
| `lite6_service_driver.py` | Wrapper de servicios xArm Lite6. |
| `xarm1_adapter.py` | C1S2 -> C2S1, C1S2 -> laser, laser -> C2S1. |
| `xarm2_adapter.py` | Stack inicial -> C1S1 o C3. |
| `ufactory_parallel_test.py` | Test de movimientos paralelos xArm1/xArm2. |

Tareas:

- `INITIALIZE_DOMAIN`
- `MOVE_PIECE`
- `MOVE_XARM_HOME`
- `RESET`

#### xArm1

Responsabilidad:

- mover piezas desde C1S2 al laser si son rojas;
- mover piezas desde C1S2 a C2S1 si son azules/verdes;
- retirar pieza roja terminada del laser hacia C2S1.

Posiciones laser actuales:

- `preapproach_laser`: comun.
- `approach_laser_place` y `place_laser`: para depositar en laser.
- `approach_laser_pick` y `pick_laser`: para recoger del laser.

El archivo mantiene comentadas las posiciones laser antiguas para poder recuperarlas si hiciera falta.

#### xArm2

Responsabilidad:

- alimentar `RED`/`BLUE` desde stack inicial a C1S1;
- alimentar `GREEN` desde stack inicial a C3.

Cambio reciente importante:

- en ruta verde hacia C3 se anadio `post_home`;
- despues se anadio `post_home_preapproach_bantam`;
- ambas se usan entre home y approach C3, y tambien de vuelta antes de home;
- se ejecutan con velocidad reducida en esa parte del trayecto.

### 10.4 Laser vendor

Directorio:

- `src/shipyard_pnp/shipyard_pnp/vendors/laser/`

Archivos:

| Archivo | Responsabilidad |
|---|---|
| `laser_vendor_supervisor.py` | Nodo vendor laser. |
| `laser_adapter.py` | Modo HTTP/dry-run, envio/validacion de G-code. |

Configuracion:

- `laser_ip`: `192.168.0.173`;
- `gcode_dir`: `/home/isecapstone/laser_gcode/`;
- `default_gcode`: `happyface.gcode`;
- whitelist: `happyface.gcode`;
- fragmentos bloqueados: `S25`.

Tareas:

- `INITIALIZE_DOMAIN`
- `RUN_JOB`
- `WORK`
- `RESET`
- `GET_READY`
- `GET_READY_TO_WORK`

### 10.5 Global vision vendor

Directorio:

- `src/shipyard_pnp/shipyard_pnp/vendors/globalvision/`

Archivos:

| Archivo | Responsabilidad |
|---|---|
| `globalvision_vendor_supervisor.py` | Nodo vendor de camara global. |
| `camera_adapter.py` | Deteccion de stack/slot/color/ocupacion. |
| `slot_inventory.py` | Modelo de inventario por slots. |
| `calibrator.py` | Utilidad de calibracion ROI. |
| `globalvision_preview.py` | Preview visual. |

Tareas:

- `INITIALIZE_DOMAIN`
- `SCAN_STACK`
- `LOCATE_NEXT_PIECE`
- `GET_INVENTORY`
- `RESET`

Nota critica:

- La shape real de piezas del stack no viene necesariamente de este adapter; se superpone desde `ml_node.py` via `stack_status`.

### 10.6 Green conveyors vendor

Directorio:

- `src/shipyard_pnp/shipyard_pnp/vendors/green_conveyors/`

Archivos:

| Archivo | Responsabilidad |
|---|---|
| `green_conveyors_vendor_supervisor.py` | Nodo vendor de conveyors Arduino 3/4. |
| `shared_arduino_driver.py` | Driver serial compartido. |

Recursos:

- `conveyor3`: canal `B`;
- `conveyor4`: canal `A`.

Tareas:

- `RUN_CONVEYOR`
- `STOP_CONVEYOR`
- `SET_SPEED`
- `RESET`

### 10.7 Arduino vacuum vendor

Directorio:

- `src/shipyard_pnp/shipyard_pnp/vendors/arduino_vacuum/`

Archivos:

| Archivo | Responsabilidad |
|---|---|
| `arduino_vacuum_vendor_supervisor.py` | Nodo vendor para vacuum artesanal de robot1. |
| `arduino_vacuum_driver.py` | Driver serial. |

Configuracion:

- puerto: `/dev/ttyACM1`;
- baudrate: `9600`;
- comando pick: `p`;
- comando release: `r`.

Tareas:

- `PICK`
- `RELEASE`
- `OFF`
- `RESET`

### 10.8 Bantam vendor

Directorio:

- `src/shipyard_pnp/shipyard_pnp/vendors/bantam/`

Archivos:

| Archivo | Responsabilidad |
|---|---|
| `bantam_vendor_supervisor.py` | Nodo vendor Bantam. |
| `bantam_adapter.py` | Ciclo de mecanizado simulado/gestion de job. |
| `door_adapter.py` | Control ZMQ de puerta. |

Configuracion:

- `processing_time_sec`: `25.0`;
- `door_zmq_address`: `tcp://192.168.0.171:5555`;
- `door_timeout_sec`: `12.0`.

Tareas:

- `RUN_JOB`
- `GET_READY`
- `OPEN_DOOR`
- `CLOSE_DOOR`
- `RESET`

---

## 11. Dashboards y nodos auxiliares

### 11.1 Dashboard operacional

Archivo:

- `src/shipyard_pnp/shipyard_pnp/nodes/dashboard_node.py`

Puerto:

- `8080`

Lee:

- `/factory/system_state`
- `/bantam_factory/status`
- `/factory/run_id`
- streams de camaras si estan disponibles
- DB `shipyard_pnp_ws` para analitica basica

Publica:

- `/supervisor/set_optimized_order`

Endpoints:

| Endpoint | Metodo | Uso |
|---|---|---|
| `/` | GET | UI principal. |
| `/api/state` | GET | Snapshot del sistema transformado para UI. |
| `/api/optimize` | POST | Lanza optimizador de orden inicial fixed-priority. |
| `/api/load_dynamic_map` | POST | Carga mapa dinamico para la composicion actual. |
| `/api/optimize_status` | GET | Estado/progreso de optimizador. |
| `/api/expected_schedule` | GET | Schedule esperado vs real. |
| `/api/start_production` | POST | Publica orden/mapa al supervisor. |

Importante:

- Si carga mapa dinamico, debe mandar `expected_schedule` almacenado, no recomputar con prioridad fija.
- Para orden fixed, usa simulacion SimPy y luego aplica el mejor orden inicial.

### 11.2 MES dashboard

Archivo:

- `src/shipyard_pnp/shipyard_pnp/nodes/MES_dashboard.py`

Puerto:

- `8082`

DB por defecto:

- host: `100.115.213.16`
- port: `5432`
- database: `twin_mes_db`
- user: `twin_mes_db`
- password: `postgres`
- schema MES: `mes_pnp_v2`
- schema fuente: `shipyard_pnp_ws`

Endpoints:

| Endpoint | Uso |
|---|---|
| `/api/snapshot` | Ultima telemetria robotica para tarjetas principales. |
| `/api/robot_telemetry` | Estado/telemetria articular por robot. |
| `/api/scada_status` | Status vivo de maquinas, conveyors y vacuums desde `status_log`. |
| `/api/scada_history` | Historico SCADA desde `status_log`. |
| `/api/analytics` | Work centers, colas y metricas para run actual o run filtrado. |
| `/api/analytics_runs` | Lista de runs para filtro. |
| `/api/analytics_range` | Analitica por rango temporal. |
| `/api/history` | Historico de telemetria de robot. |
| `/api/alarms` | Alarmas MES. |
| `/api/wc_history` | Historico de work centers. |
| `/api/db_stats` | Estadisticas de tablas DB. |
| `/api/debug` | Debug DB. |
| `/api/truncate_table` | Truncado de tablas MES permitidas, no fuentes de produccion. |

SCADA devices actuales:

- `laser_status`
- `bantam_machine_status`
- `bantam_door_status`
- `conveyor1_status`
- `conveyor2_status`
- `conveyor3_status`
- `conveyor4_status`
- `robot1_vacuum_state`
- `robot2_vacuum_state`
- `xarm1_vacuum_state`
- `xarm2_vacuum_state`

Fuente de esos estados:

- `shipyard_pnp_ws.status_log`

### 11.3 MES analytics worker

Archivo:

- `src/shipyard_pnp/shipyard_pnp/nodes/mes_analytics_worker.py`

Lee:

- `shipyard_pnp_ws.cycle_event`
- `shipyard_pnp_ws.piece_transfer`

Escribe:

- `mes_pnp_v2.wc_metrics_history`
- `mes_pnp_v2.mes_alarms`

Calcula work centers:

- `xArm2 feed to C3`
- `xArm2 feed to C1S1`
- `xArm1 C1S2 to C2S1`
- `xArm1 C1S2 to Laser`
- `xArm1 Laser to C2S1`
- `Laser process red`
- `Robot2 C2S2 to C4`
- `Robot2 C2S2 to Bantam`
- `Robot2 C2S2 to IBS`
- `Robot2 C2S2 to Scrap`
- `Robot2 IBS to Bantam`
- `Robot2 Bantam to C4`
- `Bantam process blue`
- `Robot1 unload C3`
- `Robot1 unload C4`

Usa ventanas temporales para calcular tasas, medias, variabilidad, utilizacion `rho` y espera aproximada tipo M/G/1.

### 11.4 Joint telemetry writer

Archivo:

- `src/shipyard_pnp/shipyard_pnp/nodes/joint_telemetry_writer.py`

Lee:

- `/robot1/joint_states`
- `/robot2/joint_states`
- `/xarm1/joint_states`
- `/xarm2/joint_states`
- `/ufactory_factory/status`
- `/niryo_factory/status`

Escribe:

- `mes_pnp_v2.robot1_joint_telemetry`
- `mes_pnp_v2.robot2_joint_telemetry`
- `mes_pnp_v2.xarm1_joint_telemetry`
- `mes_pnp_v2.xarm2_joint_telemetry`

Frecuencia:

- `MES_JOINT_WRITE_HZ`, default `10 Hz`.

No publica ningun topic de control. Es solo puente read-only a DB.

### 11.5 Twin bridge

Archivo:

- `src/shipyard_pnp/shipyard_pnp/nodes/twin_bridge_node.py`

Lee status de:

- `/ufactory_factory/status`
- `/niryo_factory/status`
- `/arduino_vacuum_factory/status`
- `/bantam_factory/status`
- `/laser_factory/status`
- `/green_conveyors_factory/status`

Publica topics esperados por el digital twin MuJoCo:

- vacuum ON/OFF por robot;
- conveyors RUNNING/STOPPED;
- door state Bantam;
- laser status.

No escribe en topics PnP ni decide nada. Es un traductor para visualizacion/simulacion externa.

### 11.6 `ml_node.py` externo

Archivo en raiz:

- `ml_node.py`

Es un script standalone pensado para correr incluso en otro ordenador. Hace:

- inferencia YOLO;
- snapshots de stack;
- verificacion visual de conveyors/C3/C4/IBS;
- escritura a PostgreSQL;
- publicacion `stack_status`;
- lectura de `/factory/system_state` y `/factory/run_id`;
- lectura de topics del twin para estado de conveyors.

Tablas que escribe:

- `shipyard_pnp_ws.vision_slot_snapshot`
- `shipyard_pnp_ws.vision_conveyor_snapshot`

Punto importante:

- No controla robots. Solo observa, verifica y alimenta al supervisor con el estado de stack por slot.

**Este checkout no es autocontenido para correr `ml_node.py` — y es intencional, no un bug.** El script corre de verdad en el ordenador de las camaras, no en este. Ahi tiene lo que aqui no esta:

- `ml_node.py:68` hace `from conveyor_detector import ConveyorDetector`. `conveyor_detector.py` no existe en este repo (no esta commiteado, verificado con `git log --all`) porque vive solo en el ordenador de camaras junto al script.
- `ml_node.py:87` resuelve `MODEL_PATH` por defecto a `<carpeta_de_ml_node.py>/best.pt` (la raiz de este repo), no a `models/best.pt` donde realmente esta el peso YOLO en este checkout. En el ordenador de camaras esto se resuelve o bien colocando `best.pt` junto al script, o bien fijando la variable de entorno `ML_MODEL_PATH` — ninguna de las dos cosas esta configurada aqui porque no hace falta: este repo no es donde se ejecuta.
- Contraste util: `local_vision_adapter.py` (que corre dentro de este repo, no en el ordenador de camaras) sí usa la convencion `<workspace>/models/best.pt` por defecto. Son dos módulos con convenciones de ruta distintas para el mismo tipo de archivo, cada uno correcto en su propio entorno de ejecucion — no hay que unificarlos, solo no asumir que el mismo default vale para los dos sitios.

---

## 12. Base de datos

### 12.1 Conexion

Defaults usados por `db_writer.py`, dashboards y workers:

```text
PGHOST=100.115.213.16
PGPORT=5432
PGDATABASE=twin_mes_db
PGUSER=twin_mes_db
PGPASSWORD=postgres
```

Schemas activos:

| Schema | Rol |
|---|---|
| `shipyard_pnp_ws` | Fuente de verdad de produccion, eventos, ciclos, status y mapas. |
| `mes_pnp_v2` | Capa MES: telemetria articular, work center metrics y alarmas MES. |
| `public` | No deberia contener tablas utiles del sistema actual. |

### 12.2 Writer principal

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/db_writer.py`

`RealDBWriter`:

- genera `run_id` legible con timestamp y letras del stack;
- crea schema/tablas si no existen;
- inserta `production_run` al arrancar;
- inserta una fila por pieza;
- registra comandos, ACKs, STATUS, ciclos, transferencias, outcomes, optimizer runs, operator events y alarms;
- envuelve operaciones DB en try/except para que una caida DB no tumbe la fabrica.

### 12.3 Tablas `shipyard_pnp_ws`

| Tabla | Uso |
|---|---|
| `production_run` | Una fila por corrida. Incluye orden original/optimizado, status, piezas completadas, config snapshot. |
| `piece` | Piezas esperadas del run, color/shape/posicion inicial. |
| `piece_transfer` | Movimientos esperados de pieza entre localizaciones. |
| `piece_outcome` | Resultado final por pieza, ruta y localizacion final. |
| `cycle_event` | Ciclos por entidad con fases, duracion, metadata y validacion mapa. |
| `robot_task` | Tareas roboticas derivadas de comandos. |
| `machine_job` | Jobs de maquinas como laser/Bantam. |
| `vision_detection` | Detecciones de vision local/global por pieza/slot. |
| `resource_state_change` | Cambios de estado por recurso. |
| `queue_depth_sample` | Muestras periodicas de profundidad de colas. |
| `command_log` | Todos los comandos enviados por FS. |
| `ack_log` | ACKs recibidos desde vendors. |
| `status_log` | STATUS recibidos desde vendors. Fuente SCADA del MES. |
| `optimizer_run` | Resultados del optimizador fixed/dynamic aplicados o calculados. |
| `operator_event` | Eventos de operador, por ejemplo apply order. |
| `alarm_event` | Alarmas de produccion. |
| `dynamic_map_registry` | Registro de mapas dinamicos generados/validados. |
| `vision_conveyor_snapshot` | Snapshots externos de vision sobre conveyors/C3/C4/IBS. |
| `vision_slot_snapshot` | Snapshots externos de vision del stack inicial. |

Columnas principales:

| Tabla | Columnas clave |
|---|---|
| `production_run` | `run_id`, `started_at`, `finished_at`, `status`, `original_order`, `optimized_order`, `optimizer_savings_s`, `total_pieces`, `pieces_completed`, `git_commit`, `config_snapshot` |
| `piece` | `piece_id`, `run_id`, `color`, `shape`, `initial_position`, `created_at` |
| `piece_transfer` | `id`, `run_id`, `piece_id`, `from_loc`, `to_loc`, `moved_by`, `ts`, `piece_age_s`, `history_json` |
| `piece_outcome` | `piece_id`, `run_id`, `route_taken`, `final_location`, `total_time_s`, `completed`, `completed_at` |
| `cycle_event` | `id`, `run_id`, `ts`, `entity`, `task_name`, `cycle_number`, `piece_id`, `color`, `route`, `started_at`, `completed_at`, `total_duration_s`, `is_discarded`, `discarded_reason`, `phases`, `metadata` |
| `robot_task` | `id`, `run_id`, `command_id`, `robot_id`, `task_name`, `piece_id`, `source`, `target`, `started_at`, `finished_at`, `duration_s`, `result`, `error_detail` |
| `machine_job` | `id`, `run_id`, `command_id`, `machine_id`, `piece_id`, `started_at`, `finished_at`, `duration_s`, `door_open_at`, `door_close_at`, `door_duration_s`, `result` |
| `vision_detection` | `id`, `run_id`, `vision_system`, `piece_id`, `detected_color`, `detected_shape`, `slot_id`, `started_at`, `duration_s`, `success` |
| `resource_state_change` | `id`, `run_id`, `resource_id`, `resource_type`, `from_state`, `to_state`, `ts`, `duration_in_prev_s` |
| `queue_depth_sample` | `id`, `run_id`, `sampled_at`, `location`, `depth` |
| `command_log` | `id`, `run_id`, `command_id`, `domain_id`, `resource_id`, `task_name`, `piece_id`, `source`, `target`, `route`, `parameters`, `sent_at`, `correlation_id` |
| `ack_log` | `id`, `run_id`, `command_id`, `domain_id`, `resource_id`, `task_state`, `resource_state`, `result`, `received_at`, `latency_ms` |
| `status_log` | `id`, `run_id`, `domain_id`, `resource_id`, `topic`, `resource_state`, `task_state`, `code`, `result`, `command_id`, `published_at` |
| `optimizer_run` | `id`, `run_id`, `original_order`, `best_order`, `original_time_s`, `best_time_s`, `saving_s`, `saving_pct`, `method`, `permutations_evaluated`, `optimizer_runtime_s`, `applied`, `applied_at`, `created_at` |
| `operator_event` | `id`, `run_id`, `event_type`, `description`, `ts` |
| `alarm_event` | `id`, `run_id`, `severity`, `resource_id`, `description`, `context_snapshot`, `triggered_at`, `resolved_at` |
| `dynamic_map_registry` | `id`, `composition_key`, `n_blue`, `n_red`, `n_green`, `n_total`, `status`, `hostname`, `started_at`, `completed_at`, `map_id`, `fixed_best_order`, `fixed_best_time_s`, `dynamic_best_order`, `dynamic_best_time_s`, `saving_s`, `saving_pct`, `sampled`, `permutations_total`, `permutations_searched`, `validated_hw`, `hw_doc_path`, `map_json_path`, `created_at`, `updated_at` |
| `vision_conveyor_snapshot` | `id`, `run_id`, `ts`, `conveyor1`, `conveyor2`, `conveyor3`, `conveyor4`, `ibs` |
| `vision_slot_snapshot` | `id`, `run_id`, `ts`, `s1_1` a `s3_6` |

### 12.4 Tablas `mes_pnp_v2`

| Tabla | Uso |
|---|---|
| `robot1_joint_telemetry` | Joints/status robot1 para MES. |
| `robot2_joint_telemetry` | Joints/status robot2 para MES. |
| `xarm1_joint_telemetry` | Joints/status xArm1 para MES. |
| `xarm2_joint_telemetry` | Joints/status xArm2 para MES. |
| `wc_metrics_history` | Historico de metricas por work center. |
| `mes_alarms` | Alarmas generadas por MES/worker/dashboard. |

Columnas de joint telemetry:

- `id`
- `ts`
- `robot_name`
- `robot_status`
- `joint1_position` ... `joint6_position`
- `joint1_velocity` ... `joint6_velocity`
- `joint1_effort` ... `joint6_effort`
- `source_topic`
- `received_at`
- `run_id` si la migracion actual lo incluye en DB

Columnas `wc_metrics_history`:

- `id`
- `ts`
- `window_start`
- `window_end`
- `wc_name`
- `run_id`
- `rho`
- `lq`
- `wq`
- `avg_s`
- `sigma_s`
- `lambda_s`
- `n_samples`
- `is_bottleneck`

Columnas `mes_alarms`:

- `id`
- `ts`
- `severity`
- `alarm_type`
- `entity`
- `message`
- `old_value`
- `new_value`
- `run_id`

### 12.5 Indices importantes

`db_writer.py` crea indices para:

- `piece_transfer(run_id)`
- `piece_transfer(piece_id)`
- `cycle_event(run_id)`
- `robot_task(run_id)`
- `robot_task(command_id)`
- `machine_job(run_id)`
- `resource_state_change(run_id)`
- `resource_state_change(resource_id)`
- `command_log(run_id)`
- `ack_log(command_id)`
- `status_log(run_id)`
- `status_log(command_id)`
- `queue_depth_sample(run_id, sampled_at)`

`dynamic_map_registry.py` crea:

- unique `composition_key`
- index por `status`

`joint_telemetry_writer.py` crea indices por `ts DESC` en cada tabla de telemetria.

---

## 13. Configuracion

Directorio:

- `src/shipyard_pnp/config/`

Archivos:

| Archivo | Uso |
|---|---|
| `hardware_ports.yaml` | IPs, puertos seriales, timeouts, velocidades, laser, Bantam, DB. |
| `vendor_registry.yaml` | Dominios y recursos. |
| `topic_acl.yaml` | Topics que cada nodo puede publicar/suscribir. |
| `factory_layout.yaml` | Localizaciones y rutas por color. |
| `globalvision_rois.yaml` | ROIs reales de vision global. |
| `globalvision_rois.example.yaml` | Ejemplo de ROIs. |
| `hmac_secrets.yaml` | Secretos HMAC locales. Debe tratarse como sensible. |
| `dynamic_maps/*.json` | Mapas dinamicos por composicion. |

Valores destacados de `hardware_ports.yaml`:

| Seccion | Valor |
|---|---|
| `niryo.robot1_ip` | `192.168.0.195` |
| `niryo.robot2_ip` | `192.168.0.244` |
| `ufactory.xarm1_namespace` | `/xarm1` |
| `ufactory.xarm2_namespace` | `/xarm2` |
| `arduino_vacuum.port` | `/dev/ttyACM1` |
| `green_conveyors.port` | `/dev/ttyACM0` |
| `laser.laser_ip` | `192.168.0.173` |
| `bantam.door_zmq_address` | `tcp://192.168.0.171:5555` |
| `globalvision.camera_index` | `0` |

---

## 14. Informes, auditorias y validacion

### 14.1 Reporte real vs sim/mapa

Script:

- `scripts/generate_run_validation_report.py`

Convencion de tiempo:

- inicio real `t0`: cuando empieza el primer ciclo de xArm2, incluyendo `WAITING_GLOBALVISION`;
- final real `t_fin`: fin de `RETURNING_HOME` en el ultimo ciclo de robot1 despues de colocar la ultima pieza.

Para dynamic runs, el script usa:

- `production_run.config_snapshot.expected_schedule`

Esto es importante: si reconstruyera el schedule desde `optimized_order`, convertiria accidentalmente un mapa dinamico en una simulacion fixed-priority.

El reporte valida:

- ciclos esperados vs reales;
- secuencia por entidad;
- mismatches de task;
- mismatches de color;
- intrusos;
- descartados;
- timeouts;
- `followed map`;
- piezas completadas;
- tiempos real vs sim.

### 14.2 Reportes por corrida

Directorio:

- `docs/`

Docs dinamicos existentes:

- `docs/dynamic_map_brrbrb/README.md`
- `docs/dynamic_map_b6_4b4r3g/README.md`
- `docs/dynamic_map_4b5r0g/README.md`
- `docs/dynamic_map_5b4r0g/README.md`
- `docs/dynamic_map_5b5r2g/README.md`
- `docs/dynamic_map_5b5r5g/README.md`
- `docs/dynamic_map_6b6r6g/README.md`
- `docs/dynamic_map_2b2r6g/README.md`
- `docs/dynamic_maps_dataset.md`

### 14.3 Reportes historicos en `results/`

Ejemplos:

- `results/calibracion_ciclos_20260706.md`
- `results/calibracion_ciclos_20260708.md`
- `results/comparacion_ciclo_a_ciclo_18piezas.md`
- `results/experiment_1_boundary_enforcement/README.md`
- `results/experiment_3_coordination_overhead/README.md`
- `results/dynamic_map_generation_logs/`

### 14.4 Run report y audit internos

Archivos:

| Archivo | Uso |
|---|---|
| `src/shipyard_pnp/shipyard_pnp/factory/run_report.py` | Construye reporte de run desde DB. |
| `src/shipyard_pnp/shipyard_pnp/factory/run_report_pdf.py` | Export PDF. |
| `src/shipyard_pnp/shipyard_pnp/factory/run_audit.py` | Auditoria extendida: optimizer, orden ejecutado, alarmas, vision, colas. |
| `src/shipyard_pnp/shipyard_pnp/factory/run_calibration.py` | Calibracion de duraciones de ciclos. |
| `src/shipyard_pnp/shipyard_pnp/factory/run_report_template.html` | Plantilla HTML. |
| `src/shipyard_pnp/shipyard_pnp/factory/run_audit_template.html` | Plantilla HTML auditoria. |

---

## 15. Estructura util del repositorio

### 15.1 Raiz

| Path | Uso |
|---|---|
| `README.md` | README operativo anterior/general. |
| `README_SYSTEM_ARCHITECTURE.md` | Este documento maestro. |
| `README_DYNAMIC_MAP_HISTORY.md` | Historia/contribucion de mapas dinamicos y resultados. |
| `README_CLAUDE_LIVE_SUPERVISOR.md` | Idea/plan de supervisor con Claude/IA en vivo como selector acotado. |
| `README_EXPERIMENTS.md` | Documentacion de experimentos. |
| `readme_integration_newtestbed.md` | Notas de integracion. |
| `CODEX.md` | Instrucciones locales para Codex/agentes. |
| `CLAUDE.md` | Memoria/guia previa de Claude. |
| `ml_node.py` | Vision externa standalone. |
| `models/best.pt` | Pesos YOLO usados por vision local/global segun configuracion. |

### 15.2 Paquete ROS

| Path | Uso |
|---|---|
| `src/shipyard_pnp/package.xml` | Manifest ROS. |
| `src/shipyard_pnp/setup.py` | Instalacion Python y console scripts. |
| `src/shipyard_pnp/launch/` | Launch files. |
| `src/shipyard_pnp/config/` | Configuracion, mapas dinamicos, ACL, hardware. |
| `src/shipyard_pnp/resource/shipyard_pnp` | Marker ament. |
| `src/shipyard_pnp/shipyard_pnp/` | Codigo Python principal. |

### 15.3 Codigo principal

| Path | Uso |
|---|---|
| `shipyard_pnp/shared/` | Contratos, mensajes, ACL, IDs temporales. |
| `shipyard_pnp/factory/` | Supervisor, trackers, DB, reports, dynamic schedule. |
| `shipyard_pnp/factory/planner/` | Reglas modulares de produccion. |
| `shipyard_pnp/vendors/` | Vendor supervisors y adapters. |
| `shipyard_pnp/nodes/` | Dashboards, simulacion, twin bridge, MES workers. |

### 15.4 Directorios generados o de runtime

| Path | Uso |
|---|---|
| `build/` | Salida colcon build. No editar a mano. |
| `install/` | Instalacion colcon. No editar a mano. |
| `log/` | Logs colcon. |
| `runtime_logs/` | Logs runtime. |
| `results/` | Resultados de experimentos, calibraciones, logs overnight. |

---

## 16. Archivos utiles por modulo

### 16.1 `shared`

| Archivo | Descripcion |
|---|---|
| `contracts.py` | Enumera domains, resources, task states, robot states, machine states, task names y topics derivados. |
| `messages.py` | Construye JSON command/ack/status, firma/verifica HMAC y filtra campos propietarios. |
| `acl_guard.py` | Check inbound/outbound de ACL y proprietary boundary. |
| `topic_acl.py` | Carga/representa ACL de topics. |
| `time_ids.py` | Timestamps, command ids, nonce. |

### 16.2 `factory`

| Archivo | Descripcion |
|---|---|
| `factory_supervisor.py` | Nodo central de coordinacion. |
| `vendor_client.py` | Cliente por dominio vendor, correlacion ACK/STATUS. |
| `state_tracker.py` | Estado grueso de recursos. |
| `piece_tracker.py` | Pipeline esperado de piezas. |
| `cycle_tracker.py` | Ciclos por entidad/pieza y fases. |
| `system_state_publisher.py` | Publica `/factory/system_state`. |
| `db_writer.py` | Persistencia PostgreSQL de produccion. |
| `expected_schedule.py` | Schedules esperados desde simulacion. |
| `dynamic_schedule.py` | Carga de mapas dinamicos por composicion. |
| `run_report.py` | Reporte DB por corrida. |
| `run_audit.py` | Auditoria extendida. |
| `run_calibration.py` | Calibracion de tiempos. |
| `ANALYTICS.md` | Notas de analitica. |

### 16.3 `factory/planner`

| Archivo | Descripcion |
|---|---|
| `initialization_rules.py` | Arranque e inicializacion dominios. |
| `feeding_rules.py` | xArm2 y stack inicial. |
| `conveyor_rules.py` | Conveyor1/2/3/4. |
| `processing_rules.py` | xArm1 y laser. |
| `classification_rules.py` | Robot2, Bantam, IBS, C4. |
| `unloading_rules.py` | Robot1, C3/C4, Arduino vacuum. |
| `shutdown_rules.py` | Parada segura. |

### 16.4 `nodes`

| Archivo | Descripcion |
|---|---|
| `dashboard_node.py` | Dashboard operacional puerto 8080. |
| `MES_dashboard.py` | MES dashboard puerto 8082. |
| `mes_analytics_worker.py` | Worker que calcula work centers. |
| `joint_telemetry_writer.py` | Joints/status a DB MES. |
| `twin_bridge_node.py` | Traduce status PnP a topics MuJoCo. |
| `shipyard_sim.py` | Simulacion base SimPy. |
| `shipyard_sim_search.py` | Simulacion para busqueda de orden. |
| `dispatch_search2.py` | Simulacion de despacho dinamico. |
| `beam_search.py` | Busqueda/rollouts de decision path. |
| `shipyard_sim copy.py` | Copia historica, no deberia ser fuente primaria. |
| `shipyard_sim.py.bak_20260628` | Backup historico. |

### 16.5 `scripts`

| Archivo | Descripcion |
|---|---|
| `bringup.sh` | Helper de arranque. |
| `generate_dynamic_map.py` | Generador offline de mapas dinamicos. |
| `dynamic_map_registry.py` | Sincroniza/consulta registro DB de mapas. |
| `generate_run_validation_report.py` | Genera informe fixed vs dynamic desde DB. |
| `run_overnight_dynamic_maps*.sh` | Batches largos de generacion. |
| `run_parallel_dynamic_maps_12to15pc.sh` | Batch paralelo. |
| `run_5lane_dynamic_maps_50comp.sh` | Batch experimental de muchas composiciones. |

### 16.6 `experiments`

| Path | Uso |
|---|---|
| `experiments/boundary_enforcement/` | Experimento de enforcement de frontera/ACL. |
| `experiments/coordination_overhead/` | Experimento de overhead de coordinacion y analisis rosbag. |

---

## 17. Operacion habitual

### 17.1 Arranque tipico

Desde el workspace:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch shipyard_pnp pnp_full_system.launch.py
```

Dashboard:

```text
http://localhost:8080
```

MES:

```text
http://localhost:8082
```

### 17.2 Flujo de una corrida normal

1. Configurar `INITIAL_STACK_ORDER` si se esta haciendo una prueba manual.
2. Arrancar sistema.
3. Esperar inicializacion de vendors.
4. En dashboard:
   - usar `Optimize Order`, o
   - usar `Load Dynamic Map`.
5. Confirmar/aplicar.
6. FS recibe `/supervisor/set_optimized_order`.
7. FS reordena `PieceTracker`, instala `expected_schedule` si existe y pasa a producir.
8. Vendors ejecutan tareas.
9. DB registra ciclos, comandos, status, outcomes.
10. Al completar todas las piezas, `production_run.status` pasa a `COMPLETED`.
11. Generar informe si hace falta.

### 17.3 Generar informe de validacion

Ejemplo:

```bash
PYTHONPATH=src/shipyard_pnp PGPASSWORD=postgres \
python3 scripts/generate_run_validation_report.py \
  --fixed-run 20260712_205819_BGRBGGRGGG \
  --dynamic-run 20260712_210633_BGRBGGRGGG \
  --out docs/dynamic_map_2b2r6g
```

Para el ultimo dynamic completed:

```bash
PYTHONPATH=src/shipyard_pnp PGPASSWORD=postgres \
python3 scripts/generate_run_validation_report.py \
  --latest-dynamic \
  --out /tmp/latest_dynamic_report.md
```

### 17.4 Generar mapa dinamico

```bash
PYTHONPATH=src/shipyard_pnp \
python3 scripts/generate_dynamic_map.py BRGBRGBRG \
  --top-k 20 \
  --beam-width 80 \
  --max-rollouts 4000 \
  --max-levels 400 \
  --patience 8 \
  --sample-cap 2000 \
  --seed 42
```

---

## 18. Seguridad y limites de control

Principios actuales:

1. El FS nunca manda movimiento de joints directo. Manda tareas semanticas.
2. Los vendors encapsulan detalles privados del hardware.
3. Los mapas dinamicos no fuerzan acciones fisicamente imposibles.
4. Vision/sensores mandan sobre el mapa.
5. Si un mapa se descuadra, se espera un margen y luego se vuelve a politica reactiva.
6. La DB no debe tumbar la produccion si falla.
7. El MES es observador/analitico, no controlador.
8. `twin_bridge_node` y `joint_telemetry_writer` son read-only respecto al control.

Casos protegidos:

- C4 lleno;
- Bantam no terminado;
- C3/C4 sin settle time;
- sensor no coincide;
- vision detecta color/shape inesperado;
- intruso;
- vendor busy;
- timeout de comando;
- falta de subscriber durante init;
- `stack_status` potencialmente viejo tras recarga de slot.

---

## 19. Donde tocar segun el cambio

| Cambio deseado | Archivo(s) |
|---|---|
| Cambiar stack inicial de prueba | `factory_supervisor.py`, `INITIAL_STACK_ORDER` |
| Cambiar ruta fisica de un color | `factory_layout.yaml`, planner correspondiente, simulacion |
| Cambiar prioridad reactiva de robot2 | `classification_rules.py` y `dispatch_search2.py` |
| Cambiar prioridad/espera robot1 C3/C4 | `unloading_rules.py` y `dispatch_search2.py` |
| Cambiar comportamiento xArm1 laser | `processing_rules.py`, `xarm1_adapter.py`, simulacion |
| Cambiar poses xArm1 | `xarm1_adapter.py` |
| Cambiar poses xArm2 | `xarm2_adapter.py` |
| Cambiar poses robot1 | `robot1_adapter.py` |
| Cambiar poses robot2 | `robot2_adapter.py` |
| Cambiar timeout mapa | `factory_supervisor.py`, `MAP_GRACE_SEC` |
| Cambiar generacion de mapa dinamico | `generate_dynamic_map.py`, `beam_search.py`, `dispatch_search2.py` |
| Cambiar carga de mapa desde dashboard | `dynamic_schedule.py`, `dashboard_node.py` |
| Cambiar tabla/registro DB produccion | `db_writer.py` |
| Cambiar MES analytics | `MES_dashboard.py`, `mes_analytics_worker.py` |
| Cambiar telemetria de joints | `joint_telemetry_writer.py` |
| Cambiar twin MuJoCo | `twin_bridge_node.py` |
| Cambiar vision externa | `ml_node.py` |
| Cambiar ACL/HMAC | `shared/messages.py`, `shared/acl_guard.py`, `config/topic_acl.yaml`, `config/hmac_secrets.yaml` |

---

## 20. Glosario

| Termino | Significado |
|---|---|
| FS | Factory Supervisor. Coordinador central. |
| VS | Vendor Supervisor. Nodo por dominio fisico. |
| Adapter | Implementacion concreta dentro de vendor. |
| C1S1/C1S2 | Entrada/salida conveyor1. |
| C2S1/C2S2 | Entrada/salida conveyor2. |
| C3 | Handoff de verdes. |
| C4 | Handoff de rojas/azules despues de robot2/Bantam. |
| IBS | Intermediate Blue Stack, buffer azul. |
| Fixed priority | Politica reactiva fija. |
| Dynamic map | Orden y decisiones precomputadas offline. |
| `matched` | El ciclo real coincide con el schedule esperado. |
| `followed` | El sistema espero y siguio el mapa. |
| `timeout` | El sistema espero, no aparecio la condicion, y uso fallback. |
| Makespan | Tiempo desde primer movimiento/ciclo xArm2 hasta return home final de robot1. |
| Work center | Agrupacion MES de ciclos equivalentes para analitica. |

---

## 21. Estado mental correcto para trabajar en este repo

Este repo ya no es solo "codigo de robots". Es una pila completa:

```text
hardware real
vendors/adapters
supervisor
planner
simulacion
dynamic maps
DB de produccion
MES
vision externa
digital twin
documentacion de validacion
```

La forma segura de evolucionarlo es mantener sincronizados tres mundos:

1. **Realidad fisica:** poses, velocidades, sensores, delays, vision.
2. **Modelo online:** planner, PieceTracker, CycleTracker, expected schedule.
3. **Modelo offline:** SimPy, dispatch search, beam search, dynamic maps.

Si se cambia una trayectoria, una velocidad o una regla de decision, hay que preguntarse:

- si el adapter real cambio;
- si el planner sigue describiendo bien la accion;
- si el simulador refleja el nuevo tiempo/comportamiento;
- si los reportes comparan contra el schedule correcto;
- si DB/MES siguen leyendo los nombres correctos de task/resource.

Esa es la clave para que el sistema siga siendo defendible: no basta con que se mueva, tiene que moverse, medirse y explicarse con el mismo lenguaje en todos los niveles.

---

## 22. Anexo de codigo vivo

La parte anterior explica el sistema. Esta parte baja al codigo. La idea es que alguien pueda abrir un archivo y saber que funcion mirar, que estado toca, que comando manda y que tabla acaba afectando.

### 22.1 Ciclo real de un comando

El ciclo completo de un comando en produccion es:

```text
planner rule
  -> FactorySupervisor.send_command(...)
  -> VendorClient.send_command(...)
  -> build_command(...)
  -> /{domain}_factory/command
  -> BaseVendorSupervisor._on_command_raw(...)
  -> concrete_vendor.handle_task(...)
  -> publish_ack(...)
  -> TaskRunner.run(...)
  -> adapter real
  -> publish_status(...)
  -> FactorySupervisor.on_status(...)
  -> VendorClient.on_status_received(...)
  -> callback on_complete(...)
  -> PieceTracker / CycleTracker / DB
```

Codigo de entrada en el supervisor:

```python
# src/shipyard_pnp/shipyard_pnp/factory/factory_supervisor.py
def send_command(
    self,
    domain_id: str,
    resource_id: str,
    task: str,
    piece_id: Optional[str] = None,
    source: Optional[str] = None,
    target: Optional[str] = None,
    route: Optional[str] = None,
    parameters: Optional[dict] = None,
    correlation_id: Optional[str] = None,
    on_complete=None,
) -> str:
    with self._state_lock:
        vc = self.vendor_clients[domain_id]
        if vc.is_busy(resource_id):
            raise RuntimeError(
                f"VendorClient '{domain_id}/{resource_id}' is busy; planner must wait"
            )
        command_id = vc.send_command(
            resource_id=resource_id,
            task=task,
            piece_id=piece_id,
            source=source,
            target=target,
            route=route,
            parameters=parameters,
            correlation_id=correlation_id,
            on_complete=on_complete,
        )
    self.db.insert_command(...)
    return command_id
```

Lo importante de este bloque:

- no deja mandar dos comandos al mismo recurso si `VendorClient.is_busy(resource_id)` esta activo;
- guarda el comando en `shipyard_pnp_ws.command_log`;
- el callback `on_complete` se queda asociado al `command_id` hasta que llega un STATUS terminal.

`VendorClient.send_command` construye JSON y lo publica:

```python
# src/shipyard_pnp/shipyard_pnp/factory/vendor_client.py
payload = build_command(
    domain_id=self.domain_id,
    resource_id=resource_id,
    task=task,
    correlation_id=correlation_id,
    piece_id=piece_id,
    source=source,
    target=target,
    route=route,
    parameters=params,
    secret=self._hmac_secret or None,
)
command_id = payload["command_id"]
...
self._pending_by_command[command_id] = pending
self._pending_by_resource[resource_id] = pending
...
msg.data = to_json(payload)
self._publisher.publish(msg)
```

El contrato JSON exacto se genera en `shared/messages.py`:

```python
payload = {
    "schema": "shipyard.pnp.command.v1",
    "command_id": command_id,
    "correlation_id": correlation_id,
    "sender_id": sender_id,
    "domain_id": domain_id,
    "resource_id": resource_id,
    "task": task,
    "piece_id": piece_id,
    "source": source,
    "target": target,
    "route": route,
    "parameters": parameters or {},
    "issued_at": issued_at,
    "nonce": nonce,
    "auth": "",
}
```

El vendor recibe asi:

```python
# src/shipyard_pnp/shipyard_pnp/vendors/common/base_vendor_supervisor.py
def _on_command_raw(self, msg: String) -> None:
    cmd = json.loads(msg.data)
    if cmd.get("domain_id") != self.domain_id:
        return

    decision = check_outbound(
        sender_id=cmd.get("sender_id", ""),
        topic=f"/{self.domain_id}_factory/command",
        payload=cmd,
        secret=self._hmac_secret or None,
        enforce_hmac=bool(self._hmac_secret),
    )
    if not decision.allowed:
        self._publish_acl_event(...)
        return

    accepted, reason = self.handle_task(cmd)
    self.publish_ack(...)
```

Cada vendor implementa solo `handle_task(cmd)`. Esa es la frontera Plug-and-Plan: el FS no sabe como se mueve un robot; el vendor no sabe por que esa pieza es importante para el makespan global.

### 22.2 Bucle principal del supervisor

El supervisor no tiene un while manual. ROS ejecuta `evaluate_rules` cada `0.5 s`.

```python
def evaluate_rules(self) -> None:
    with self._state_lock:
        if self.planner_phase == PlannerPhase.BOOT:
            initialization_rules.evaluate(self)
        elif self.planner_phase == PlannerPhase.WAITING_FOR_ORDER:
            pass
        elif self.planner_phase == PlannerPhase.RUNNING:
            for name, rule in (
                ("feeding", feeding_rules),
                ("conveyor", conveyor_rules),
                ("processing", processing_rules),
                ("classification", classification_rules),
                ("unloading", unloading_rules),
            ):
                rule.evaluate(self)
            if self.pieces.all_pieces_finished():
                self.planner_phase = PlannerPhase.SHUTTING_DOWN
        elif self.planner_phase == PlannerPhase.SHUTTING_DOWN:
            shutdown_rules.evaluate(self)
```

Orden de evaluacion en cada tick:

1. `feeding`: mete piezas nuevas al sistema.
2. `conveyor`: mueve conveyor1/conveyor2.
3. `processing`: xArm1 + laser.
4. `classification`: robot2 + Bantam + IBS.
5. `unloading`: robot1 + vacuum.

Esto es importante: las reglas estan desacopladas, pero comparten `StateTracker`, `PieceTracker` y `VendorClient`. Una regla no debe hacer busy-wait; si no puede actuar, retorna y se vuelve a probar en el siguiente tick.

### 22.3 Aplicacion de orden optimizado o mapa dinamico

La entrada desde dashboard llega por `/supervisor/set_optimized_order` y entra en `_on_optimized_order`.

```python
payload = json.loads(msg.data)
order = payload.get("order")
map_mode = payload.get("map_mode", "fixed")
map_id = payload.get("map_id")
expected_schedule = payload.get("expected_schedule")

with self._state_lock:
    self._optimized_order = list(order)
    self.pieces.reorder_initial_stack(order)
    if self.planner_phase == PlannerPhase.WAITING_FOR_ORDER:
        self.planner_phase = PlannerPhase.RUNNING
```

Si el dashboard manda un mapa dinamico completo:

```python
if isinstance(expected_schedule, dict) and expected_schedule:
    with self._state_lock:
        self._expected_schedule = expected_schedule
else:
    threading.Thread(
        target=self._build_expected_schedule_async,
        args=(list(order),), daemon=True,
    ).start()
```

Luego se persiste en DB:

```python
self.db.insert_operator_event("APPLY_ORDER", detail)
self.db.update_production_run_optimized_order(order, saving_s)
self.db.update_production_run_config_snapshot({
    "map_mode": map_mode,
    "map_id": map_id,
    "expected_schedule": expected_schedule,
    "reference_order": payload.get("reference_order"),
    "reference_time_s": payload.get("reference_time_s"),
})
```

Por eso los informes dinamicos deben leer `production_run.config_snapshot.expected_schedule`. Si se recalcula desde `optimized_order`, se pierde el mapa dinamico y se compara contra una politica fija.

### 22.4 Codigo exacto de map guidance

El mapa solo opina si hay schedule cargado:

```python
def _map_next(self, entity: str) -> Optional[dict]:
    if not self._map_guidance_enabled:
        return None
    cycles = self._expected_schedule.get(entity)
    if not cycles:
        return None
    idx = self._map_pointer.get(entity, 0)
    if idx >= len(cycles):
        return None
    return cycles[idx]
```

La espera protegida esta aqui:

```python
def _map_should_wait(self, entity: str) -> bool:
    now = time.time()
    started = self._map_wait_since.get(entity)
    if started is None:
        self._map_wait_since[entity] = now
        return True
    if (now - started) < self.MAP_GRACE_SEC:
        return True
    self._map_wait_since.pop(entity, None)
    self._map_last_wait_duration[entity] = now - started
    return False
```

Interpretacion:

- primera llamada: empieza episodio de espera y devuelve `True`;
- llamadas dentro de `MAP_GRACE_SEC`: sigue esperando;
- si expira: devuelve `False`, limpia timestamp y permite fallback reactivo.

Resolucion de una decision:

```python
expected = self._map_next(entity)
expected_task = expected["task"]
matched = actual_category == expected_task

if matched:
    self._map_pointer[entity] = self._map_pointer.get(entity, 0) + 1
    if waited_before_this:
        self._map_last_dispatch_info[entity] = {
            "map_outcome": "followed",
            "map_expected": expected_label,
            "map_wait_s": round(waited_before_this, 2),
        }
elif gave_up_after is not None:
    self.db.insert_alarm(... "map_guidance_timeout" ...)
    self._map_last_dispatch_info[entity] = {
        "map_outcome": "timeout",
        "map_expected": expected_label,
        "map_wait_s": round(gave_up_after, 2),
    }
else:
    self.db.insert_alarm(... "map_guidance_intruder" ...)
    self._map_last_dispatch_info[entity] = {
        "map_outcome": "intruder",
        "map_expected": expected_label,
    }
```

La regla fuerte: el puntero del mapa solo avanza si la accion real coincide con la esperada. Un intruso o mismatch no consume silenciosamente una entrada del mapa.

### 22.5 Por que existen `register_pick_source` y `register_place_target`

Muchos adapters hacen pick, travel, place y home dentro del mismo comando vendor. Si el `PieceTracker` esperase al final del comando, la pieza seguiria apareciendo en la cola origen aunque fisicamente ya fue cogida. Por eso el FS registra hooks:

```text
antes de mandar MOVE_PIECE:
  fs.register_pick_source(entity, source_loc)
  fs.register_place_target(entity, target_loc)

cuando llega STATUS resource_state == PICK_DONE:
  PieceTracker transfiere source_loc -> gripper_loc

cuando llega STATUS resource_state == PLACE_DONE:
  PieceTracker transfiere gripper_loc -> target_loc
```

Esto corrige un bug real documentado en comentarios: sin este hook, una pieza podia ser arrastrada por el modelo esperado despues de que el robot ya habia soltado otra pieza.

Archivos que dependen de esto:

- `feeding_rules.py`: xArm2.
- `processing_rules.py`: xArm1.
- `classification_rules.py`: robot2.
- `unloading_rules.py`: robot1 hace algo parecido pero coordinado con vacuum externo.

### 22.6 `feeding_rules.py` a nivel codigo

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/planner/feeding_rules.py`

Guardas antes de alimentar:

```python
if fs._feeding_state != "IDLE":
    return
if fs.pieces.count("initial_stack") <= 0:
    return
if fs.state.get_robot("xarm2") != RobotState.IDLE:
    return
if fs.vendor_clients["globalvision"].is_busy():
    return
if fs.vendor_clients["ufactory"].is_busy("xarm2"):
    return
if not fs.stack_status_is_fresh():
    return
```

Decision de ruta:

```python
requested_color = fs.pieces.peek_first_piece_color("initial_stack")
if requested_color == "GREEN":
    if fs.state.get_sensor("c3") != SensorState.FREE:
        return
elif fs.state.get_sensor("c1s1") != SensorState.FREE:
    return
```

Primer comando siempre es vision global:

```python
fs.cycles.start_entity_cycle("xarm2", task_name, piece_id=piece_id, color=color)
fs.cycles.add_phase("xarm2", "WAITING_GLOBALVISION")
fs._feeding_state = "WAITING_VISION"
fs.send_command(
    "globalvision",
    "globalvision_camera",
    "LOCATE_NEXT_PIECE",
    piece_id=piece_id,
    source="INITIAL_STACK",
    parameters=params,
    on_complete=_on_locate_complete(fs, piece_id),
)
```

Overlay de shape desde vision externa:

```python
stack_shape = fs.get_stack_status_shape(slot_id)
if stack_shape:
    shape = stack_shape
...
fs.pieces.assign_slot(slot_id)
fs.pieces.assign_color_shape("initial_stack", color, shape)
```

Despacho:

```python
if color == "GREEN":
    fs.cycles.add_phase("xarm2", "MOVING_TO_C3")
    _send_xarm2_to_c3(fs, piece_id, slot_id)
else:
    fs.cycles.add_phase("xarm2", "MOVING_TO_C1S1")
    _send_xarm2_to_c1(fs, piece_id, slot_id)
```

Movimiento rojo/azul:

```python
fs.register_pick_source("xarm2", "initial_stack")
fs.register_place_target("xarm2", "conveyor1")
fs.send_command(
    "ufactory", "xarm2", "MOVE_PIECE",
    piece_id=piece_id,
    source="INITIAL_STACK",
    target="C1S1",
    parameters={"pick_slot": slot_id, "target": "C1S1"},
    on_complete=_on_xarm2_to_c1_complete(fs, piece_id),
)
```

Movimiento verde:

```python
fs.register_pick_source("xarm2", "initial_stack")
fs.register_place_target("xarm2", "c3_location")
fs.send_command(
    "ufactory", "xarm2", "MOVE_PIECE",
    piece_id=piece_id,
    source="INITIAL_STACK",
    target="C3",
    route="GREEN",
    parameters={"pick_slot": slot_id, "target": "C3"},
    on_complete=_on_xarm2_to_c3_complete(fs, piece_id),
)
```

Despues de colocar verde:

```python
fs.state.update_sensor("c3", SensorState.OCCUPIED)
fs._c3_deposit_time = time.time()
fs.send_command("green_conveyors", "conveyor3", "RUN_CONVEYOR", ...)
_schedule_conveyor_stop(fs, "conveyor3", piece_id, "GREEN", fs.c3_settle_sec)
fs.send_command("ufactory", "xarm2", "MOVE_XARM_HOME", ...)
```

### 22.7 `processing_rules.py` a nivel codigo

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/planner/processing_rules.py`

Calcula dos opciones:

```python
retrieve_ready = (
    fs.state.get_machine("laser") == MachineState.FINISHED
    and fs.state.get_sensor("c2s1") == SensorState.FREE
)
c1s2_ready = (
    fs.pieces.count("conveyor1") > 0
    and fs.state.get_sensor("c1s2") == SensorState.OCCUPIED
)
```

Consulta mapa:

```python
expected = fs._map_next("xarm1")
wants_retrieve = expected is not None and expected["task"] == "LASER_TO_C2S1"
wants_c1s2 = expected is not None and expected["task"] in ("C1S2_TO_LASER", "C1S2_TO_C2S1")
```

Casos:

```python
if c1s2_ready and wants_c1s2:
    do_retrieve = False
elif retrieve_ready and wants_retrieve:
    do_retrieve = True
elif retrieve_ready and c1s2_ready:
    do_retrieve = True
elif retrieve_ready:
    if wants_c1s2 and fs._map_should_wait("xarm1"):
        return
    do_retrieve = True
else:
    if wants_retrieve and fs._map_should_wait("xarm1"):
        return
    do_retrieve = False
```

Rutas:

```python
if do_retrieve:
    fs._map_note_dispatch("xarm1", "LASER_TO_C2S1")
    _send_xarm1_laser_to_c2(fs, fs._pending_laser_piece_id)
    return

piece_id = fs.pieces.peek_first_piece_id("conveyor1")
color = fs.pieces.peek_first_piece_color("conveyor1") or "UNKNOWN"
if color == "RED":
    if fs.state.get_machine("laser") != MachineState.IDLE:
        return
    fs._map_note_dispatch("xarm1", "C1S2_TO_LASER")
    _send_xarm1_to_laser(fs, piece_id)
else:
    if fs.state.get_sensor("c2s1") != SensorState.FREE:
        return
    fs._map_note_dispatch("xarm1", "C1S2_TO_C2S1")
    _send_xarm1_direct_to_c2(fs, piece_id, color)
```

Esto significa que xArm1 ya puede esperar por mapa, pero siempre protegido por readiness real.

### 22.8 `classification_rules.py` a nivel codigo

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/planner/classification_rules.py`

Estados ocupados de robot2:

```python
_ROBOT2_BUSY_STATES = frozenset({
    "WAITING_VISION",
    "WAITING_ROBOT2_TO_C4",
    "WAITING_ROBOT2_TO_BANTAM",
    "WAITING_ROBOT2_TO_IBS",
    "WAITING_ROBOT2_TO_SCRAP",
    "WAITING_ROBOT2_IBS_TO_BANTAM",
    "WAITING_ROBOT2_BANTAM_TO_C4",
    "WAITING_ROBOT2_HOME",
})
```

Readiness principal:

```python
classify_ready = (
    fs.state.get_sensor("c2s2") == SensorState.OCCUPIED
    and fs.state.get_sensor("c4") == SensorState.FREE
)
bantam_ready = (
    fs._pending_bantam_piece is not None
    and fs.state.get_sensor("c4") == SensorState.FREE
)
```

Nota fina:

- `classify_ready` no exige `pieces.count("conveyor2") > 0` para poder limpiar intrusos fisicos en C2S2.
- `bantam_ready` no exige `pieces.count("conveyor2") == 0`, porque descargar Bantam a C4 no toca fisicamente C2S2.

Decision map-guided:

```python
if classify_ready and bantam_ready:
    expected = fs._map_next("robot2")
    wants_bantam = expected is not None and expected["task"] == "BANTAM_TO_C4"
    do_classify = not wants_bantam
elif classify_ready:
    expected = fs._map_next("robot2")
    wants_bantam = expected is not None and expected["task"] == "BANTAM_TO_C4"
    if wants_bantam and fs._map_should_wait("robot2"):
        do_classify = None
    else:
        do_classify = True
else:
    expected = fs._map_next("robot2")
    wants_classify = expected is not None and expected["task"].startswith("CLASSIFY_C2S2")
    if wants_classify and fs._map_should_wait("robot2"):
        do_classify = None
    else:
        do_classify = False
```

Si va a clasificar, todavia no sabe destino real. Por eso solo empieza dispatch:

```python
wait_info = fs._map_begin_dispatch("robot2")
fs.cycles.start_entity_cycle(
    "robot2", "CLASSIFY_C2S2",
    piece_id=piece_id,
    metadata={"pick_position": "C2S2"},
)
fs.cycles.add_phase("robot2", "VISION_C2S2")
fs.send_command(
    "niryo",
    "robot2",
    "CAPTURE_LOCAL_VISION",
    piece_id=piece_id,
    source="C2S2",
    parameters={"position": "C2S2"},
    on_complete=_on_vision_complete(fs, piece_id, wait_info),
)
```

La ruta real se decide despues de vision:

```python
color = result.get("color", "UNKNOWN")
shape = result.get("shape", "UNKNOWN")
is_intruder = is_registered_intruder or color_mismatch
route = "SCRAP" if is_intruder else _decide_route(fs, color)
task_name = f"CLASSIFY_C2S2_TO_{route}"
fs._map_resolve_dispatch("robot2", task_name, wait_info)
```

Routing:

```python
def _decide_route(fs, color: str) -> str:
    if color in {"RED", "GREEN"}:
        return "C4"
    if color == "BLUE":
        if fs.state.get_machine("bantam") == MachineState.IDLE and not fs.vendor_clients["bantam"].is_busy():
            return "BANTAM"
        return "IBS"
    return "SCRAP"
```

Acciones finales:

```text
C4:
  robot2 MOVE_PIECE C2S2 -> C4
  sensor c4 OCCUPIED
  conveyor4 RUN + auto-stop
  robot2 RETURN_HOME

BANTAM:
  robot2 MOVE_PIECE C2S2 -> BANTAM_BED
  bantam RUN_JOB
  _pending_bantam_piece = piece_id cuando termina

IBS:
  robot2 MOVE_PIECE C2S2 -> IBS_BED
  luego Priority 3 drena IBS -> Bantam cuando Bantam esta IDLE

SCRAP:
  robot2 MOVE_PIECE C2S2 -> SCRAP
  ciclo de pieza termina en robot2_scrap
```

### 22.9 `unloading_rules.py` a nivel codigo

Archivo:

- `src/shipyard_pnp/shipyard_pnp/factory/planner/unloading_rules.py`

Guardas:

```python
if fs._unloading_state != "IDLE":
    return
if fs.state.get_robot("robot1") != RobotState.IDLE:
    return
if fs.vendor_clients["niryo"].is_busy("robot1"):
    return
if fs.vendor_clients["arduino_vacuum"].is_busy():
    return
```

Ready de C3/C4:

```python
c4_ready_at = fs._c4_deposit_time + fs.c4_settle_sec if c4_occupied else None
c3_ready_at = fs._c3_deposit_time + fs.c3_settle_sec if c3_occupied else None
c4_ready = c4_occupied and now >= c4_ready_at
c3_ready = c3_occupied and now >= c3_ready_at
```

Map guidance robot1:

```python
expected = fs._map_next("robot1")
wants_c3 = expected is not None and expected["task"] == "UNLOAD_C3"
wants_c4 = expected is not None and expected["task"] == "UNLOAD_C4"

if c3_ready and wants_c3:
    go_c4 = False
elif c4_ready and wants_c4:
    go_c4 = True
elif c4_ready and c3_ready:
    go_c4 = c4_ready_at <= c3_ready_at
elif c4_ready:
    if wants_c3 and fs._map_should_wait("robot1"):
        return None
    go_c4 = True
else:
    if wants_c4 and fs._map_should_wait("robot1"):
        return None
    go_c4 = False
```

Secuencia real de robot1 + vacuum:

```text
CLASSIFY_AND_PICK       niryo/robot1
PICK                    arduino_vacuum
LIFT_AND_PLACE          niryo/robot1
RELEASE                 arduino_vacuum
RETURN_HOME             niryo/robot1
```

Codigo de los callbacks:

```python
# tras CLASSIFY_AND_PICK
fs.cycles.add_phase("robot1", "VACUUM_PICK")
fs.send_command("arduino_vacuum", "arduino_vacuum", "PICK", ...)

# tras PICK
fs.state.update_sensor(context["sensor_id"], SensorState.FREE)
fs.pieces.transfer_piece(context["source_location"], "robot1_gripper")
fs.cycles.add_phase("robot1", "LIFT_AND_PLACE")
fs.send_command("niryo", "robot1", "LIFT_AND_PLACE", ...)

# tras LIFT_AND_PLACE
fs.cycles.add_phase("robot1", "VACUUM_RELEASE")
fs.send_command("arduino_vacuum", "arduino_vacuum", "RELEASE", ...)

# tras RELEASE
fs.pieces.transfer_via_gripper("robot1_gripper", context["source_location"], context["final_location"])
fs.cycles.add_phase("robot1", "RETURNING_HOME")
fs.send_command("niryo", "robot1", "RETURN_HOME", ...)
```

Final destination:

```python
if color == "RED":
    return "final_red_circle" if shape == "CIRCLE" else "final_red_stack"
if color == "GREEN":
    return "final_green_circle" if shape == "CIRCLE" else "final_green_stack"
if color == "BLUE":
    return "final_blue_circle" if shape == "CIRCLE" else "final_blue_stack"
return "robot1_scrap"
```

### 22.10 Adapters UFactory con poses reales

#### xArm1

Archivo:

- `src/shipyard_pnp/shipyard_pnp/vendors/ufactory/xarm1_adapter.py`

Rutas soportadas:

```python
if source == "C1S2" and target == "C2S1":
    self._c1s2_to_c2s1(route, status_cb)
elif source == "C1S2" and target == "LASER_BED":
    self._c1s2_to_laser(status_cb)
elif source == "LASER_BED" and target == "C2S1":
    self._laser_to_c2s1(status_cb)
else:
    raise ValueError(...)
```

Laser pick/place separados actualmente:

```python
"preapproach_laser": [-0.1608, 0.7263, 1.9174, -0.0447, 1.1176, -0.0385, 0.0],
"approach_laser_place": [-0.2544, 1.0460, 1.8157, -0.0431, 1.1936, -0.0015],
"place_laser": [-0.2623, 1.1955, 1.8083, -0.0585, 1.1387, -0.0832],
"approach_laser_pick": [-0.2425, 1.0884, 1.8137, 0.0470, 0.6531, -0.4516],
"pick_laser": [-0.2641, 1.3856, 2.0659, 0.1741, 0.6751, -0.6105],
```

Posiciones antiguas conservadas como comentario:

```python
# "approach_laser": [-0.2428, 1.3724, 2.1971, -0.0968, 0.7393, -0.2100, 0.0],
# "place_laser": [-0.2356, 1.4958, 2.2759, 0.0102, 0.7348, -0.3820],
```

Flujo place laser:

```python
self._move("preapproach_laser", "Pre-Approach LASER", 30.0, 100.0, status_cb)
self._move("approach_laser_place", "Approach LASER place", 30.0, 100.0, status_cb)
self._move("place_laser", "Place LASER", 30.0, 100.0, status_cb)
self.driver.vacuum_off()
self._move("approach_laser_place", "Retorno LASER place", 30.0, 100.0, status_cb)
self._move("preapproach_laser", "Retorno Pre-Approach LASER", 30.0, 100.0, status_cb)
self.move_home(status_cb)
```

Flujo pick laser:

```python
self._move("home", "HOME inicial PICK_LASER", 30.0, 100.0, status_cb)
self._move("preapproach_laser", "Pre-Approach LASER", 30.0, 100.0, status_cb)
self._move("approach_laser_pick", "Approach LASER pick", 30.0, 100.0, status_cb)
self._move("pick_laser", "Pick LASER", 30.0, 100.0, status_cb)
self.driver.vacuum_on()
self._move("approach_laser_pick", "Retorno LASER pick", 30.0, 100.0, status_cb)
self._move("preapproach_laser", "Retorno Pre-Approach LASER", 30.0, 100.0, status_cb)
self._move("home", "HOME intermedio", 30.0, 100.0, status_cb)
```

#### xArm2

Archivo:

- `src/shipyard_pnp/shipyard_pnp/vendors/ufactory/xarm2_adapter.py`

Rutas soportadas:

```python
if target not in {"C1S1", "C3"}:
    raise ValueError(f"Unsupported xarm2 target: {target}")

self._pick_from_slot(pick_slot, status_cb)
if target == "C3":
    self._place_to_c3(status_cb)
    return {"resource_state": RobotState.PLACE_DONE.value, "code": "PLACED_C3", ...}

self._place_to_c1s1(status_cb)
return {"resource_state": RobotState.IDLE.value, "code": "MOVE_DONE", ...}
```

Pick del stack:

```python
stack = slot_id.split(".")[0]
approach_stack = f"approach_{stack}"
approach_slot = f"approach_{slot_id}"
pick_slot = f"pick_{slot_id}"

self._move("home", "HOME inicial", 30.0, 100.0, status_cb)
self._move(approach_stack, ..., 30.0, 100.0, status_cb)
self._move(approach_slot, ..., 25.0, 80.0, status_cb)
self._move(pick_slot, ..., 20.0, 60.0, status_cb)
self.driver.vacuum_on()
```

Ruta verde C3 con posiciones nuevas:

```python
"post_home": [-1.1528, -0.5555, 0.5890, -0.1615, 1.0249, 0.0652, 0.0],
"post_home_preapproach_bantam": [-1.8958, -0.5263, 0.9511, 0.0805, 1.1634, 0.0456, 0.0],
"approach_c3": [-2.5459, 0.4384, 1.6066, -0.0023, 1.0910, -0.9033, 0.0],
"preplace_c3": [-2.5342, 0.7958, 1.4726, -0.0970, 0.6843, -0.9129, 0.0],
"place_c3": [-2.5791, 0.9619, 1.5154, -0.0660, 0.6067, -0.8245, 0.0],
```

Codigo del path:

```python
self._move("post_home", "Post-Home C3", 15.0, 50.0, status_cb)
self._move("post_home_preapproach_bantam", "Post-Home Pre-Approach Bantam C3", 15.0, 50.0, status_cb)
self._move("approach_c3", "Approach C3", 30.0, 100.0, status_cb)
self._move("preplace_c3", "Pre-Place C3", 25.0, 80.0, status_cb)
self._move("place_c3", "Place C3", 20.0, 60.0, status_cb)
self.driver.vacuum_off()
self._placed_at_c3 = True
```

Return home desde C3:

```python
if self._placed_at_c3:
    self._move("preplace_c3", "Retorno Pre-Place C3", 25.0, 80.0, status_cb)
    self._move("approach_c3", "Retorno C3", 30.0, 100.0, status_cb)
    self._move("post_home_preapproach_bantam", "Retorno Post-Home Pre-Approach Bantam C3", 15.0, 50.0, status_cb)
    self._move("post_home", "Retorno Post-Home C3", 15.0, 50.0, status_cb)
    self._placed_at_c3 = False
self._move("home", "Volviendo a HOME", 30.0, 100.0, status_cb)
```

### 22.11 Adapters Niryo a nivel codigo

#### Robot1

Archivo:

- `src/shipyard_pnp/shipyard_pnp/vendors/niryo/robot1_adapter.py`

Metodos principales:

| Metodo | Uso |
|---|---|
| `initialize` | Inicializa robot1. |
| `classify_and_goto_pick` | Vision local y movimiento a pickup C3/C4. |
| `goto_pick_position` | Movimiento a posicion de pick sin clasificar. |
| `lift_and_place` | Lleva pieza a destino final. |
| `move_home` | Return home. |
| `_place_path` | Path de destino final. |
| `_normalize_pick_position` | Normaliza C3/C4. |
| `_normalize_target` | Normaliza destinos finales. |

El vacuum de robot1 NO esta aqui. Robot1 mueve el brazo; `arduino_vacuum` hace `PICK`/`RELEASE`.

#### Robot2

Archivo:

- `src/shipyard_pnp/shipyard_pnp/vendors/niryo/robot2_adapter.py`

Metodos principales:

| Metodo | Uso |
|---|---|
| `initialize` | Inicializa robot2. |
| `capture_local_vision` | Vision en C2S2. |
| `move_piece` | Router general entre C2S2, Bantam, IBS, C4, scrap. |
| `move_home` | Return home. |
| `_pick_c2s2` | Pick en C2S2. |
| `_pick_bantam` | Pick desde Bantam. |
| `_place_c4` | Place en C4. |
| `_place_bantam` | Place en Bantam. |
| `_pick_ibs` | Pick desde IBS. |
| `_place_ibs` | Place en IBS. |
| `_place_scrap` | Place en scrap. |

El vacuum de robot2 si es interno a Niryo y se controla dentro del adapter/driver.

### 22.12 Drivers hardware

#### `Lite6ServiceDriver`

Archivo:

- `src/shipyard_pnp/shipyard_pnp/vendors/ufactory/lite6_service_driver.py`

Responsabilidades:

- esperar servicios xArm;
- habilitar motion;
- set mode/state;
- `move_joint(joints, description, speed, acc)`;
- `vacuum_on()`;
- `vacuum_off()`;
- wrappers `_request`, `_call_optional`, `_call_required`.

Si falla un movimiento real de xArm, el error sale desde aqui hacia el adapter y luego al vendor STATUS `FAILED`.

#### `NiryoServiceDriver`

Archivo:

- `src/shipyard_pnp/shipyard_pnp/vendors/niryo/niryo_service_driver.py`

Responsabilidades:

- inicializar robot;
- mover joints;
- activar/desactivar vacuum Niryo;
- inicializar/controlar conveyor Niryo;
- leer digital IO;
- esperar action goal/result;
- resolver tipos ROS dinamicamente.

#### `ArduinoVacuumDriver`

Archivo:

- `src/shipyard_pnp/shipyard_pnp/vendors/arduino_vacuum/arduino_vacuum_driver.py`

Responsabilidades:

- abrir serial;
- mandar `p` para pick;
- mandar `r` para release;
- esperar respuesta esperada;
- reconectar si hay error serial;
- neutralizar al cerrar.

#### `SharedGreenConveyorDriver`

Archivo:

- `src/shipyard_pnp/shipyard_pnp/vendors/green_conveyors/shared_arduino_driver.py`

Responsabilidades:

- abrir serial compartido;
- configurar canal A/B;
- normalizar direccion;
- enviar RUN/STOP/SET_SPEED;
- parsear status;
- respetar `inter_command_delay_sec`;
- proteger comandos concurrentes sobre un unico Arduino.

#### `LaserAdapter`

Archivo:

- `src/shipyard_pnp/shipyard_pnp/vendors/laser/laser_adapter.py`

Responsabilidades:

- modo HTTP/dry-run;
- validar filename contra whitelist;
- bloquear fragmentos peligrosos;
- leer G-code;
- enviar comandos HTTP;
- simular duracion si aplica.

#### `BantamAdapter` y `DoorAdapter`

Archivos:

- `src/shipyard_pnp/shipyard_pnp/vendors/bantam/bantam_adapter.py`
- `src/shipyard_pnp/shipyard_pnp/vendors/bantam/door_adapter.py`

Responsabilidades:

- abrir/cerrar puerta por ZMQ;
- simular o ejecutar proceso azul;
- publicar estados intermedios de puerta y maquina;
- dejar pieza pendiente para robot2 cuando termina.

### 22.13 Indice de funciones criticas por archivo

Este indice no repite todo el codigo, pero dice que funcion abre una persona para seguir el comportamiento.

#### Supervisor y tracking

| Archivo | Funciones/clases criticas |
|---|---|
| `factory_supervisor.py` | `FactorySupervisor.__init__`, `_setup_vendor_clients`, `_setup_pub_sub`, `send_command`, `on_ack`, `on_status`, `_apply_resource_state`, `_apply_sensor_result`, `_apply_vision_result`, `evaluate_rules`, `watchdog`, `_on_optimized_order`, `_on_stack_status`, `_map_next`, `_map_should_wait`, `_map_begin_dispatch`, `_map_resolve_dispatch`, `_map_note_dispatch`, `_map_pop_dispatch_metadata`, `_sample_queue_depths` |
| `vendor_client.py` | `PendingCommand`, `VendorClient.send_command`, `on_ack_received`, `on_status_received`, `check_timeout`, `_complete` |
| `state_tracker.py` | `update_robot`, `update_conveyor`, `update_sensor`, `update_machine`, `apply_resource_state`, `snapshot` |
| `piece_tracker.py` | `reorder_initial_stack`, `transfer_via_gripper`, `transfer_piece`, `assign_slot`, `assign_color_shape`, `register_intruder`, `peek_first_piece`, `count`, `all_pieces_finished`, `snapshot` |
| `cycle_tracker.py` | `start_entity_cycle`, `add_phase`, `update_entity_cycle`, `complete_entity_cycle`, `discard_entity_cycle`, `start_cycle`, `complete_cycle`, `snapshot` |
| `db_writer.py` | `_ddl`, `RealDBWriter._bootstrap`, `_create_production_run`, `insert_command`, `insert_ack`, `insert_status`, `insert_entity_cycle`, `insert_cycle_complete`, `insert_optimizer_result`, `update_production_run_config_snapshot`, `update_production_run_finished` |

#### Planner

| Archivo | Funciones criticas |
|---|---|
| `initialization_rules.py` | `evaluate`, `_kick_domain`, `_make_callback`, `_first_offline_domain` |
| `feeding_rules.py` | `evaluate`, `_on_locate_complete`, `_send_xarm2_to_c1`, `_send_xarm2_to_c3`, `_on_xarm2_to_c1_complete`, `_on_xarm2_to_c3_complete`, `_schedule_conveyor_stop` |
| `conveyor_rules.py` | `evaluate`, `_conveyor1_rules`, `_conveyor2_rules`, `_on_conveyor_done` |
| `processing_rules.py` | `evaluate`, `_send_xarm1_direct_to_c2`, `_send_xarm1_to_laser`, `_send_laser_job`, `_send_xarm1_laser_to_c2` |
| `classification_rules.py` | `evaluate`, `_decide_route`, `_on_vision_complete`, `_send_robot2_to_c4`, `_send_robot2_to_bantam`, `_send_robot2_to_ibs`, `_send_robot2_ibs_to_bantam`, `_send_bantam_job`, `_on_bantam_complete`, `_send_robot2_bantam_to_c4`, `_send_robot2_to_scrap`, `_schedule_conveyor_stop` |
| `unloading_rules.py` | `evaluate`, `_next_pick_context`, `_final_destination`, `_on_classify_pick_complete`, `_on_vacuum_pick_complete`, `_on_lift_place_complete`, `_on_vacuum_release_complete`, `_on_return_home_complete`, `sync_robot1_vision_phase` |
| `shutdown_rules.py` | `evaluate`, `_execute_step`, `_make_step_callback` |

#### Vendors

| Archivo | Funciones/clases criticas |
|---|---|
| `vendors/common/base_vendor_supervisor.py` | `BaseVendorSupervisor._on_command_raw`, `handle_task`, `publish_ack`, `publish_status`, `_publish_acl_event`, `_load_hmac_secret` |
| `vendors/common/task_runner.py` | `TaskRunner.run`, `TaskRunner.is_running`, `TaskRunner.join` |
| `vendors/niryo/niryo_vendor_supervisor.py` | `handle_task`, `_make_task_fn`, `_initialize_domain`, `_robot_adapter`, `_read_ir_sensor`, `_poll_sensors_once`, `_publish_auto_sensor`, `_resource_status_cb` |
| `vendors/niryo/robot1_adapter.py` | `classify_and_goto_pick`, `goto_pick_position`, `lift_and_place`, `move_home`, `_place_path` |
| `vendors/niryo/robot2_adapter.py` | `capture_local_vision`, `move_piece`, `_pick_c2s2`, `_pick_bantam`, `_place_c4`, `_place_bantam`, `_pick_ibs`, `_place_ibs`, `_place_scrap` |
| `vendors/niryo/local_vision_adapter.py` | `capture`, `_setup_subscription`, `_wait_for_frame`, `_get_model`, `_infer`, `_majority` |
| `vendors/ufactory/ufactory_vendor_supervisor.py` | `handle_task`, `_make_task_fn`, `_resource_status_cb`, `_publish_completed`, `_publish_failed` |
| `vendors/ufactory/xarm1_adapter.py` | `move_piece`, `_pick_from_c1s2`, `_place_to_c2s1`, `_place_to_laser`, `_pick_from_laser`, `_move` |
| `vendors/ufactory/xarm2_adapter.py` | `move_piece`, `_pick_from_slot`, `_place_to_c1s1`, `_place_to_c3`, `move_home`, `_move` |
| `vendors/laser/laser_adapter.py` | `make_task_fn`, `prepare_job`, `run_job`, `_run_http_job`, `_send_gcode_command`, `_validate_filename` |
| `vendors/bantam/bantam_vendor_supervisor.py` | `handle_task`, `_open_door_task`, `_close_door_task`, `_status_cb`, `_publish_completed` |
| `vendors/globalvision/camera_adapter.py` | `scan_stack`, `locate_next_piece`, `_open_camera`, `_capture_frame`, `_detect_color`, `build_preview_image` |
| `vendors/green_conveyors/shared_arduino_driver.py` | `make_task_fn`, `configure_channel`, `send_channel_command`, `_send_and_wait_locked`, `_parse_status` |
| `vendors/arduino_vacuum/arduino_vacuum_driver.py` | `make_task_fn`, `connect`, `_send_command`, `_drain_serial_output`, `_contains_expected` |

#### Dashboards, MES y simulacion

| Archivo | Funciones/clases criticas |
|---|---|
| `nodes/dashboard_node.py` | `_run_optimizer_thread`, `_install_expected_schedule_from_result`, `_Handler.do_GET`, `_Handler.do_POST`, `DashboardNode._on_system_state`, `_normalize`, `_refresh_analytics` |
| `nodes/MES_dashboard.py` | `MESDatabase.get_snapshot`, `get_scada_status`, `get_scada_history`, `get_recent_runs`, `get_run_analytics`, `compute_analytics`, `Handler.do_GET` |
| `nodes/mes_analytics_worker.py` | `compute_window`, `write_metrics`, `write_alarms`, `run_once`, `backfill`, `run_live` |
| `nodes/joint_telemetry_writer.py` | `_ensure_tables`, `_on_joint_state`, `_on_status`, `_flush` |
| `nodes/twin_bridge_node.py` | `_on_ufactory`, `_on_niryo`, `_on_arduino_vacuum`, `_on_bantam`, `_on_laser`, `_on_green_conveyors` |
| `nodes/dispatch_search2.py` | `robot2_process_v2`, `robot1_process_v2`, `xarm1_process_v2`, `run_system`, `fixed_priority_decide_*`, `run_with_path_tagged` |
| `nodes/beam_search.py` | `_worth_waiting`, `_fallback_policies`, `unique_color_orders`, `_advance`, `beam_search`, `search_initial_orders` |
| `scripts/generate_dynamic_map.py` | `parse_order`, `_count_permutations`, `_sample_permutations_directly`, `main` |
| `scripts/generate_run_validation_report.py` | `validate_run`, `schedule_from_run`, `status_for_cycle`, `render_markdown`, `summary_payload` |
| `ml_node.py` | `VisionLoggerNode`, `_on_system_state`, `_camera_loop`, `ensure_tables`, `insert_row`, `build_supervisor_panel`, `check_piece_match` |

### 22.14 Como seguir una pieza roja en el codigo

Ejemplo `RED`:

```text
feeding_rules.evaluate
  -> globalvision LOCATE_NEXT_PIECE
  -> _on_locate_complete
  -> _send_xarm2_to_c1
  -> xarm2_adapter.move_piece(INITIAL_STACK -> C1S1)
  -> PieceTracker initial_stack -> conveyor1
  -> conveyor_rules mueve conveyor1 hasta C1S2
  -> processing_rules.evaluate detecta RED en conveyor1/C1S2
  -> _send_xarm1_to_laser
  -> xarm1_adapter.move_piece(C1S2 -> LASER_BED)
  -> PieceTracker conveyor1 -> laser_bed
  -> _send_laser_job
  -> laser_adapter.run_job
  -> laser FINISHED
  -> processing_rules retira laser
  -> _send_xarm1_laser_to_c2
  -> PieceTracker laser_bed -> conveyor2
  -> conveyor_rules mueve conveyor2 hasta C2S2
  -> classification_rules.evaluate
  -> robot2 CAPTURE_LOCAL_VISION
  -> _decide_route(RED) == C4
  -> _send_robot2_to_c4
  -> PieceTracker conveyor2 -> c4_location
  -> conveyor4 RUN/STOP
  -> unloading_rules.evaluate
  -> robot1 CLASSIFY_AND_PICK C4
  -> arduino_vacuum PICK
  -> robot1 LIFT_AND_PLACE final_red_*
  -> arduino_vacuum RELEASE
  -> robot1 RETURN_HOME
  -> CycleTracker.complete_cycle
  -> piece_outcome completed
```

Tablas tocadas durante esa pieza:

- `piece_transfer`: cada salto entre localizaciones esperadas.
- `vision_detection`: globalvision, robot2 camera, robot1 camera.
- `cycle_event`: xarm2, xarm1, laser, robot2, robot1.
- `command_log`, `ack_log`, `status_log`: todos los comandos.
- `piece_outcome`: al final.
- `resource_state_change`: cambios de estado de recursos.

### 22.15 Como seguir una pieza azul en el codigo

Ejemplo `BLUE`:

```text
feeding_rules -> xArm2 INITIAL_STACK -> C1S1
conveyor_rules -> C1S2
processing_rules -> xArm1 C1S2 -> C2S1
conveyor_rules -> C2S2
classification_rules:
  robot2 vision
  if Bantam IDLE:
    _send_robot2_to_bantam
    _send_bantam_job
    _pending_bantam_piece = piece_id when finished
    later _send_robot2_bantam_to_c4
  else:
    _send_robot2_to_ibs
    later _send_robot2_ibs_to_bantam
    then Bantam job
    then Bantam -> C4
unloading_rules -> robot1 C4 -> final_blue_*
```

El mapa dinamico suele aportar mas aqui porque las decisiones `CLASSIFY_C2S2_*`, `BANTAM_TO_C4` e `IBS_TO_BANTAM` compiten por robot2 y por C4.

### 22.16 Como seguir una pieza verde en el codigo

Ejemplo `GREEN`:

```text
feeding_rules:
  requested_color == GREEN
  require sensor c3 FREE
  globalvision LOCATE_NEXT_PIECE
  _send_xarm2_to_c3
  xarm2_adapter._place_to_c3
  conveyor3 RUN + auto-stop
  sensor c3 OCCUPIED

unloading_rules:
  c3_ready = c3 occupied and settle elapsed
  map may prefer C3 or wait for C4
  robot1 CLASSIFY_AND_PICK C3
  arduino_vacuum PICK
  robot1 LIFT_AND_PLACE final_green_*
  arduino_vacuum RELEASE
  robot1 RETURN_HOME
```

Verdes no deberian pasar por C1S2 -> C2S1 salvo casos anomalos/intrusos. En el modelo actual, xArm1 solo hace `C1S2_TO_C2S1` para azul/verde si una verde llegase a C1S2, pero la ruta normal de verde es C3.

### 22.17 Dynamic map offline a nivel codigo

`generate_dynamic_map.py` hace dos etapas.

Stage 1:

```python
n_perms_total = _count_permutations(n_blue, n_red, n_green)
sampled = n_perms_total > args.sample_cap
if sampled:
    permutations = _sample_permutations_directly(...)
else:
    permutations = list(bs.unique_color_orders(n_blue, n_red, n_green))

for perm in permutations:
    system = ds.run_system(
        perm,
        ds.fixed_priority_decide_r2,
        ds.fixed_priority_decide_r1,
        ds.fixed_priority_decide_x1,
    )
    ms = ds.makespan(system, n_blue, n_red, n_green)
    scored.append((ms, perm))
```

Stage 2:

```python
top_k = scored[: args.top_k]
for fixed_ms, perm in top_k:
    result, n_completed = bs.beam_search(
        perm, n_blue, n_red, n_green,
        beam_width=args.beam_width,
        max_levels=args.max_levels,
        patience=args.patience,
        max_rollouts=args.max_rollouts,
    )
```

Replay:

```python
system, nd = ds.run_with_path_tagged(best_order, best_path)
expected_schedule = build_schedule_from_state_changes(system.state_changes)
```

JSON guardado:

```python
entry = {
    "map_id": f"dynamic_{n_blue}b{n_red}r{n_green}g_{_tag(best_order)}_v1",
    "composition": {"BLUE": n_blue, "RED": n_red, "GREEN": n_green},
    "best_order": _tag(best_order),
    "best_time_s": best_ms,
    "fixed_reference_order": _tag(fixed_reference_order),
    "fixed_reference_time_s": fixed_reference_ms,
    "saving_s": round(fixed_reference_ms - best_ms, 1),
    "decision_path": [[entity, choice] for entity, choice in best_path],
    "expected_schedule": expected_schedule,
    "search_stats": {...},
}
```

### 22.18 `dispatch_search2.py`: que decisiones modela

Entidades con decision:

- `robot2_process_v2`
- `robot1_process_v2`
- `xarm1_process_v2`

Robot2 modela:

```text
CLASSIFY_C2S2_TO_C4
CLASSIFY_C2S2_TO_BANTAM
CLASSIFY_C2S2_TO_IBS
IBS_TO_BANTAM
BANTAM_TO_C4
WAIT cuando merece esperar y hay recurso trabajando
```

Robot1 modela:

```text
UNLOAD_C3
UNLOAD_C4
WAIT por la estacion que el mapa espera si esta en progreso
```

xArm1 modela:

```text
C1S2_TO_C2S1
C1S2_TO_LASER
LASER_TO_C2S1
WAIT por laser o por C1S2 segun el schedule
```

Fixed priorities:

```python
def fixed_priority_decide_r2(ready_options, now=None, system=None):
    for option in ["CLASSIFY_C2S2", "BANTAM_TO_C4", "IBS_TO_BANTAM"]:
        if option in ready_options:
            return option

def fixed_priority_decide_r1(ready_options, now=None, system=None):
    # equivalente a elegir la estacion que termino antes / lleva mas esperando

def fixed_priority_decide_x1(ready_options, now=None, system=None):
    # prioridad fija de laser terminado frente a C1S2, salvo readiness
```

La contribucion de dynamic map es que no aprende una prioridad global fija. Genera un path donde cada decision puede cambiar:

```text
robot2 decision 4: CLASSIFY_C2S2_TO_BANTAM
robot2 decision 5: BANTAM_TO_C4
robot2 decision 6: CLASSIFY_C2S2_TO_C4
robot1 decision 3: WAIT/UNLOAD_C4
xarm1 decision 7: LASER_TO_C2S1
...
```

### 22.19 Reporte de validacion a nivel codigo

Script:

- `scripts/generate_run_validation_report.py`

El tiempo real se calcula asi:

```python
xarm2_cycles = [cycle for cycle in cycles if cycle["entity"] == "xarm2"]
t0 = min(cycle["started_at"] for cycle in xarm2_cycles)

robot1_cycles = [cycle for cycle in cycles if cycle["entity"] == "robot1"]
last_robot1 = max(robot1_cycles, key=lambda cycle: cycle["started_at"])
home_end = returning_home_end(last_robot1.get("phases"))
t_fin = datetime.fromtimestamp(float(home_end), tz=timezone.utc)

real_total = (t_fin - t0).total_seconds()
```

La fuente de schedule:

```python
snap = run.get("config_snapshot") or {}
expected = snap.get("expected_schedule")
if isinstance(expected, dict) and expected:
    schedule = expected
    source = "snapshot"
else:
    order = run.get("optimized_order") or run.get("original_order") or []
    schedule = compute_expected_schedule(order)
    source = "computed_fixed"
```

Validacion fuerte:

```python
validation_ok = (
    run.get("status") == "COMPLETED"
    and pieces_completed == total_pieces
    and expected_cycles == len(cycles)
    and not task_mismatches
    and not color_mismatches
    and not timeout_rows
    and not no_sim_rows
    and not intruder_rows
    and not discarded_rows
    and all(value == "OK" for value in per_entity.values())
)
```

Por eso un informe no solo compara tiempos. Tambien certifica que los ciclos ocurrieron en el orden esperado.

### 22.20 MES: de donde lee cada panel

`MES_dashboard.py` no lee una DB inventada. Lee:

```python
DB_SCHEMA = os.environ.get("MES_PGSCHEMA", os.environ.get("PGSCHEMA", "mes_pnp_v2"))
SOURCE_SCHEMA = os.environ.get("MES_SOURCE_SCHEMA", os.environ.get("MES_SRC_PGSCHEMA", "shipyard_pnp_ws"))
```

Status SCADA:

```python
FROM {SOURCE_SCHEMA}.status_log
```

Robot telemetry:

```python
FROM {DB_SCHEMA}.{robot}_joint_telemetry
```

Work centers:

```python
FROM {DB_SCHEMA}.wc_metrics_history
```

Run analytics:

```python
FROM {SOURCE_SCHEMA}.cycle_event
FROM {SOURCE_SCHEMA}.piece_transfer
LEFT JOIN {SOURCE_SCHEMA}.piece
```

El worker que alimenta `wc_metrics_history` mapea task names asi:

```python
TASK_TO_WC = {
    ("xarm2", "FEED_GREEN_TO_C3"): "xArm2 feed to C3",
    ("xarm2", "FEED_TO_C1S1"): "xArm2 feed to C1S1",
    ("xarm1", "C1S2_TO_C2S1"): "xArm1 C1S2 to C2S1",
    ("xarm1", "C1S2_TO_LASER"): "xArm1 C1S2 to Laser",
    ("xarm1", "LASER_TO_C2S1"): "xArm1 Laser to C2S1",
    ("laser", "PROCESS_RED"): "Laser process red",
    ("robot2", "CLASSIFY_C2S2_TO_C4"): "Robot2 C2S2 to C4",
    ("robot2", "CLASSIFY_C2S2_TO_BANTAM"): "Robot2 C2S2 to Bantam",
    ("robot2", "CLASSIFY_C2S2_TO_IBS"): "Robot2 C2S2 to IBS",
    ("robot2", "IBS_TO_BANTAM"): "Robot2 IBS to Bantam",
    ("robot2", "BANTAM_TO_C4"): "Robot2 Bantam to C4",
    ("bantam", "PROCESS_BLUE"): "Bantam process blue",
    ("robot1", "UNLOAD_C3"): "Robot1 unload C3",
    ("robot1", "UNLOAD_C4"): "Robot1 unload C4",
}
```

Si en el futuro se cambia un `task_name`, hay que cambiarlo tambien aqui o el MES dejara de agrupar bien.

### 22.21 `ml_node.py`: vision externa en codigo

`ml_node.py` vive en la raiz porque puede correr standalone en otro ordenador.

Entradas:

```text
/factory/run_id
/factory/system_state
/factory/conveyor_1/status
/factory/conveyor_2/status
camaras OpenCV [2, 0, 4, 6]
YOLO best.pt
rois.json
```

Salidas:

```text
stack_status
shipyard_pnp_ws.vision_slot_snapshot
shipyard_pnp_ws.vision_conveyor_snapshot
```

Bloqueo por tareas:

```python
XARM1_C1S2_TASKS = {"C1S2_TO_C2S1", "C1S2_TO_LASER"}
ROBOT1_C3_TASK = "UNLOAD_C3"
ROBOT1_C4_TASK = "UNLOAD_C4"
ROBOT2_IBS_TASKS = {"CLASSIFY_C2S2_TO_IBS", "IBS_TO_BANTAM"}
XARM2_C1S1_TASK = "FEED_TO_C1S1"
XARM2_C3_TASK = "FEED_GREEN_TO_C3"
XARM1_C2S1_PLACE_TASKS = {"C1S2_TO_C2S1", "LASER_TO_C2S1"}
ROBOT2_C4_PLACE_TASKS = {"CLASSIFY_C2S2_TO_C4", "BANTAM_TO_C4"}
```

Por que lee `/factory/system_state`:

- para saber que zonas estan bloqueadas por robot activo;
- para comparar realidad visual vs `pipeline.queues`;
- para desbloquear temprano cuando EXPECTED ya dice que una zona esta vacia;
- para no depender de estados fugaces como `PICK_DONE` que duran milisegundos.

### 22.22 Preguntas frecuentes de mantenimiento

**Quiero cambiar una pose de xArm2 al stack. Donde toco?**  
`xarm2_adapter.py`, diccionario `_XARM2_POSITIONS`. Si cambia el tiempo del ciclo de forma relevante, recalibrar simulacion.

**Quiero cambiar decision de robot2. Donde toco?**  
Online: `classification_rules.py`. Offline: `dispatch_search2.py` y posiblemente `beam_search.py`. Si no cambias ambos, el mapa puede optimizar una realidad distinta a la fisica.

**Quiero que el MES muestre otro nombre de work center. Donde toco?**  
`mes_analytics_worker.py` para el mapping `TASK_TO_WC`, y `MES_dashboard.py` si hay orden/colores/canonical names asociados.

**Quiero cambiar el margen de espera del mapa. Donde toco?**  
`factory_supervisor.py`, `MAP_GRACE_SEC`. Si se cambia mucho, documentar porque afecta cuantos `followed` vs `timeout` aparecen.

**Quiero anadir una tabla DB de produccion. Donde toco?**  
`db_writer.py` en `_ddl`, y luego el metodo insert/update correspondiente. Si la lee MES, tocar `MES_dashboard.py` tambien.

**Quiero anadir una accion vendor nueva. Pasos minimos.**

1. Anadir task en `shared/contracts.py` si es task publica.
2. Permitir/usar task en planner.
3. Implementar `handle_task` en vendor supervisor.
4. Implementar funcion en adapter/driver.
5. Publicar STATUS con `resource_state`, `task_state`, `result.code`.
6. Registrar ciclos/DB si afecta produccion.
7. Reflejarlo en simulacion si afecta makespan.

**Quiero depurar por que una pieza se fue mal. Orden recomendado.**

1. `production_run` para run_id/status.
2. `piece` para color/shape esperado inicial.
3. `piece_transfer` para ruta esperada.
4. `vision_detection` para lecturas de camaras.
5. `cycle_event` para orden y fases reales.
6. `command_log` + `status_log` para comando/vendor exacto.
7. `alarm_event` para timeouts, intrusos o map guidance.
8. `docs/dynamic_map_*/README.md` si era corrida validada.

### 22.23 Lo que sigue faltando documentar mejor

Aunque este README ya baja a codigo, hay tres piezas que conviene convertir algun dia en docs separados:

- un documento solo de poses por robot con fotos/layout fisico;
- un documento de calibracion simulacion-vs-real por work center;
- un documento de contratos DB con DDL generado automaticamente desde `db_writer.py` y `information_schema`.

Esto no bloquea entender el sistema, pero ayudaria mucho si el repo se entrega a alguien externo.
