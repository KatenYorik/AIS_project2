# -*- coding: utf-8 -*-
"""Все три узла разом.

    ros2 launch birdcls demo.launch.py model:=/путь/best.onnx source:=0
    ros2 launch birdcls demo.launch.py model:=best.onnx source:=clip.mp4 mode:=threshold

Для демонстрации с turtlesim скорости надо публиковать в его топик:

    ros2 launch birdcls demo.launch.py model:=$HOME/best.onnx source:=$HOME/clip.mov \
         cmd_vel:=/turtle1/cmd_vel log:=$HOME/demo_log.csv

Для TurtleBot3 в Gazebo — топик /cmd_vel, но тип TwistStamped:

    ros2 launch birdcls demo.launch.py model:=$HOME/best.onnx source:=$HOME/clip.mov \
         cmd_vel_stamped:=true log:=$HOME/demo_log.csv
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    args = [
        DeclareLaunchArgument("model", default_value="best.onnx"),
        DeclareLaunchArgument("source", default_value="0"),
        DeclareLaunchArgument("fps", default_value="5.0"),
        DeclareLaunchArgument("classes", default_value="alert,empty,feeding"),
        DeclareLaunchArgument("mode", default_value="efe"),
        DeclareLaunchArgument("confusion", default_value=""),
        # Куда публиковать скорости. По умолчанию /cmd_vel; для turtlesim нужен
        # /turtle1/cmd_vel, поэтому топик пробрасывается аргументом, а не правкой кода.
        DeclareLaunchArgument("cmd_vel", default_value="/cmd_vel"),
        # TurtleBot3 в Gazebo (Jazzy) ждёт TwistStamped, а не Twist: на Twist робот
        # молча стоит. По умолчанию false — Twist, как требует задание и turtlesim.
        DeclareLaunchArgument("cmd_vel_stamped", default_value="false"),
        DeclareLaunchArgument("log", default_value=""),
    ]
    return LaunchDescription(args + [
        Node(package="birdcls", executable="camera_publisher", name="camera_publisher",
             output="screen",
             parameters=[{"source": LaunchConfiguration("source"),
                          "fps": LaunchConfiguration("fps")}]),
        Node(package="birdcls", executable="classifier_node", name="classifier_node",
             output="screen",
             parameters=[{"model": LaunchConfiguration("model"),
                          "classes": LaunchConfiguration("classes")}]),
        Node(package="birdcls", executable="controller_node", name="controller_node",
             output="screen",
             parameters=[{"mode": LaunchConfiguration("mode"),
                          "confusion": LaunchConfiguration("confusion"),
                          "cmd_vel": LaunchConfiguration("cmd_vel"),
                          "cmd_vel_stamped": LaunchConfiguration("cmd_vel_stamped"),
                          "log": LaunchConfiguration("log")}]),
    ])
