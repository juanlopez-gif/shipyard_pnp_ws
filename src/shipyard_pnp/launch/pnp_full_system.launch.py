import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    niryo_mode          = LaunchConfiguration('niryo_mode')
    ufactory_mode       = LaunchConfiguration('ufactory_mode')
    globalvision_device = LaunchConfiguration('globalvision_camera_device')
    globalvision_window = LaunchConfiguration('globalvision_show_window')

    xarm_api_share   = get_package_share_directory('xarm_api')
    lite6_driver     = os.path.join(xarm_api_share, 'launch', 'lite6_driver.launch.py')

    niryo_driver_share = get_package_share_directory('niryo_ned_ros2_driver')
    niryo_driver       = os.path.join(niryo_driver_share, 'launch', 'driver.launch.py')

    return LaunchDescription([
        # ── launch args ──────────────────────────────────────────────────────
        DeclareLaunchArgument('niryo_mode',    default_value='hardware'),
        DeclareLaunchArgument('ufactory_mode', default_value='hardware'),
        DeclareLaunchArgument('globalvision_camera_device', default_value='/dev/video0'),
        DeclareLaunchArgument('globalvision_show_window',   default_value='true'),

        # ── Niryo ROS2 driver (must start before niryo_vendor_supervisor) ────
        # Reads robot IPs and namespaces from drivers_list.yaml in the package.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(niryo_driver),
            condition=IfCondition(PythonExpression(["'", niryo_mode, "' == 'hardware'"])),
        ),

        # ── xArm ROS2 drivers (must start before ufactory_vendor_supervisor) ─
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(lite6_driver),
            launch_arguments={'robot_ip': '192.168.0.254', 'hw_ns': 'xarm1'}.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(lite6_driver),
            launch_arguments={'robot_ip': '192.168.0.168', 'hw_ns': 'xarm2'}.items(),
        ),

        # ── vendor supervisors ───────────────────────────────────────────────
        Node(
            package='shipyard_pnp',
            executable='niryo_vendor_supervisor',
            name='niryo_vendor_supervisor',
            parameters=[{'mode': niryo_mode}],
        ),
        Node(
            package='shipyard_pnp',
            executable='ufactory_vendor_supervisor',
            name='ufactory_vendor_supervisor',
            parameters=[{'mode': ufactory_mode}],
        ),
        Node(package='shipyard_pnp', executable='laser_vendor_supervisor',         name='laser_vendor_supervisor'),
        Node(
            package='shipyard_pnp',
            executable='globalvision_vendor_supervisor',
            name='globalvision_vendor_supervisor',
            parameters=[{
                'camera_device': globalvision_device,
                'show_window': ParameterValue(globalvision_window, value_type=bool),
            }],
        ),
        Node(package='shipyard_pnp', executable='green_conveyors_vendor_supervisor', name='green_conveyors_vendor_supervisor'),
        Node(package='shipyard_pnp', executable='arduino_vacuum_vendor_supervisor',  name='arduino_vacuum_vendor_supervisor'),
        Node(package='shipyard_pnp', executable='bantam_vendor_supervisor',          name='bantam_vendor_supervisor'),

        # ── factory layer ────────────────────────────────────────────────────
        Node(package='shipyard_pnp', executable='factory_supervisor', name='factory_supervisor'),
        Node(package='shipyard_pnp', executable='dashboard_node',     name='dashboard_node'),
    ])
