# -*- coding: utf-8 -*-
"""Узел-издатель: веб-камера или файл → топик /image/compressed.

CompressedImage выбран намеренно: он не требует cv_bridge, которого в свежей
установке ROS 2 часто нет, и кадр летит по шине уже сжатым.

    ros2 run birdcls camera_publisher --ros-args -p source:=0 -p fps:=5.0
    ros2 run birdcls camera_publisher --ros-args -p source:=clip.mp4 -p loop:=true
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import cv2


class CameraPublisher(Node):
    def __init__(self):
        super().__init__("camera_publisher")
        self.declare_parameter("source", "0")
        self.declare_parameter("fps", 5.0)
        self.declare_parameter("loop", True)
        self.declare_parameter("width", 640)
        src = self.get_parameter("source").value
        self.loop = bool(self.get_parameter("loop").value)
        self.width = int(self.get_parameter("width").value)
        fps = float(self.get_parameter("fps").value)

        self.cap = cv2.VideoCapture(int(src) if str(src).isdigit() else str(src))
        if not self.cap.isOpened():
            self.get_logger().error(f"не открылся источник {src}")
            raise SystemExit(1)
        self.pub = self.create_publisher(CompressedImage, "/image/compressed", 10)
        self.timer = self.create_timer(1.0 / fps, self.tick)
        self.n = 0
        self.get_logger().info(f"источник {src}, {fps} кадров/с → /image/compressed")

    def tick(self):
        ok, frame = self.cap.read()
        if not ok:
            if self.loop:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0); return
            self.get_logger().info("источник кончился"); raise SystemExit(0)
        h, w = frame.shape[:2]
        if w > self.width:
            frame = cv2.resize(frame, (self.width, int(h * self.width / w)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok: return
        msg = CompressedImage()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera"
        msg.format = "jpeg"
        msg.data = buf.tobytes()
        self.pub.publish(msg)
        self.n += 1
        if self.n % 50 == 0:
            self.get_logger().info(f"отправлено кадров: {self.n}")


def main():
    rclpy.init()
    try:
        rclpy.spin(CameraPublisher())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
