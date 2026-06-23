from setuptools import setup
from glob import glob

package_name = 'shipyard_pnp'

setup(
    name=package_name,
    version='0.0.1',
    packages=[
        'shipyard_pnp',
        'shipyard_pnp.shared',
        'shipyard_pnp.factory',
        'shipyard_pnp.factory.planner',
        'shipyard_pnp.nodes',
        'shipyard_pnp.vendors',
        'shipyard_pnp.vendors.common',
        'shipyard_pnp.vendors.niryo',
        'shipyard_pnp.vendors.ufactory',
        'shipyard_pnp.vendors.laser',
        'shipyard_pnp.vendors.globalvision',
        'shipyard_pnp.vendors.green_conveyors',
        'shipyard_pnp.vendors.arduino_vacuum',
        'shipyard_pnp.vendors.bantam',
    ],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='isecapstone',
    maintainer_email='lossuperlopezoli@gmail.com',
    description='Shipyard 4.0 MVP2 — Plug-and-Plan coordination architecture',
    license='MIT',
    entry_points={
        'console_scripts': [
            # Factory layer
            'factory_supervisor = shipyard_pnp.factory.factory_supervisor:main',
            'dashboard_node = shipyard_pnp.nodes.dashboard_node:main',
            # Vendor supervisors
            'niryo_vendor_supervisor = shipyard_pnp.vendors.niryo.niryo_vendor_supervisor:main',
            'ufactory_vendor_supervisor = shipyard_pnp.vendors.ufactory.ufactory_vendor_supervisor:main',
            'ufactory_parallel_test = shipyard_pnp.vendors.ufactory.ufactory_parallel_test:main',
            'laser_vendor_supervisor = shipyard_pnp.vendors.laser.laser_vendor_supervisor:main',
            'globalvision_vendor_supervisor = shipyard_pnp.vendors.globalvision.globalvision_vendor_supervisor:main',
            'globalvision_preview = shipyard_pnp.vendors.globalvision.globalvision_preview:main',
            'green_conveyors_vendor_supervisor = shipyard_pnp.vendors.green_conveyors.green_conveyors_vendor_supervisor:main',
            'arduino_vacuum_vendor_supervisor = shipyard_pnp.vendors.arduino_vacuum.arduino_vacuum_vendor_supervisor:main',
            'bantam_vendor_supervisor = shipyard_pnp.vendors.bantam.bantam_vendor_supervisor:main',
            # Testing / simulation
            'mock_vendor_supervisor = shipyard_pnp.vendors.common.mock_vendor_supervisor:main',
        ],
    },
)
