from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument

DOMAINS = [
    'niryo', 'ufactory', 'laser', 'globalvision',
    'green_conveyors', 'arduino_vacuum', 'bantam',
]


def generate_launch_description():
    actions = [
        Node(package='shipyard_pnp', executable='factory_supervisor', name='factory_supervisor'),
        Node(package='shipyard_pnp', executable='dashboard_node', name='dashboard_node'),
    ]
    for domain_id in DOMAINS:
        actions.append(Node(
            package='shipyard_pnp',
            executable='mock_vendor_supervisor',
            name=f'mock_{domain_id}_vendor_supervisor',
            parameters=[{'domain_id': domain_id, 'sim_delay_sec': 0.05}],
        ))
    return LaunchDescription(actions)
