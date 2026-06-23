# Vendor-Agnostic ROS Testbed - Guia de experimentos y tests

Este README convierte los experimentos del paper `Plug-and-Plan: A Minimal Coordination Interface for Vendor-Agnostic Orchestration of Heterogeneous Industrial Systems` en una especificacion practica para implementar los tests en este u otro repositorio.

La idea no es solo describir el paper. La idea es que otro repo pueda tomar este documento y crear:

- los YAML de registro y ACL;
- los probes que intentan violar la frontera;
- los analyzers de rosbag/CSV;
- los criterios de pass/fail;
- las tablas finales de resultados.

El contrato experimental que se quiere validar es:

```text
Factory Supervisor -> /{vendor}_factory/command -> Vendor Supervisor
Vendor Supervisor -> /{vendor}_factory/ack     -> Factory Supervisor
Vendor Supervisor -> /{vendor}_factory/status  -> Factory Supervisor
```

Todo lo interno del vendor, como topics de robots, SDKs, serial, HTTP, registers, GPIO, servicios ROS especificos o datos propietarios, debe quedarse dentro del Vendor Supervisor.

---

## 1. Resultado esperado del otro repositorio

El otro repositorio debe poder generar esta estructura minima:

```text
.
|-- config/
|   |-- vendor_registry.yaml
|   `-- topic_acl.yaml
|-- experiments/
|   |-- boundary_enforcement/
|   |   |-- run_probe.py
|   |   `-- analyze_boundary_results.py
|   |-- vendor_substitutability/
|   |   |-- analyze_modification_scope.py
|   |   |-- analyze_peer_intervals.py
|   |   `-- analyze_first_cycle.py
|   `-- coordination_overhead/
|       `-- analyze_rosbag.py
|-- tools/
|   `-- check_three_topic_contract.py
|-- results/
|   |-- bags/
|   |-- experiment_1_boundary_enforcement/
|   |-- experiment_2_vendor_substitutability/
|   `-- experiment_3_coordination_overhead/
`-- README_EXPERIMENTS.md
```

En este repo, las referencias actuales estan en:

```text
shipyard_plug_and_plan/config/vendor_registry.yaml
shipyard_plug_and_plan/config/topic_acl.yaml
shipyard_plug_and_plan/ARCHITECTURE_PLAN.md
```

Nota importante: varios archivos de `shipyard_plug_and_plan/shipyard_pnp/` y `shipyard_plug_and_plan/test/` existen como esqueleto, pero aun estan vacios. Por eso este README funciona como contrato de implementacion de tests.

---

## 2. Arquitectura bajo prueba

### 2.1 Dominios vendor

El testbed Plug-and-Plan de este repo define siete dominios:

| Domain ID | Vendor Supervisor | Recursos internos |
|---|---|---|
| `niryo` | `niryo_vendor_supervisor` | `robot1`, `robot2`, `conveyor1`, `conveyor2`, sensores IR, vision local, vacuum Niryo de robot2 |
| `ufactory` | `ufactory_vendor_supervisor` | `xarm1`, `xarm2` |
| `laser` | `laser_vendor_supervisor` | laser |
| `globalvision` | `globalvision_vendor_supervisor` | camara global e inventario semantico |
| `green_conveyors` | `green_conveyors_vendor_supervisor` | conveyors 3 y 4 por Arduino |
| `arduino_vacuum` | `arduino_vacuum_vendor_supervisor` | vacuum Arduino de robot1 |
| `bantam` | `bantam_vendor_supervisor` | Bantam CNC y puerta |

### 2.2 Registro de vendors

El archivo base es:

```text
shipyard_plug_and_plan/config/vendor_registry.yaml
```

Contenido esperado:

```yaml
domains:
  niryo:
    supervisor_node: niryo_vendor_supervisor
    resources:
      robot1: {type: robot, model: niryo_ned2}
      robot2: {type: robot, model: niryo_ned2, internal_vacuum: robot2_niryo_vacuum}
      conveyor1: {type: niryo_conveyor, ir_sensors: [c1s1, c1s2]}
      conveyor2: {type: niryo_conveyor, ir_sensors: [c2s1, c2s2]}
      vision_robot1: {type: local_camera, owner_robot: robot1}
      vision_robot2: {type: local_camera, owner_robot: robot2}
      robot2_niryo_vacuum: {type: niryo_tool, owner_robot: robot2}

  ufactory:
    supervisor_node: ufactory_vendor_supervisor
    resources:
      xarm1: {type: robot, model: lite6}
      xarm2: {type: robot, model: lite6}

  laser:
    supervisor_node: laser_vendor_supervisor
    resources:
      laser: {type: machine}

  globalvision:
    supervisor_node: globalvision_vendor_supervisor
    resources:
      globalvision_camera: {type: camera}

  green_conveyors:
    supervisor_node: green_conveyors_vendor_supervisor
    resources:
      conveyor3: {type: arduino_conveyor, channel: A}
      conveyor4: {type: arduino_conveyor, channel: B}

  arduino_vacuum:
    supervisor_node: arduino_vacuum_vendor_supervisor
    resources:
      arduino_vacuum: {type: serial_vacuum, owner_robot: robot1}

  bantam:
    supervisor_node: bantam_vendor_supervisor
    resources:
      bantam: {type: cnc}
      bantam_door: {type: door}
```

### 2.3 ACL de topics

Este es el YAML que define a que topics puede publicar y de que topics puede leer cada nodo. Es el artefacto central del Experimento 1.

Archivo base:

```text
shipyard_plug_and_plan/config/topic_acl.yaml
```

Contenido esperado:

```yaml
nodes:
  factory_supervisor:
    publishes:
      - /niryo_factory/command
      - /ufactory_factory/command
      - /laser_factory/command
      - /globalvision_factory/command
      - /green_conveyors_factory/command
      - /arduino_vacuum_factory/command
      - /bantam_factory/command
      - /factory/system_state
    subscribes:
      - /niryo_factory/ack
      - /niryo_factory/status
      - /ufactory_factory/ack
      - /ufactory_factory/status
      - /laser_factory/ack
      - /laser_factory/status
      - /globalvision_factory/ack
      - /globalvision_factory/status
      - /green_conveyors_factory/ack
      - /green_conveyors_factory/status
      - /arduino_vacuum_factory/ack
      - /arduino_vacuum_factory/status
      - /bantam_factory/ack
      - /bantam_factory/status

  niryo_vendor_supervisor:
    subscribes: [/niryo_factory/command]
    publishes: [/niryo_factory/ack, /niryo_factory/status]

  ufactory_vendor_supervisor:
    subscribes: [/ufactory_factory/command]
    publishes: [/ufactory_factory/ack, /ufactory_factory/status]

  laser_vendor_supervisor:
    subscribes: [/laser_factory/command]
    publishes: [/laser_factory/ack, /laser_factory/status]

  globalvision_vendor_supervisor:
    subscribes: [/globalvision_factory/command]
    publishes: [/globalvision_factory/ack, /globalvision_factory/status]

  green_conveyors_vendor_supervisor:
    subscribes: [/green_conveyors_factory/command]
    publishes: [/green_conveyors_factory/ack, /green_conveyors_factory/status]

  arduino_vacuum_vendor_supervisor:
    subscribes: [/arduino_vacuum_factory/command]
    publishes: [/arduino_vacuum_factory/ack, /arduino_vacuum_factory/status]

  bantam_vendor_supervisor:
    subscribes: [/bantam_factory/command]
    publishes: [/bantam_factory/ack, /bantam_factory/status]
```

Regla de interpretacion:

- `publishes` es allowlist de topics que el nodo puede publicar.
- `subscribes` es allowlist de topics que el nodo puede leer.
- Si un source/destination no aparece en el ACL, el mensaje se rechaza.
- Si el publish se fuerza a nivel DDS/ROS2, el receptor tambien debe validar y dropear el mensaje.

---

## 3. Mensajes que deben usar los tests

Los experimentos asumen `std_msgs/String` con payload JSON. Cada mensaje debe tener identificadores estables para poder unir comando, ack y status.

### 3.1 Command

```json
{
  "schema": "shipyard.pnp.command.v1",
  "command_id": "CMD-niryo-robot1-20260617T183000123456Z-000001",
  "correlation_id": "CYCLE-PIECE_001-0001",
  "sender_id": "factory_supervisor",
  "domain_id": "niryo",
  "resource_id": "robot1",
  "task": "MOVE_PIECE",
  "piece_id": "PIECE_001",
  "source": "C3",
  "target": "FINAL_RED_STACK",
  "route": "C3_TO_FINAL_RED",
  "parameters": {},
  "issued_at": "2026-06-17T18:30:00.123456Z",
  "t_published_ns": 0,
  "nonce": "hex",
  "auth": "hmac-sha256-hex"
}
```

### 3.2 Ack

```json
{
  "schema": "shipyard.pnp.ack.v1",
  "command_id": "CMD-niryo-robot1-20260617T183000123456Z-000001",
  "correlation_id": "CYCLE-PIECE_001-0001",
  "sender_id": "niryo_vendor_supervisor",
  "domain_id": "niryo",
  "resource_id": "robot1",
  "accepted": true,
  "reason": null,
  "accepted_at": "2026-06-17T18:30:00.223456Z",
  "t_published_ns": 0,
  "t_received_ns": 0,
  "nonce": "hex",
  "auth": "hmac-sha256-hex"
}
```

### 3.3 Status

```json
{
  "schema": "shipyard.pnp.status.v1",
  "command_id": "CMD-niryo-robot1-20260617T183000123456Z-000001",
  "correlation_id": "CYCLE-PIECE_001-0001",
  "sender_id": "niryo_vendor_supervisor",
  "domain_id": "niryo",
  "resource_id": "robot1",
  "task": "MOVE_PIECE",
  "task_state": "COMPLETED",
  "resource_state": "PLACE_DONE",
  "piece_id": "PIECE_001",
  "source": "C3",
  "target": "FINAL_RED_STACK",
  "route": "C3_TO_FINAL_RED",
  "result": {"code": "OK"},
  "published_at": "2026-06-17T18:30:07.223456Z",
  "t_published_ns": 0,
  "t_received_ns": 0,
  "nonce": "hex",
  "auth": "hmac-sha256-hex"
}
```

### 3.4 Datos prohibidos en la frontera

Estos campos no deben cruzar la frontera Factory/Vendor:

```text
joint
joint_states
angle
servo
register
gpio
pin
raw_image
image
frame
hsv
mask
contour
roi_pixels
gcode_line
serial_bytes
tool_torque
motor_current
```

Excepcion permitida: resultados semanticos de coordinacion. Por ejemplo, `color`, `shape`, `slot_id`, `occupied` y `confidence` son validos si representan el resultado de una tarea, no detalles internos del algoritmo.

---

## 4. Setup comun antes de correr experimentos

### 4.1 Preparar ROS2

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
```

### 4.2 Verificar grafo ROS2

```bash
ros2 node list
ros2 topic list
ros2 topic list | grep '_factory'
```

Para un sistema completo, deben existir estos tres topics por vendor:

```text
/{vendor}_factory/command
/{vendor}_factory/ack
/{vendor}_factory/status
```

### 4.3 Crear directorios de resultados

```bash
mkdir -p results/bags
mkdir -p results/experiment_1_boundary_enforcement
mkdir -p results/experiment_2_vendor_substitutability
mkdir -p results/experiment_3_coordination_overhead
```

### 4.4 Grabacion base con rosbag

```bash
ros2 bag record -o results/bags/full_vendor_run \
  /niryo_factory/command /niryo_factory/ack /niryo_factory/status \
  /ufactory_factory/command /ufactory_factory/ack /ufactory_factory/status \
  /laser_factory/command /laser_factory/ack /laser_factory/status \
  /globalvision_factory/command /globalvision_factory/ack /globalvision_factory/status \
  /green_conveyors_factory/command /green_conveyors_factory/ack /green_conveyors_factory/status \
  /arduino_vacuum_factory/command /arduino_vacuum_factory/ack /arduino_vacuum_factory/status \
  /bantam_factory/command /bantam_factory/ack /bantam_factory/status
```

---

## 5. Experimento 1 - Boundary Enforcement

### 5.1 Pregunta que valida

Valida:

- RQ2, proprietary confinement: datos internos del vendor no cruzan la frontera.
- RQ4, fault containment: un vendor o nodo externo no puede afectar directamente a otro vendor.

Hipotesis:

```text
Unauthorized messages sent: 200 per sub-experiment
Unauthorized messages acted upon: 0
ACL latency: sub-millisecond
```

### 5.2 Diseno comun

Cada sub-experimento envia:

- 100 mensajes en modo secuencial;
- 100 mensajes en modo batch;
- 200 mensajes totales.

Cada intento debe producir una fila CSV:

```csv
case,mode,message_id,source_node,destination_topic,allowed,acted_upon,acl_latency_us,rejection_reason,timestamp_ns
```

Definiciones:

- `allowed`: `true` si el ACL permite publicar/recibir ese mensaje.
- `acted_upon`: `true` si el receptor ejecuto alguna accion fisica/logica por ese mensaje.
- `acl_latency_us`: tiempo de validacion ACL, no tiempo fisico de robot.
- `rejection_reason`: por ejemplo `TOPIC_NOT_ALLOWED`, `NO_TOKEN`, `BAD_HMAC`, `PROPRIETARY_FIELD`.

### 5.3 Probe requerido

Implementar:

```text
experiments/boundary_enforcement/run_probe.py
```

CLI esperada:

```bash
python3 experiments/boundary_enforcement/run_probe.py \
  --case <case_name> \
  --source <source_node_id> \
  --destination <topic> \
  --sequential 100 \
  --batch 100 \
  --out <csv_path>
```

El probe debe usar el mismo ACL wrapper que usara el sistema real. Un `ros2 topic pub` manual sirve para debug, pero no debe ser el test final si salta la validacion ACL.

### 5.4 Experimento 1(a) - Cross-vendor direct access

Objetivo: demostrar que un vendor no puede comandar directamente a otro vendor.

Accion: un probe del dominio `bantam` intenta publicar directamente al topic de frontera de `niryo`, saltandose al Factory Supervisor. Esto simula un vendor intentando coordinar a otro vendor sin pasar por el unico punto de control autorizado.

Adaptacion respecto al paper: el paper usa `agv_vendor_probe -> /robot_8/command` sobre un testbed de 11 robots con dominio AGV. En este testbed de 7 dominios (niryo, ufactory, laser, globalvision, green_conveyors, arduino_vacuum, bantam), el equivalente es `bantam_vendor_probe` intentando publicar a un topic de frontera de otro vendor. El ACL no incluye ninguna regla `bantam -> /niryo_factory/command`, por lo que el rechazo es equivalente.

Ejemplo:

```bash
python3 experiments/boundary_enforcement/run_probe.py \
  --case cross_vendor_access \
  --source bantam_vendor_probe \
  --destination /niryo_factory/command \
  --sequential 100 \
  --batch 100 \
  --out results/experiment_1_boundary_enforcement/cross_vendor_access.csv
```

Topics internos adicionales que tambien se pueden usar como destino para verificar que tampoco son accesibles:

```text
/robot1/command
/robot2/command
/xarm1/command
/xarm2/command
```

Criterio de pass:

- el ACL rechaza la publicacion;
- el intento queda logueado;
- si el publish se fuerza a bajo nivel, el receptor dropea el mensaje;
- ningun robot/vendor actua sobre el payload;
- no se publica ack de exito.

Resultado reportado en el paper:

| Metric | Value |
|---|---:|
| Messages sent | 200 |
| Messages acted upon | 0 |
| Sequential ACL latency | 0.82 us |
| Batch ACL latency | 5.97 us |

### 5.5 Experimento 1(b1) - External injection without token

Objetivo: demostrar que un nodo externo no registrado no puede publicar a un topic de coordinacion sin token.

Accion:

```bash
python3 experiments/boundary_enforcement/run_probe.py \
  --case external_no_token \
  --source external_probe \
  --destination /niryo_factory/command \
  --token none \
  --sequential 100 \
  --batch 100 \
  --out results/experiment_1_boundary_enforcement/external_no_token.csv
```

Criterio de pass:

- el ACL rechaza antes de computar HMAC;
- el vendor no recibe un comando ejecutable;
- no se publica ack/status para ese comando no autorizado.

Resultado reportado en el paper:

| Metric | Value |
|---|---:|
| Messages sent | 200 |
| Messages acted upon | 0 |
| Sequential ACL latency | 0.43 us |
| Batch ACL latency | 3.51 us |

### 5.6 Experimento 1(b2) - External injection with forged token

Objetivo: demostrar que un token HMAC-SHA256 falso se rechaza.

Accion:

```bash
python3 experiments/boundary_enforcement/run_probe.py \
  --case external_forged_token \
  --source external_probe \
  --destination /niryo_factory/command \
  --token forged \
  --sequential 100 \
  --batch 100 \
  --out results/experiment_1_boundary_enforcement/external_forged_token.csv
```

Criterio de pass:

- el receptor calcula el HMAC esperado;
- el token falso falla comparacion;
- el mensaje se rechaza;
- ningun vendor actua sobre el payload.

Resultado reportado en el paper:

| Metric | Value |
|---|---:|
| Messages sent | 200 |
| Messages acted upon | 0 |
| Sequential ACL latency | 14.92 us |
| Batch ACL latency | 43.06 us |

La latencia es mayor que en 1(b1) porque aqui si se calcula HMAC antes del rechazo.

### 5.7 Experimento 1(c) - Vendor-to-factory proprietary leakage

Objetivo: demostrar que datos propietarios internos de un vendor no pueden cruzar la frontera aunque el topic de destino sea valido (Theorem 3).

Diseño: el `niryo_vendor_supervisor` publica a su propio topic de status (`/niryo_factory/status`), que SÍ esta en su allowlist de ACL. Lo que se bloquea es el CONTENIDO: el payload incluye `joint_states`, una clave prohibida. El rechazo ocurre en la Gate 4 (boundary key check), no en la Gate 3 (ACL). Esto es lo que diferencia este sub-experimento de 1(a): aqui el ACL pasa y es el validator de payload el que intercepta la fuga.

```bash
python3 experiments/boundary_enforcement/run_probe.py \
  --case vendor_to_factory_leakage \
  --source niryo_vendor_supervisor \
  --destination /niryo_factory/status \
  --payload-type joint_angles \
  --sequential 100 \
  --batch 100 \
  --out results/experiment_1_boundary_enforcement/vendor_to_factory_leakage.csv
```

Criterio de pass:

- el ACL permite la publicacion (el vendor SÍ puede publicar a su status topic);
- el boundary key check rechaza el payload por contener `joint_states`;
- `rejection_reason == PROPRIETARY_FIELD`;
- `acted_upon == 0`;
- ningun dato interno de articulaciones llega al Factory Supervisor.

Resultado reportado en el paper:

| Metric | Value |
|---|---:|
| Messages sent | 200 |
| Messages acted upon | 0 |
| Sequential ACL latency | 11.91 us |
| Batch ACL latency | 18.18 us |

### 5.8 Experimento 1(d) - Factory-to-vendor proprietary leakage

Objetivo: demostrar que el Factory Supervisor no puede incrustar datos propietarios del vendor en un comando aunque el topic de destino sea valido (Theorem 3).

Diseño: el `factory_supervisor` publica a `/niryo_factory/command`, que SÍ esta en su allowlist de ACL. El payload contiene `parameters.servo`, una clave prohibida. El rechazo ocurre en Gate 4 (boundary key check). Si el payload estuviera limpio, el mensaje se aceptaria normalmente.

```bash
python3 experiments/boundary_enforcement/run_probe.py \
  --case factory_to_vendor_leakage \
  --source factory_supervisor \
  --destination /niryo_factory/command \
  --payload-type servo_data \
  --sequential 100 \
  --batch 100 \
  --out results/experiment_1_boundary_enforcement/factory_to_vendor_leakage.csv
```

Criterio de pass:

- el ACL permite la publicacion (factory_supervisor SÍ puede publicar comandos a niryo);
- el boundary key check rechaza el payload por contener `servo` o `register`;
- `rejection_reason == PROPRIETARY_FIELD`;
- `acted_upon == 0`;
- no llega ningun dato propietario del vendor a traves del canal de comando.

Resultado reportado en el paper:

| Metric | Value |
|---|---:|
| Messages sent | 200 |
| Messages acted upon | 0 |
| Sequential ACL latency | 7.66 us |
| Batch ACL latency | 13.10 us |

### 5.9 Resultado global del Experimento 1

| Sub-experiment | Teorema | Sent | Acted upon | Sequential latency (us) | Batch latency (us) |
|---|---|---:|---:|---:|---:|
| Cross-vendor access | Theorem 2 | 200 | 0 | 0.82 | 5.97 |
| External, no token | Theorem 2 | 200 | 0 | 0.43 | 3.51 |
| External, forged token | Theorem 2 | 200 | 0 | 14.92 | 43.06 |
| Vendor-to-factory leakage | Theorem 3 | 200 | 0 | 11.91 | 18.18 |
| Factory-to-vendor leakage | Theorem 3 | 200 | 0 | 7.66 | 13.10 |

Conclusion esperada:

```text
Unauthorized messages acted upon: 0
ACL latency range: 0.43 us to 43.06 us
All ACL checks remained sub-millisecond
```

---

## 6. Experimento 2 - Vendor Substitutability

### 6.1 Pregunta que valida

Valida RQ3: un vendor nuevo se puede agregar sin modificar vendors existentes ni logica central del Factory Supervisor.

Hipotesis:

```text
Peer vendor domains changed: 0 files, 0 lines
Factory Supervisor coordination logic changed: 0 files, 0 lines
New vendor registration entry changed: 1 entry
New vendor communicates through command -> ack -> status from first contact
Peer vendor cadence is not meaningfully affected before/after T_launch
```

### 6.2 Experimento 2(a) - Modification scope

Objetivo: medir el alcance del cambio al agregar un vendor nuevo.

Procedimiento:

```bash
git status
git checkout -b exp2_vendor_addition
```

Agregar:

1. un nuevo `*_vendor_supervisor`;
2. un entry nuevo en `config/vendor_registry.yaml`;
3. tres topics nuevos en `config/topic_acl.yaml`;
4. launch entry para el nuevo vendor, si aplica.

Luego:

```bash
git diff --numstat main...HEAD > results/experiment_2_vendor_substitutability/modification_scope_raw.txt
```

El analyzer debe clasificar cada archivo cambiado:

```csv
component,files_changed,lines_changed
new_vendor_supervisor,XX,XX
new_vendor_registration_entry,1,XX
new_vendor_acl_entry,1,XX
peer_vendor_domains,0,0
factory_supervisor_coordination_logic,0,0
```

Implementar:

```text
experiments/vendor_substitutability/analyze_modification_scope.py
```

Reglas de clasificacion:

- `shipyard_pnp/vendors/<new_vendor>/...` cuenta como `new_vendor_supervisor`.
- `config/vendor_registry.yaml` cuenta como `new_vendor_registration_entry`.
- `config/topic_acl.yaml` cuenta como `new_vendor_acl_entry`.
- `shipyard_pnp/vendors/<existing_vendor>/...` cuenta como `peer_vendor_domains`.
- `shipyard_pnp/factory/factory_supervisor.py`, planner o `vendor_client.py` cuentan como `factory_supervisor_coordination_logic`.

Criterio de pass:

- peer vendor domains: 0 files, 0 lines;
- Factory Supervisor coordination logic: 0 files, 0 lines;
- el cambio global obligatorio se limita al registro/ACL;
- el vendor nuevo mantiene el mismo contrato de 3 topics.

Estado de resultado del paper:

| Component | Files changed | Lines changed |
|---|---:|---:|
| New Vendor Supervisor | [XX] | [XX] |
| New vendor registration entry | 1 | [XX] |
| Peer vendor domains, all | 0 | 0 |
| Factory Supervisor | 0 | 0 |

Los valores `[XX]` deben llenarse despues de la corrida real.

### 6.3 Experimento 2(b) - Operational continuity

Objetivo: demostrar que los vendors existentes siguen funcionando mientras se lanza el vendor nuevo.

Procedimiento:

1. Arrancar flujo de produccion continuo con vendors existentes.
2. Iniciar rosbag antes de lanzar el nuevo vendor.
3. Guardar `T_launch`.
4. Lanzar el nuevo Vendor Supervisor.
5. Continuar hasta que el nuevo vendor complete su primer task.
6. Comparar intervalos de status de los vendors existentes antes y despues de `T_launch`.

Rosbag recomendado:

```bash
ros2 bag record -o results/bags/exp2_vendor_substitution \
  /niryo_factory/status \
  /ufactory_factory/status \
  /new_vendor_factory/command \
  /new_vendor_factory/ack \
  /new_vendor_factory/status
```

Guardar `T_launch`:

```bash
date +%s%N | tee results/experiment_2_vendor_substitutability/T_launch_ns.txt
```

Lanzar vendor:

```bash
ros2 launch <new_vendor_package> <new_vendor_supervisor_launch_file>.py
```

Implementar:

```text
experiments/vendor_substitutability/analyze_peer_intervals.py
```

Calculo:

```text
interval_i = timestamp(status_i) - timestamp(status_i-1)
mean_interval_before_T_launch = mean(intervals where status_i < T_launch)
mean_interval_after_T_launch = mean(intervals where status_i >= T_launch)
difference = after - before
```

CSV esperado:

```csv
vendor,mean_interval_before_s,mean_interval_after_s,difference_s,status_count_before,status_count_after
niryo,XX,XX,XX,XX,XX
ufactory,XX,XX,XX,XX,XX
```

Criterio de pass:

- vendors existentes siguen publicando status despues de `T_launch`;
- no se requiere restart de vendors existentes;
- no hay pausa significativa atribuible al lanzamiento;
- no hay comandos directos entre vendors.

Estado de resultado del paper:

| Vendor | Mean interval before T_launch (s) | Mean interval after T_launch (s) | Difference (s) |
|---|---:|---:|---:|
| Niryo | [XX] | [XX] | [XX] |
| Lite6/UFactory | [XX] | [XX] | [XX] |

### 6.4 Experimento 2(c) - First coordination cycle

Objetivo: demostrar que el vendor nuevo funciona desde el primer contacto usando solo `command`, `ack` y `status`.

Desde el rosbag de 2(b), extraer:

```text
T_cmd    = timestamp del primer command al vendor nuevo
T_ack    = timestamp del primer ack correspondiente
T_status = timestamp del primer status terminal correspondiente
```

Implementar:

```text
experiments/vendor_substitutability/analyze_first_cycle.py
```

Calculos:

```text
command_to_ack_ms = T_ack - T_cmd
ack_to_status_ms = T_status - T_ack
command_to_status_ms = T_status - T_cmd
```

CSV esperado:

```csv
phase,elapsed_from_Tcmd_ms
command_to_acknowledgment,XX
acknowledgment_to_status,XX
command_to_status,XX
```

Criterio de pass:

- existe un command hacia el vendor nuevo;
- existe un ack con el mismo `command_id`;
- existe un status terminal con el mismo `command_id`;
- no se necesita un cuarto topic;
- no se modifica ningun peer vendor.

Estado de resultado del paper:

| Phase | Elapsed from T_cmd (ms) |
|---|---:|
| Command to acknowledgment | [XX] |
| Acknowledgment to status | [XX] |
| Command to status | [XX] |

---

## 7. Experimento 3 - Coordination Overhead

### 7.1 Pregunta que valida

Valida RQ5: el overhead de coordinacion queda acotado por tres mensajes por task vendor.

Hipotesis:

```text
T_coord = T_cmd + T_ack + T_status
```

Donde:

```text
T_cmd    = command published by FS -> command received by VS
T_ack    = ack published by VS -> ack received by FS
T_status = status published by VS -> status received by FS
```

Para `k` dominios concurrentes y `n` tasks por dominio:

```text
T_total = k * n * T_coord
```

### 7.2 Datos requeridos

Grabar una corrida con todos los vendors activos:

```bash
ros2 bag record -o results/bags/exp3_coordination_overhead \
  /niryo_factory/command /niryo_factory/ack /niryo_factory/status \
  /ufactory_factory/command /ufactory_factory/ack /ufactory_factory/status \
  /laser_factory/command /laser_factory/ack /laser_factory/status \
  /globalvision_factory/command /globalvision_factory/ack /globalvision_factory/status \
  /green_conveyors_factory/command /green_conveyors_factory/ack /green_conveyors_factory/status \
  /arduino_vacuum_factory/command /arduino_vacuum_factory/ack /arduino_vacuum_factory/status \
  /bantam_factory/command /bantam_factory/ack /bantam_factory/status
```

Cada payload debe traer:

- `command_id`;
- `domain_id`;
- `resource_id`;
- `t_published_ns`;
- `t_received_ns`, si el wrapper lo puede anadir;
- estado terminal en `status.task_state`.

### 7.3 Analyzer requerido

Implementar:

```text
experiments/coordination_overhead/analyze_rosbag.py
```

CLI esperada:

```bash
python3 experiments/coordination_overhead/analyze_rosbag.py \
  --bag results/bags/exp3_coordination_overhead \
  --vendors niryo ufactory laser globalvision green_conveyors arduino_vacuum bantam \
  --out results/experiment_3_coordination_overhead/coordination_latencies.csv \
  --summary results/experiment_3_coordination_overhead/coordination_summary.csv
```

Procedimiento:

1. leer mensajes de command/ack/status;
2. parsear JSON;
3. agrupar por `(domain_id, command_id)`;
4. descartar ciclos incompletos o reportarlos como error;
5. calcular `T_cmd`, `T_ack`, `T_status`, `T_coord`;
6. unir con tiempo fisico de task si esta disponible;
7. calcular overhead porcentual.

CSV por ciclo:

```csv
vendor,resource_id,command_id,T_cmd_ms,T_ack_ms,T_status_ms,T_coord_ms,physical_task_time_s,overhead_percent
niryo,robot1,CMD-001,XX,XX,XX,XX,XX,XX
```

CSV resumen:

```csv
message,mean_ms,std_ms,min_ms,max_ms,count
command_dispatch_Tcmd,XX,XX,XX,XX,XX
acknowledgment_receipt_Tack,XX,XX,XX,XX,XX
status_receipt_Tstatus,XX,XX,XX,XX,XX
total_Tcoord_per_task,XX,XX,XX,XX,XX
```

Criterio de pass:

- cada task analizada tiene exactamente 1 command, 1 ack y 1 status terminal;
- `T_coord` esta en milisegundos;
- la ejecucion fisica esta en segundos;
- overhead porcentual es pequeno frente al ciclo fisico;
- aumentar complejidad interna del vendor no agrega nuevos topics de coordinacion.

Estado de resultado del paper:

| Message | Mean (ms) | Std (ms) |
|---|---:|---:|
| Command dispatch, T_cmd | [XX] | [XX] |
| Acknowledgment receipt, T_ack | [XX] | [XX] |
| Status receipt, T_status | [XX] | [XX] |
| Total T_coord per task | [XX] | [XX] |

Pendiente:

```text
T_coord on physical testbed = [XX] ms
Physical task execution range = [XX] s to [XX] s
Coordination overhead = [XX] %
```

---

## 8. Verificacion estatica opcional - RQ1

RQ1 se responde formalmente en el paper, pero conviene crear un check estatico para evitar que el repo viole el contrato.

Implementar:

```text
tools/check_three_topic_contract.py
```

CLI esperada:

```bash
python3 tools/check_three_topic_contract.py \
  --registry config/vendor_registry.yaml \
  --acl config/topic_acl.yaml \
  --out results/three_topic_contract_check.csv
```

El check debe validar:

- cada vendor en `vendor_registry.yaml` tiene exactamente 3 topics de frontera;
- el Factory Supervisor publica solo `/{vendor}_factory/command` para cada vendor;
- el Factory Supervisor se subscribe solo a `/{vendor}_factory/ack` y `/{vendor}_factory/status`;
- cada Vendor Supervisor se subscribe solo a su command;
- cada Vendor Supervisor publica solo ack/status;
- no aparecen topics internos como `/robot1/command`, `/xarm1/set_servo_angle`, `/laser/private`, `/serial_bytes`, etc. como frontera.

CSV esperado:

```csv
vendor,command_topic,ack_topic,status_topic,extra_boundary_topics,pass,reason
niryo,/niryo_factory/command,/niryo_factory/ack,/niryo_factory/status,0,true,
```

---

## 9. Tests unitarios minimos a generar

Estos tests son la version automatizable de los experimentos.

### 9.1 `test_vendor_registry.py`

Debe validar:

- `domains` existe;
- cada domain tiene `supervisor_node`;
- cada domain tiene `resources`;
- no hay resource duplicado en dos domains salvo excepcion documentada;
- cada domain puede mapear a un topic prefix `/{domain}_factory`.

### 9.2 `test_acl.py`

Debe validar:

- `factory_supervisor` solo publica commands y `system_state`;
- `factory_supervisor` solo lee ack/status;
- cada vendor lee exactamente un command;
- cada vendor publica exactamente ack y status;
- no hay publish directo vendor-to-vendor;
- no hay topic interno en `publishes` o `subscribes`.

### 9.3 `test_proprietary_confinement.py`

Debe validar:

- payloads con claves prohibidas se rechazan;
- payloads semanticos permitidos pasan;
- `result.color`, `result.shape`, `result.slot_id`, `result.occupied` son validos si son resultado de tarea;
- `raw_image`, `roi_pixels`, `hsv`, `gcode_line`, `serial_bytes`, `joint_states` son invalidos.

### 9.4 `test_messages.py`

Debe validar:

- command, ack y status tienen `schema`;
- `command_id` es obligatorio;
- `domain_id` y `resource_id` son obligatorios;
- ack/status deben referenciar un `command_id` existente;
- status terminal debe usar `COMPLETED`, `FAILED`, `REJECTED`, `TIMEOUT` o `CANCELED`.

### 9.5 `test_resource_routing.py`

Debe validar:

- `domain_id` determina el topic vendor;
- `resource_id` queda dentro del vendor;
- el Factory Supervisor no enruta por topic interno;
- robot1 y robot2 pertenecen a `niryo`;
- xarm1 y xarm2 pertenecen a `ufactory`;
- vacuum Arduino de robot1 pertenece a `arduino_vacuum`, no a `niryo`.

---

## 10. Checklist final de reporte

### Experimento 1

- [ ] 100 mensajes secuenciales por sub-experimento
- [ ] 100 mensajes batch por sub-experimento
- [ ] 200 mensajes totales por sub-experimento
- [ ] latencia ACL por mensaje
- [ ] `acted_upon = 0` para todos los mensajes no autorizados
- [ ] logs de violaciones guardados
- [ ] tabla resumen generada

### Experimento 2

- [ ] diff scope guardado
- [ ] nuevo Vendor Supervisor contado separado
- [ ] vendor registry contado separado
- [ ] topic ACL contado separado
- [ ] peer vendor domains con 0 archivos y 0 lineas modificadas
- [ ] Factory Supervisor coordination logic con 0 archivos y 0 lineas modificadas
- [ ] `T_launch` guardado
- [ ] rosbag antes/durante/despues del launch
- [ ] intervalos peer antes/despues calculados
- [ ] primer ciclo command/ack/status del vendor nuevo extraido

### Experimento 3

- [ ] rosbag con todos los vendors activos
- [ ] command/ack/status matcheados por `command_id`
- [ ] `T_cmd`, `T_ack`, `T_status` y `T_coord` calculados
- [ ] media, std, min, max y count calculados
- [ ] tiempo fisico de task medido
- [ ] overhead porcentual calculado

---

## 11. Como interpretar resultados

La arquitectura queda soportada si:

1. ningun mensaje no autorizado es ejecutado;
2. los datos internos del vendor no cruzan la frontera;
3. un vendor nuevo se agrega sin tocar vendors existentes;
4. el Factory Supervisor no necesita conocer topics internos;
5. el vendor nuevo completa un ciclo `command -> ack -> status`;
6. el overhead de coordinacion queda en milisegundos mientras las tareas fisicas estan en segundos.

La arquitectura queda cuestionada si:

- un vendor comanda directamente a otro vendor;
- el Factory Supervisor necesita un topic interno para coordinar;
- agregar un vendor obliga a modificar otros vendors;
- agregar un vendor obliga a reescribir la logica central del Factory Supervisor;
- una tarea necesita un cuarto topic de frontera;
- los datos propietarios aparecen en command/ack/status;
- `T_coord` escala con la complejidad interna del vendor y no solo con la cantidad de ciclos de coordinacion.

---

## 12. Resumen corto para portar a otro repo

Para portar estos experimentos, copiar primero:

```text
config/vendor_registry.yaml
config/topic_acl.yaml
README_EXPERIMENTS.md
```

Luego implementar en este orden:

1. parser de `vendor_registry.yaml`;
2. parser y validator de `topic_acl.yaml`;
3. builder/validator de mensajes command/ack/status;
4. `tools/check_three_topic_contract.py`;
5. tests unitarios de ACL, registry, messages y proprietary confinement;
6. `experiments/boundary_enforcement/run_probe.py`;
7. analyzers de Experimento 2;
8. analyzer de Experimento 3.

El primer resultado que debe poder reproducirse es el Experimento 1:

```text
200 unauthorized messages per sub-experiment
0 unauthorized messages acted upon
ACL latency sub-millisecond
```

Despues se completan los `[XX]` de Experimentos 2 y 3 con rosbags del testbed real.
