# -*- coding: utf-8 -*-
"""Узел-классификатор: /image/compressed → /model_result.

Внутри onnxruntime, а не ultralytics: ради этого и делался экспорт.

Сообщение — std_msgs/String с JSON внутри. Своё сообщение (.msg) потребовало бы
сборки rosidl и отдельного пакета интерфейсов; на масштабе учебного проекта это
лишняя деталь, а JSON читается глазами прямо в `ros2 topic echo`. В отчёте это
надо назвать осознанным решением, а не упрощением.

    ros2 run birdcls classifier_node --ros-args -p model:=best.onnx
"""
import json, time

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
import cv2
import onnxruntime as ort


class ClassifierNode(Node):
    def __init__(self):
        super().__init__("classifier_node")
        self.declare_parameter("model", "best.onnx")
        self.declare_parameter("classes", "alert,empty,feeding")
        self.declare_parameter("imgsz", 224)
        path = self.get_parameter("model").value
        self.classes = [c.strip() for c in
                        str(self.get_parameter("classes").value).split(",")]
        self.imgsz = int(self.get_parameter("imgsz").value)

        self.sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name
        self.pub = self.create_publisher(String, "/model_result", 10)
        self.sub = self.create_subscription(CompressedImage, "/image/compressed",
                                            self.on_image, 10)
        self.lat = []
        self.get_logger().info(f"модель {path}, классы {self.classes}")

    def square(self, im):
        """Препроцессинг ТОТ ЖЕ, что при обучении: масштаб по короткой стороне
        плюс центральная обрезка.

        Здесь раньше стоял cv2.resize(img, (imgsz, imgsz)): кадр 16:9 сплющивался
        в квадрат, и на вход сети шла сжатая по горизонтали птица — не то, на чём
        модель обучалась. Численная валидация экспорта такое не ловит, она
        сравнивает PyTorch с ONNX на одинаково подготовленном квадрате.
        """
        h, w = im.shape[:2]
        s = self.imgsz / min(h, w)
        im = cv2.resize(im, (round(w * s), round(h * s)))
        H, W = im.shape[:2]
        top, left = (H - self.imgsz) // 2, (W - self.imgsz) // 2
        return im[top:top + self.imgsz, left:left + self.imgsz]

    def on_image(self, msg):
        arr = np.frombuffer(msg.data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None: return
        x = self.square(img)
        x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = x.transpose(2, 0, 1)[None]

        t0 = time.perf_counter()
        out = self.sess.run(None, {self.inp: x})[0][0]
        dt = (time.perf_counter() - t0) * 1000
        self.lat.append(dt)

        p = np.asarray(out, dtype=np.float64)
        if abs(p.sum() - 1.0) > 1e-3:                 # на случай, если экспортированы логиты
            p = np.exp(p - p.max()); p = p / p.sum()

        i = int(p.argmax())
        res = {
            "stamp": msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9,
            "label": self.classes[i],
            "confidence": float(p[i]),
            "probs": {c: round(float(v), 4) for c, v in zip(self.classes, p)},
            "latency_ms": round(dt, 2),
        }
        self.pub.publish(String(data=json.dumps(res, ensure_ascii=False)))
        if len(self.lat) % 50 == 0:
            m = float(np.median(self.lat[-50:]))
            self.get_logger().info(f"кадров {len(self.lat)}, задержка медиана {m:.1f} мс")


def main():
    rclpy.init()
    try:
        rclpy.spin(ClassifierNode())
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
