from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    port = LaunchConfiguration("green_conveyor_serial_port")
    baudrate = LaunchConfiguration("green_conveyor_serial_baud")
    conveyor4_speed = LaunchConfiguration("green_conveyor_a_speed")
    conveyor3_speed = LaunchConfiguration("green_conveyor_b_speed")
    conveyor4_direction = LaunchConfiguration("green_conveyor_a_direction")
    conveyor3_direction = LaunchConfiguration("green_conveyor_b_direction")
    startup_wait = LaunchConfiguration("green_conveyor_startup_wait")
    command_timeout = LaunchConfiguration("green_conveyor_command_timeout")
    inter_command_delay = LaunchConfiguration("green_conveyor_inter_command_delay")
    max_retries = LaunchConfiguration("green_conveyor_max_retries")

    return LaunchDescription([
        DeclareLaunchArgument(
            "green_conveyor_serial_port",
            default_value="/dev/ttyACM0",
            description="Shared serial port for the Arduino controlling conveyors 3 and 4.",
        ),
        DeclareLaunchArgument(
            "green_conveyor_serial_baud",
            default_value="115200",
            description="Shared serial baud rate for the green conveyor Arduino.",
        ),
        DeclareLaunchArgument(
            "green_conveyor_a_speed",
            default_value="9000",
            description="Default speed for conveyor4 / Arduino channel A.",
        ),
        DeclareLaunchArgument(
            "green_conveyor_b_speed",
            default_value="9000",
            description="Default speed for conveyor3 / Arduino channel B.",
        ),
        DeclareLaunchArgument(
            "green_conveyor_a_direction",
            default_value="FWD",
            description="Default direction for conveyor4 / Arduino channel A.",
        ),
        DeclareLaunchArgument(
            "green_conveyor_b_direction",
            default_value="REV",
            description="Default direction for conveyor3 / Arduino channel B.",
        ),
        DeclareLaunchArgument(
            "green_conveyor_startup_wait",
            default_value="2.0",
            description="Seconds to wait after opening serial before reading startup output.",
        ),
        DeclareLaunchArgument(
            "green_conveyor_command_timeout",
            default_value="2.0",
            description="Seconds to wait for each Arduino ACK.",
        ),
        DeclareLaunchArgument(
            "green_conveyor_inter_command_delay",
            default_value="0.3",
            description="Delay between serial boot/configuration commands.",
        ),
        DeclareLaunchArgument(
            "green_conveyor_max_retries",
            default_value="5",
            description="Maximum retries per serial command.",
        ),
        Node(
            package="shipyard_pnp",
            executable="green_conveyors_vendor_supervisor",
            name="green_conveyors_vendor_supervisor",
            output="screen",
            parameters=[{
                "port": port,
                "baudrate": baudrate,
                "startup_wait_sec": startup_wait,
                "command_timeout_sec": command_timeout,
                "inter_command_delay_sec": inter_command_delay,
                "reconnect_attempts": max_retries,
                "conveyor3_speed": conveyor3_speed,
                "conveyor4_speed": conveyor4_speed,
                "conveyor3_direction": conveyor3_direction,
                "conveyor4_direction": conveyor4_direction,
            }],
        ),
    ])
