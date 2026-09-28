#!/usr/bin/env bash
# Демонстрация Проекта 2 в Gazebo на TurtleBot3 burger. Запускать в WSL:
#
#     bash /mnt/c/Users/kkhod/claude/AIS/project2/step8_demo/demo_gazebo.sh
#
# Поднимает Gazebo с роботом, всю цепочку и панель Gradio; пишет решения в
# ~/demo_gz_log_<время>.csv. Останов — Ctrl+C, гасит всё за собой, включая Gazebo.
#
# Отличия от demo_turtle.sh:
#   * мир свой, gazebo/worlds/empty_local.sdf: штатный empty_world тянет землю и
#     солнце из интернета (Fuel) и без сети не запускается;
#   * контроллер с cmd_vel_stamped:=true — TurtleBot3 в Jazzy слушает
#     geometry_msgs/TwistStamped, на обычный Twist молча стоит;
#   * камера GUI следует за роботом (/gui/follow), иначе он уедет из кадра.
# confusion — как в turtlesim: только с измеренной A есть все три действия.
# ВНИМАНИЕ: здесь НЕ должно быть `set -u` (падает setup.bash ROS 2).

HERE=/mnt/c/Users/kkhod/claude/AIS/project2/step8_demo
CLIP="${CLIP:-$HOME/clip.mov}"
MODEL="${MODEL:-$HOME/best.onnx}"
CONF="${CONF:-/mnt/c/Users/kkhod/claude/AIS/data/results/pretrain_stage2.json}"
PANEL="${PANEL:-/mnt/c/Users/kkhod/claude/AIS/project2/step7_gradio_panel/gradio_panel.py}"
WORLD_LAUNCH="${WORLD_LAUNCH:-$HERE/gazebo/tb3_world.launch.py}"
# Контроллер дописывает лог, поэтому имя своё на каждый запуск.
LOG="${LOG:-$HOME/demo_gz_log_$(date +%H%M%S).csv}"

for f in "$CLIP" "$MODEL" "$CONF" "$PANEL" "$WORLD_LAUNCH"; do
    [ -f "$f" ] || { echo "нет файла: $f"; exit 1; }
done

if ss -ltn | grep -q ':7860 '; then
    echo "порт 7860 занят — висит прошлая панель. Погасить:"
    echo "  pkill -9 -f '[g]radio_panel'"
    exit 1
fi
# Окна WSL на этой машине бывают пустыми и прозрачными: WSLg при старте не открыл
# общую память и перешёл в режим копирования (в заголовке [WARN:COPY MODE]).
# Случается не при каждом старте WSL; лечится только перезапуском WSL.
if grep -q 'rdp_allocate_shared_memory: Failed' /mnt/wslg/weston.log 2>/dev/null; then
    echo "WSLg запущен в режиме копирования — окно Gazebo будет пустым."
    echo "В PowerShell:  wsl --shutdown   и запустить этот скрипт заново."
    exit 1
fi
# Второй Gazebo поверх первого даст два робота на одних топиках.
if pgrep -f '[g]z sim' > /dev/null; then
    echo "Gazebo уже запущен. Погасить:"
    echo "  pkill -9 -f '[g]z sim'; pkill -f '[p]arameter_bridge'; pkill -f '[r]obot_state_publisher'"
    exit 1
fi

source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
export TURTLEBOT3_MODEL=burger
# launch-файл мира лежит на /mnt/c — не мусорить там __pycache__.
export PYTHONDONTWRITEBYTECODE=1

odom_pos() {
    timeout 6 ros2 topic echo /odom --once --field pose.pose 2>/dev/null \
        | grep -A3 -E 'position|orientation' | tr '\n' ' ' | sed 's/  */ /g'
    echo
}

PIDS=()
DONE=0
cleanup() {
    [ "$DONE" = "1" ] && return
    DONE=1
    echo
    echo "=== поза робота в конце (/odom): $(odom_pos)"
    echo "=== гашу узлы"
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
    sleep 2
    for p in "${PIDS[@]}"; do kill -9 "$p" 2>/dev/null; done
    pkill -9 -f '[g]radio_panel' 2>/dev/null
    # GUI Gazebo на SIGINT не выходит (launch ждёт 5 с и шлёт SIGTERM) — добиваем.
    pkill -f '[p]arameter_bridge' 2>/dev/null
    pkill -f '[r]obot_state_publisher' 2>/dev/null
    pkill -9 -f '[g]z sim' 2>/dev/null
    if [ -f "$LOG" ]; then
        echo "=== действия за прогон ($LOG)"
        tail -n +2 "$LOG" | cut -d, -f6 | sort | uniq -c
    fi
}
trap cleanup EXIT INT TERM

echo "=== решения пишу в $LOG"
echo "=== Gazebo + TurtleBot3 burger (лог: /tmp/gz_demo.log)"
ros2 launch "$WORLD_LAUNCH" > /tmp/gz_demo.log 2>&1 &
PIDS+=($!)
for i in $(seq 1 40); do
    gz model --list 2>/dev/null | grep -q burger && break
    sleep 3
done
if ! gz model --list 2>/dev/null | grep -q burger; then
    echo "робот не появился за 120 с — см. /tmp/gz_demo.log"
    exit 1
fi
echo "=== робот на месте: $(odom_pos)"

echo "=== камера следует за роботом"
gz service -s /gui/follow/offset --reqtype gz.msgs.Vector3d --reptype gz.msgs.Boolean \
   --timeout 5000 --req 'x: -0.45, y: -0.3, z: 0.3' > /dev/null
gz service -s /gui/follow --reqtype gz.msgs.StringMsg --reptype gz.msgs.Boolean \
   --timeout 5000 --req 'data: "burger"' > /dev/null

echo "=== цепочка: камера -> классификатор -> контроллер (TwistStamped в /cmd_vel)"
ros2 launch birdcls demo.launch.py \
     model:="$MODEL" source:="$CLIP" fps:=5.0 \
     cmd_vel:=/cmd_vel cmd_vel_stamped:=true log:="$LOG" confusion:="$CONF" &
PIDS+=($!)
sleep 6

echo "=== панель Gradio (лог: /tmp/panel_demo.log)"
python3 "$PANEL" --mode ros > /tmp/panel_demo.log 2>&1 &
PIDS+=($!)
for i in $(seq 1 30); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7860/)" = "200" ] && break
    sleep 2
done

cat <<'TXT'

-------------------------------------------------------------------
Идёт демонстрация в Gazebo. Что должно быть видно на записи:

  * окно Gazebo Sim — TurtleBot3 едет вперёд, замирает, отъезжает
    назад с разворотом; камера следует за ним;
  * панель — кадр, вероятности, решение, таблица риска и неоднозначности;
  * терминал контроллера — строки «alert (0.99) → ПОДЪЕХАТЬ» с G и риском.

Панель: открыть в браузере НОВУЮ вкладку  http://127.0.0.1:7860

Окно Gazebo не видно — оно под другими окнами (Alt+Tab, «Gazebo Sim»).
Окно есть, но пустое/прозрачное и в заголовке [WARN:COPY MODE] —
сломался показ окон WSL: Ctrl+C здесь, в PowerShell `wsl --shutdown`,
запустить заново.

Вернуть робота в центр, в другом окне WSL:
  gz service -s /world/default/set_pose --reqtype gz.msgs.Pose \
     --reptype gz.msgs.Boolean --timeout 3000 \
     --req 'name: "burger", position: {x: 0, y: 0, z: 0.01}'

Останов — Ctrl+C.
-------------------------------------------------------------------
TXT

wait
