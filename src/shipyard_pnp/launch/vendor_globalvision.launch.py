from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    camera_index = LaunchConfiguration("globalvision_camera_index")
    camera_device = LaunchConfiguration("globalvision_camera_device")
    config_file = LaunchConfiguration("globalvision_config_file")
    color_threshold = LaunchConfiguration("globalvision_color_threshold_pct")
    show_window = LaunchConfiguration("globalvision_show_window")

    return LaunchDescription([
        DeclareLaunchArgument(
            "globalvision_camera_index",
            default_value="0",
            description="OpenCV camera index for the global stack camera.",
        ),
        DeclareLaunchArgument(
            "globalvision_camera_device",
            default_value="",
            description="Optional explicit camera device path, e.g. /dev/video2.",
        ),
        DeclareLaunchArgument(
            "globalvision_config_file",
            default_value="",
            description="ROI config file. Empty uses package config/globalvision_rois.yaml.",
        ),
        DeclareLaunchArgument(
            "globalvision_color_threshold_pct",
            default_value="5.0",
            description="Minimum HSV color percentage for a slot to be occupied.",
        ),
        DeclareLaunchArgument(
            "globalvision_show_window",
            default_value="true",
            description="Show the GlobalVision preview window from the vendor process.",
        ),
        Node(
            package="shipyard_pnp",
            executable="globalvision_vendor_supervisor",
            name="globalvision_vendor_supervisor",
            output="screen",
            parameters=[{
                "camera_index": camera_index,
                "camera_device": camera_device,
                "config_file": config_file,
                "color_threshold_pct": color_threshold,
                "show_window": ParameterValue(show_window, value_type=bool),
            }],
        ),
    ])
