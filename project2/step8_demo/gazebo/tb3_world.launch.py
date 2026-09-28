#!/usr/bin/env python3
"""TurtleBot3 burger в локальном мире Gazebo (без Fuel).

То же, что turtlebot3_gazebo/empty_world.launch.py, но мир берётся из
аргумента world (по умолчанию worlds/empty_local.sdf рядом с этим файлом).

    TURTLEBOT3_MODEL=burger ros2 launch /mnt/c/Users/kkhod/claude/AIS/project2/step8_demo/gazebo/tb3_world.launch.py
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import AppendEnvironmentVariable, DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

HERE = os.path.dirname(os.path.realpath(__file__))


def generate_launch_description():
    tb3 = get_package_share_directory('turtlebot3_gazebo')
    ros_gz_sim = get_package_share_directory('ros_gz_sim')
    world = LaunchConfiguration('world')

    return LaunchDescription([
        DeclareLaunchArgument('world', default_value=os.path.join(HERE, 'worlds', 'empty_local.sdf')),
        DeclareLaunchArgument('x_pose', default_value='0.0'),
        DeclareLaunchArgument('y_pose', default_value='0.0'),
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', os.path.join(tb3, 'models')),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ros_gz_sim, 'launch', 'gz_sim.launch.py')),
            launch_arguments={'gz_args': ['-r -s -v2 ', world], 'on_exit_shutdown': 'true'}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ros_gz_sim, 'launch', 'gz_sim.launch.py')),
            launch_arguments={'gz_args': '-g -v2 '}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(tb3, 'launch', 'spawn_turtlebot3.launch.py')),
            launch_arguments={'x_pose': LaunchConfiguration('x_pose'),
                              'y_pose': LaunchConfiguration('y_pose')}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(tb3, 'launch', 'robot_state_publisher.launch.py')),
            launch_arguments={'use_sim_time': 'true'}.items()),
    ])
