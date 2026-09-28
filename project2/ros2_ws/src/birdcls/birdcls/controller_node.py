# -*- coding: utf-8 -*-
"""Узел-контроллер: /model_result → /action и /cmd_vel.

Действие выбирается минимизацией ожидаемой свободной энергии (см. efe.py).
Флагом можно переключиться на обычный порог — запасной вариант на день демо.

    ros2 run birdcls controller_node
    ros2 run birdcls controller_node --ros-args -p mode:=threshold -p threshold:=0.6
    ros2 run birdcls controller_node --ros-args -p log:=demo_log.csv
    ros2 run birdcls controller_node --ros-args -p cmd_vel:=/turtle1/cmd_vel

Требование задания (шаг 6): каждый класс отображается в КОМАНДНОЕ СООБЩЕНИЕ.
Поэтому кроме человекочитаемого /action узел публикует geometry_msgs/Twist в
/cmd_vel — это то, что понимает подвижный робот в Gazebo, turtlesim и вообще
любой differential drive. Само отображение задано таблицей MOVE ниже и
документировано в отчёте.

Параметр log пишет поток решений в CSV. Это тот самый «поток поведенческих
проб», под который в графе курса стоит rosbag: только сразу в том виде, который
читают analyse_new.py и hmm_phases.py. Демо и научная часть смыкаются здесь.
"""
import csv, json, os

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from geometry_msgs.msg import Twist, TwistStamped

from birdcls import efe


# Класс поведения птицы -> действие робота -> команда движения.
# Три различных действия — прямое требование задания (не менее трёх).
#   approach  подъехать ближе: птица кормится, можно приблизиться
#   hold      стоять: птица осматривается, лишнее движение её спугнёт
#   retreat   отъехать и отвернуться: птицы нет, точка наблюдения неудачна
MOVE = {
    "approach": (0.20,  0.0),      # линейная скорость м/с, угловая рад/с
    "hold":     (0.00,  0.0),
    "retreat":  (-0.15, 0.6),
}
SAFE = (0.0, 0.0)                  # что делать, когда уверенности не хватает


class ControllerNode(Node):
    def __init__(self):
        super().__init__("controller_node")
        self.declare_parameter("mode", "efe")          # efe | threshold
        self.declare_parameter("threshold", 0.6)
        self.declare_parameter("gamma", 4.0)
        self.declare_parameter("confusion", "")        # results/small.json из train.py
        self.declare_parameter("log", "")              # CSV с потоком решений
        self.mode = str(self.get_parameter("mode").value)
        self.thr = float(self.get_parameter("threshold").value)
        self.gamma = float(self.get_parameter("gamma").value)

        cpath = str(self.get_parameter("confusion").value)
        if cpath:
            try:
                d = json.load(open(cpath, encoding="utf-8"))
                if efe.set_A_from_confusion(d["confusion"], d["labels"]):
                    self.get_logger().info(f"A взята из матрицы ошибок: {cpath}")
                else:
                    self.get_logger().warn("классы в матрице ошибок не совпали, A по умолчанию")
            except Exception as e:
                self.get_logger().warn(f"матрицу ошибок прочитать не вышло: {e}")

        self.declare_parameter("cmd_vel", "/cmd_vel")
        # TurtleBot3 в Gazebo (Jazzy) слушает TwistStamped; Twist он молча
        # игнорирует. По умолчанию — Twist: его требует задание и turtlesim.
        self.declare_parameter("cmd_vel_stamped", False)
        self.declare_parameter("min_confidence", 0.34)
        self.min_conf = float(self.get_parameter("min_confidence").value)

        self.pub = self.create_publisher(String, "/action", 10)
        topic = str(self.get_parameter("cmd_vel").value)
        self.stamped = bool(self.get_parameter("cmd_vel_stamped").value)
        self.pub_cmd = self.create_publisher(TwistStamped if self.stamped else Twist, topic, 10)
        self.get_logger().info(f"команды движения идут в {topic} "
                               f"({'TwistStamped' if self.stamped else 'Twist'})")
        self.sub = self.create_subscription(String, "/model_result", self.on_result, 10)
        self.last = None
        self.logf = None
        lp = str(self.get_parameter("log").value)
        if lp:
            new = not os.path.exists(lp)
            self.logf = open(lp, "a", encoding="utf-8", newline="")
            self.logw = csv.writer(self.logf)
            if new:
                self.logw.writerow(["stamp", "label", "p_feeding", "p_alert",
                                    "p_empty", "action", "confidence",
                                    "risk_best", "ambiguity_best"])
            self.get_logger().info(f"пишу решения в {lp}")
        self.get_logger().info(f"режим: {self.mode}")

    def on_result(self, msg):
        try:
            r = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        qs = [float(r["probs"].get(s, 0.0)) for s in efe.STATES]
        z = sum(qs)
        if z <= 0: return
        qs = [v / z for v in qs]

        d = (efe.choose_threshold(qs, self.thr) if self.mode == "threshold"
             else efe.choose(qs, self.gamma))
        d["label"] = r["label"]
        d["mode"] = self.mode
        d["stamp"] = r.get("stamp")
        self.pub.publish(String(data=json.dumps(d, ensure_ascii=False)))

        # Порог уверенности: ниже него — безопасная команда «стоять».
        # В режиме efe порог не назначен вручную, а выведен из решения, но
        # страховка нужна и здесь: классификатор может быть уверенно неправ.
        lin, ang = MOVE.get(d["action"], SAFE)
        if d["confidence"] < self.min_conf:
            lin, ang = SAFE
            d["action"] = d["action"] + " (ниже порога → стоп)"
        if self.stamped:
            t = TwistStamped()
            t.header.stamp = self.get_clock().now().to_msg()
            t.header.frame_id = "base_footprint"
            v = t.twist
        else:
            t = v = Twist()
        v.linear.x = float(lin); v.angular.z = float(ang)
        self.pub_cmd.publish(t)

        if self.logf:
            b = d["action"]
            self.logw.writerow([r.get("stamp"), r["label"],
                                round(qs[0], 4), round(qs[1], 4), round(qs[2], 4),
                                b, round(d["confidence"], 3),
                                d["risk"].get(b, ""), d["ambiguity"].get(b, "")])
            self.logf.flush()

        if d["action"] != self.last:                   # печатаем только смену действия
            self.last = d["action"]
            if self.mode == "efe":
                self.get_logger().info(
                    f"{r['label']} ({r['confidence']:.2f}) → {d['action_ru'].upper()}  "
                    f"G={d['G']}  риск={d['risk']}")
            else:
                self.get_logger().info(
                    f"{r['label']} ({r['confidence']:.2f}) → {d['action_ru'].upper()}")


def main():
    rclpy.init()
    try:
        rclpy.spin(ControllerNode())
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
