# Шаг 4. Архитектура ROS 2

**Задание.** Выбрать, где работает вывод: **вне** ROS 2 (скрипт сам читает датчик и
публикует результат) или **внутри** (узел подписан на топик датчика). Нужны как минимум
топик результата и узел-контроллер. Перечислить все топики, обосновать выбор, описать
путь данных от датчика до исполнителя.

## Что выбрано — внутри ROS 2

Отдельный узел подписан на топик с кадрами, выполняет ONNX и публикует результат. Так
камера, модель и контроллер заменяются независимо, а любой топик можно записать
(`ros2 bag`) или прослушать.

```
 камера / файл
      │
┌────────────────┐ /image/compressed ┌─────────────────┐ /model_result ┌─────────────────┐ /cmd_vel ┌──────────┐
│camera_publisher│ ────────────────► │ classifier_node │ ────────────► │ controller_node │ ───────► │  робот   │
└────────────────┘ CompressedImage   │   onnxruntime   │ String (JSON) │   argmin G(u)   │  Twist   │turtlesim │
                                     └─────────────────┘               └─────────────────┘          └──────────┘
        └──────────────────────────────────────┴──────────────────────────────┴── /action ──► gradio_panel
```

| топик | тип | публикует | подписаны |
|---|---|---|---|
| `/image/compressed` | `sensor_msgs/CompressedImage` (JPEG) | `camera_publisher` | `classifier_node`, `gradio_panel` |
| `/model_result` | `std_msgs/String`, JSON | `classifier_node` | `controller_node`, `gradio_panel` |
| `/action` | `std_msgs/String`, JSON | `controller_node` | `gradio_panel` |
| `/cmd_vel` (для turtlesim — `/turtle1/cmd_vel`) | `geometry_msgs/Twist` | `controller_node` | робот |

**Путь данных:** кадр → JPEG в `/image/compressed` → декодирование, квадрат 224×224, ONNX →
класс, уверенность и вероятности в `/model_result` → выбор действия → `Twist` в `/cmd_vel`
и объяснение решения в `/action` → панель показывает всё.

**Два сознательных упрощения.**

- `CompressedImage` вместо `Image` — не нужен `cv_bridge`, которого часто нет в свежей
  установке; кадр идёт по шине уже сжатым.
- `String` с JSON вместо своего типа сообщения — свой `.msg` потребовал бы отдельного
  пакета интерфейсов. JSON читается глазами в `ros2 topic echo`.

## Пакет `birdcls`

Лежит в **`project2\ros2_ws\src\birdcls\`**, а не в папке этого шага: пакет один на шаги
4–6, и `colcon` собирает его целиком.

| файл | что |
|---|---|
| `package.xml`, `setup.py` | метаданные пакета ament_python, три исполняемых узла |
| `setup.cfg` | `install_scripts=$base/lib/birdcls` — **не удалять** |
| `launch/demo.launch.py` | три узла одной командой |
| `birdcls/camera_publisher.py` | шаг 5 |
| `birdcls/classifier_node.py` | шаг 5 |
| `birdcls/controller_node.py`, `birdcls/efe.py` | шаг 6 |

**Аргументы launch-файла:** `model`, `source`, `fps`, `classes`, `mode`, `confusion`,
`cmd_vel`, `log`.

**Ошибка, которую уже совершали.** `ros2 run` отвечал «No executable found» при успешной
сборке: colcon не передал setuptools `--install-scripts`, и узлы легли в
`install/birdcls/bin/` вместо `install/birdcls/lib/birdcls/`. Диагностика:
`ros2 pkg executables birdcls` пусто, а `build/birdcls/birdcls.egg-info/entry_points.txt`
полон — значит, дело в путях, а не в `setup.py`. Лечение — `setup.cfg`.

## Как собрать и запустить

WSL, Ubuntu 24.04, ROS 2 Jazzy. Собирается **копия** пакета в `~/ros2_ws`:

```bash
cp -r /mnt/c/Users/kkhod/claude/AIS/project2/ros2_ws/src/birdcls ~/ros2_ws/src/
cp /mnt/c/Users/kkhod/claude/AIS/data/runs/classify/pretrain_stage2/weights/best.onnx ~/
cd ~/ros2_ws && source /opt/ros/jazzy/setup.bash && colcon build --packages-select birdcls
source install/setup.bash && ros2 pkg executables birdcls    # три строки

ros2 launch birdcls demo.launch.py model:=$HOME/best.onnx source:=$HOME/clip.mov \
     confusion:=/mnt/c/Users/kkhod/claude/AIS/data/results/pretrain_stage2.json log:=$HOME/log.csv
ros2 topic list
ros2 topic echo /model_result
ros2 topic hz /image/compressed
```

После правки исходников в `project2\ros2_ws\` — снова `cp` и `colcon build`. 14.09.2026
копия в `~/ros2_ws` совпадает с исходниками.

**Отчёт:** раздел 4.
