# Поведение птицы: от разметки кадров до робота в Gazebo

Курсовой проект курса **AIS (Artificial Intelligence Software)**, МФТИ, 2026.
Автор — Ходарева Екатерина.

Собственная архивная съёмка птиц у кормушки размечена по кадрам. На ней дообучен классификатор YOLO (Проект 1), а в Проекте 2 он в формате ONNX управляет роботом через ROS 2: turtlesim и TurtleBot3 в Gazebo.

## Ссылки

| что | где |
|---|---|
| Отчёт Проекта 2 | [`ОТЧЁТ_ПРОЕКТ2.ru.md`](../ОТЧЁТ_ПРОЕКТ2.ru.md) |
| Видео: | [`Gazebo`](https://disk.yandex.ru/i/6hXkftSC0-i1Ig), [`turtlesim`](https://disk.yandex.ru/i/_ALIfJuvEu08dw) |
| ClearML, проект | [`AIS-birds`](https://app.clear.ml/projects/c2fb292e6f5d4d98a248152756f16684/experiments/87432635605b4483a312f63b277e30e1/output/execution) |
| Итоговая модель ONNX | [`data/runs/classify/pretrain_stage2/weights/best.onnx`](../data/runs/classify/pretrain_stage2/weights/best.onnx) |


## Главное

**Проект 2.** Цепочка `camera_publisher → classifier_node (onnxruntime) → controller_node →
/cmd_vel`, панель Gradio. Контроллер выбирает действие — подъехать, стоять, отъехать —
минимизацией ожидаемой свободной энергии, с порогом уверенности. ONNX совпадает с PyTorch
до 2·10⁻⁶. Демонстрация — все три действия в turtlesim и в Gazebo Sim 8 с TurtleBot3.

## Устройство репозитория

Папки шагов названы по разделам заданий. В каждой — `README.md`: что требует задание,
что сделано, файлы, команды, числа.

```
project1/                  Проект 1 — классификатор
  step1_task … step8_deployment_demo
project2/                  Проект 2 — ROS 2, ONNX, Gradio, Gazebo
  ros2_ws/src/birdcls/     пакет ROS 2
  step1_task_design … step8_demo
scientific_question/       научная часть поверх той же разметки
common/aispaths.py         где лежат данные; все скрипты работают через него
data/                      разметка, метрики, журналы демо, итоговый ONNX
```

**Чего нет в репозитории** — кадров, собранных датасетов, весов `.pt` и видео. Датасеты
версионируются в ClearML (`birds` 1.0.0 и 2.0.0), видео — по ссылкам выше.

## Запуск

Python 3.11, ultralytics, onnxruntime, gradio, clearml (`common/setup_windows.ps1`), WSL, Ubuntu 24.04, ROS 2 Jazzy (`common/УСТАНОВКА.ru.md`).

```bash
bash project2/step8_demo/demo_gazebo.sh                  # Gazebo + цепочка + панель
bash project2/step8_demo/demo_turtle.sh                  # то же в turtlesim
```

Пути в аргументах скриптов считаются от `data/` (см. `common/README.md`).



# Проект 2 — управление роботом по выходу модели в ROS 2

Модель из Проекта 1 в формате ONNX работает внутри узла ROS 2. Контроллер переводит
класс сцены в движение робота, панель Gradio показывает поток вживую, демонстрация — в
симуляторе. Задание — `AIS\notes\projects\pr02-inference-in-the-loop.md`, 15 % оценки.

**Отчёт:** [`ОТЧЁТ_ПРОЕКТ2.ru.md`](ОТЧЁТ_ПРОЕКТ2.ru.md), 12 разделов.
Не заполнены группа, ссылки и раздел про Gazebo.
**Архитектура и решения:** [`PROJECT2.ru.md`](PROJECT2.ru.md) — документ 31.08, часть
путей в нём старые.

## Шаги

| шаг | папка | что сделано | статус |
|---|---|---|---|
| 1 | [`step1_task_design`](../project2/step1_task_design/README.md) | класс → действие: подъехать / стоять / отъехать | готово |
| 2 | [`step2_model`](../project2/step2_model/README.md) | итоговая модель Проекта 1, accuracy 0.510, macro-F1 0.402 | готово |
| 3 | [`step3_onnx_export`](../project2/step3_onnx_export/README.md) | экспорт и сверка: расхождение 2.15·10⁻⁶, 0 смен класса | готово |
| 4 | [`step4_ros2_architecture`](../project2/step4_ros2_architecture/README.md) | узел внутри ROS 2, пакет `birdcls`, 4 топика | готово |
| 5 | [`step5_inference_node`](../project2/step5_inference_node/README.md) | `classifier_node`: onnxruntime, 5 Гц | готово |
| 6 | [`step6_controller`](../project2/step6_controller/README.md) | `controller_node`: ожидаемая свободная энергия + порог уверенности | готово |
| 7 | [`step7_gradio_panel`](../project2/step7_gradio_panel/README.md) | панель: кадр, вероятности, решение, разложение G | готово |
| 8 | [`step8_demo`](../project2/step8_demo/README.md) | turtlesim: видео записано, три действия; Gazebo — отдельный чат | готово |

## Где что лежит, кроме шагов

- **`ros2_ws\src\birdcls\`** — пакет ROS 2. Он один на шаги 4, 5 и 6 и не делится по
  папкам: `colcon` собирает пакет целиком. Узлы и описание — в README шагов 4–6.
- Данные и модель — `AIS\data\`.

## Цепочка

```
camera_publisher ─/image/compressed─► classifier_node ─/model_result─► controller_node ─/cmd_vel─► робот
                    CompressedImage     onnxruntime      String/JSON      argmin G(u)       Twist
                                                                               └─/action─► gradio_panel
```

## Главное в числах

- ONNX: 2.15·10⁻⁶, 0 из 60 смен класса, 6,0 мс против 18,6 мс.
- Записанный прогон на turtlesim: 861 решение, approach 617 / retreat 212 / hold 32.
- **Три действия появляются только с измеренной матрицей ошибок.** С правдоподобием,
  заданным руками, «подъехать» не возникает: модель не выдаёт `feeding`.
- Контроллер меняет действие **48 раз в минуту**, птица — 20.

## Как запускать

Windows, из `C:\Users\kkhod\claude\AIS` (пути в аргументах от `AIS\data\`):

```powershell
python project2\step3_onnx_export\export_onnx.py --weights runs\classify\pretrain_stage2\weights\best.pt --data datasets\birds_v1_course3
python project2\step6_controller\decision_rate.py --labels labels_all.csv --log \\wsl.localhost\Ubuntu-24.04\home\kkhodareva\demo_log_185555.csv
```

WSL — демонстрация целиком:

```bash
wsl -d Ubuntu-24.04 -- bash /mnt/c/Users/kkhod/claude/AIS/project2/step8_demo/demo_turtle.sh
```
