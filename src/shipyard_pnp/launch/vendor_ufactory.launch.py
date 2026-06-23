from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    mode = LaunchConfiguration("ufactory_mode")
    xarm1_namespace = LaunchConfiguration("xarm1_namespace")
    xarm2_namespace = LaunchConfiguration("xarm2_namespace")

    return LaunchDescription([
        DeclareLaunchArgument(
            "ufactory_mode",
            default_value="dry_run",
            description="UFactory mode: dry_run or hardware.",
        ),
        DeclareLaunchArgument(
            "xarm1_namespace",
            default_value="/xarm1",
            description="ROS2 namespace for xArm1 services.",
        ),
        DeclareLaunchArgument(
            "xarm2_namespace",
            default_value="/xarm2",
            description="ROS2 namespace for xArm2 services.",
        ),
        Node(
            package="shipyard_pnp",
            executable="ufactory_vendor_supervisor",
            name="ufactory_vendor_supervisor",
            output="screen",
            parameters=[{
                "mode": mode,
                "xarm1_namespace": xarm1_namespace,
                "xarm2_namespace": xarm2_namespace,
            }],
        ),
    ])
