#!/usr/bin/env bash
# Демонстрация Проекта 2 на turtlesim. Запускать в WSL:
#
#     bash /mnt/c/Users/kkhod/claude/AIS/project2/step8_demo/demo_turtle.sh
#
# Поднимает turtlesim, всю цепочку и панель Gradio; пишет решения в
# ~/demo_log_<время>.csv. Останов — Ctrl+C, гасит всё за собой.
#
# Почему с confusion. Правдоподобие A берётся из измеренной матрицы ошибок
# итоговой модели. Это не украшение: с A, заданной руками, действие approach
# не появляется вовсе, потому что оно требует класса feeding, а итоговая модель
# его почти не предсказывает (6 кадров из 204). Требование задания «не менее
# трёх различных действий» выполняется именно на измеренной A.
# ВНИМАНИЕ: здесь НЕ должно быть `set -u`. Скрипты окружения ROS 2
# (/opt/ros/jazzy/setup.bash и ament) штатно читают необъявленные переменные,
# например AMENT_TRACE_SETUP_FILES, и с `set -u` падают на восьмой строке,
# не дойдя до запуска узлов.

CLIP="${CLIP:-$HOME/clip.mov}"
MODEL="${MODEL:-$HOME/best.onnx}"
CONF="${CONF:-/mnt/c/Users/kkhod/claude/AIS/data/results/pretrain_stage2.json}"
PANEL="${PANEL:-/mnt/c/Users/kkhod/claude/AIS/project2/step7_gradio_panel/gradio_panel.py}"
# Лог — свой на каждый запуск. Контроллер открывает файл на ДОПИСЫВАНИЕ, поэтому
# общее имя склеило бы несколько прогонов в один файл, и сводка в конце считала бы
# их вместе. Имя со временем запуска эту ошибку исключает.
LOG="${LOG:-$HOME/demo_log_$(date +%H%M%S).csv}"

for f in "$CLIP" "$MODEL" "$CONF" "$PANEL"; do
    [ -f "$f" ] || { echo "нет файла: $f"; exit 1; }
done

# Панель слушает порт 7860. Если он занят прошлым запуском, новая панель не
# встанет, а страница будет показывать старую — проверяем заранее.
if ss -ltn | grep -q ':7860 '; then
    echo "порт 7860 занят — висит прошлая панель. Погасить:"
    echo "  pkill -9 -f '[g]radio_panel'"
    exit 1
fi

source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash

PIDS=()
DONE=0
cleanup() {
    # Ctrl+C поднимает INT, затем при выходе ещё и EXIT, поэтому без этого
    # флага сводка печаталась трижды.
    [ "$DONE" = "1" ] && return
    DONE=1
    echo
    echo "=== гашу узлы"
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
    sleep 2
    # gradio на обычный сигнал закрывается медленно и может пережить скрипт,
    # оставив порт 7860 занятым. Добиваем то, что не успело выйти.
    for p in "${PIDS[@]}"; do kill -9 "$p" 2>/dev/null; done
    pkill -9 -f '[g]radio_panel' 2>/dev/null
    if [ -f "$LOG" ]; then
        echo "=== действия за прогон ($LOG)"
        tail -n +2 "$LOG" | cut -d, -f6 | sort | uniq -c
    fi
}
trap cleanup EXIT INT TERM

echo "=== решения пишу в $LOG"
echo "=== turtlesim"
ros2 run turtlesim turtlesim_node &
PIDS+=($!)
sleep 4

echo "=== цепочка: камера -> классификатор -> контроллер"
ros2 launch birdcls demo.launch.py \
     model:="$MODEL" source:="$CLIP" fps:=5.0 \
     cmd_vel:=/turtle1/cmd_vel log:="$LOG" confusion:="$CONF" &
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
Идёт демонстрация. Что должно быть видно на записи:

  * окно turtlesim — черепаха едет, замирает, отъезжает с разворотом;
  * панель — кадр, вероятности, решение, таблица риска и неоднозначности;
  * терминал контроллера — строки «alert (0.99) → ПОДЪЕХАТЬ» с G и риском.

Панель: открыть в браузере НОВУЮ вкладку  http://127.0.0.1:7860
  Если страница пустая — закрыть вкладку и открыть новую. Старая вкладка,
  пережившая перезапуск панели, застревает в переподключении и не
  обновляется, хотя сервер исправен.

Черепаха может доехать до стены и упереться. Сброс, в другом окне:
  ros2 service call /reset std_srvs/srv/Empty

Останов — Ctrl+C.
-------------------------------------------------------------------
TXT

wait
