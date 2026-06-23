from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    niryo_mode = LaunchConfiguration("niryo_mode")
    robot1_namespace = LaunchConfiguration("robot1_namespace")
    robot2_namespace = LaunchConfiguration("robot2_namespace")

    return LaunchDescription([
        DeclareLaunchArgument(
            "niryo_mode",
            default_value="dry_run",
            description="Niryo mode: dry_run or hardware.",
        ),
        DeclareLaunchArgument(
            "robot1_namespace",
            default_value="/robot1",
            description="Robot1 ROS2 namespace.",
        ),
        DeclareLaunchArgument(
            "robot2_namespace",
            default_value="/robot2",
            description="Robot2 ROS2 namespace.",
        ),
        Node(
            package="shipyard_pnp",
            executable="niryo_vendor_supervisor",
            name="niryo_vendor_supervisor",
            output="screen",
            parameters=[{
                "mode": niryo_mode,
                "robot1_namespace": robot1_namespace,
                "robot2_namespace": robot2_namespace,
            }],
        ),
    ])
