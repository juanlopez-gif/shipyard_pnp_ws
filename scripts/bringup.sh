#!/usr/bin/env bash
# bringup.sh — Arranca el sistema completo Shipyard P&P
#
# Uso:
#   ./scripts/bringup.sh                          # hardware completo
#   ./scripts/bringup.sh ufactory_mode:=dry_run   # sin mover los xArms
#   ./scripts/bringup.sh niryo_mode:=dry_run       # sin mover los Niryos

set -eo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "============================================================"
echo "  SHIPYARD P&P — BRINGUP"
echo "============================================================"
echo ""
echo "Prerrequisitos manuales antes de continuar:"
echo "  1. Encender el laser y verificar que está en posición inicial."
echo "  2. Conectar y calibrar los dos Niryos en Niryo Studio (hasta que estén en verde)."
echo "  3. Habilitar los dos xArms en UFactory Studio."
echo "  4. Verificar que el Arduino vacuum está conectado en /dev/ttyACM1."
echo "  5. Verificar que los green conveyors están conectados en /dev/ttyACM0."
echo "  6. Verificar que la Raspberry Pi de la puerta Bantam está encendida."
echo ""
echo "IPs de los robots:"
echo "  xArm1:   192.168.0.254"
echo "  xArm2:   192.168.0.168"
echo "  Niryo1:  192.168.0.195"
echo "  Niryo2:  192.168.0.244"
echo "  Laser:   192.168.0.173"
echo "  Puerta:  192.168.0.171"
echo "============================================================"
echo ""

# ── Directorios de logs ───────────────────────────────────────────────────────
mkdir -p "$REPO_ROOT/runtime_logs/ros"
export ROS_LOG_DIR="$REPO_ROOT/runtime_logs/ros"
LOG_FILE="$REPO_ROOT/runtime_logs/full_system_$(date +%Y%m%d_%H%M%S).txt"
echo "Log guardado en: $LOG_FILE"
echo ""

# ── Limpiar variables de entorno ROS anteriores ───────────────────────────────
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH ROS_PACKAGE_PATH

# ── Source workspaces en orden ────────────────────────────────────────────────
set +u
source /opt/ros/jazzy/setup.bash
source /home/isecapstone/ros2_ws/install/setup.bash         # conveyor3_driver, door_controller
source /home/isecapstone/dev_ws/install/setup.bash          # xarm_msgs, xarm_api, uf_ros_lib
source /home/isecapstone/ros2_drivers_ws/install/setup.bash # niryo_ned_ros2_interfaces
source "$REPO_ROOT/install/setup.bash"                       # shipyard_pnp
set -u

cd "$REPO_ROOT"

# ── Build ─────────────────────────────────────────────────────────────────────
echo "Compilando shipyard_pnp..."
colcon build --packages-select shipyard_pnp --symlink-install 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: colcon build falló. Abortando."
    exit 1
fi
set +u
source "$REPO_ROOT/install/setup.bash"
set -u
echo ""

# ── Lanzar ───────────────────────────────────────────────────────────────────
ros2 launch shipyard_pnp pnp_full_system.launch.py "$@" 2>&1 | tee "$LOG_FILE"
