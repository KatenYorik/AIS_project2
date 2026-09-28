# -*- coding: utf-8 -*-
"""Панель Gradio: кадр, три вероятности, выбранное действие и разложение решения.

Работает в двух режимах, и это сделано намеренно:

  --mode ros       подписывается на /image/compressed, /model_result и /action.
                   Показывает то, что реально происходит в системе.
  --mode local     сам гоняет ONNX по веб-камере или файлу, без ROS.
                   Нужен на случай, если в день демонстрации ROS не поднимется.

    pip install gradio onnxruntime opencv-python
    python gradio_panel.py --mode local --model best.onnx --source 0
    python gradio_panel.py --mode ros
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # общие пути AIS, см. common/aispaths.py
_sys.path.insert(0, str(next(_p / "common" for _p in _pl.Path(__file__).resolve().parents
                            if (_p / "common" / "aispaths.py").is_file())))
import aispaths
import argparse, json, os, sys, threading, time

aispaths.add_ros_pkg()
import efe                                     # noqa: E402

STATE = {"frame": None, "probs": {}, "label": "—", "latency": 0.0,
         "decision": None, "n": 0, "timeline": []}   # (класс, действие)
TL_MAX = 150
LOCK = threading.Lock()


# ---------------------------------------------------------------- локальный режим
def loop_local(model, source, classes, imgsz, fps, mode, thr):
    import cv2, numpy as np, onnxruntime as ort
    sess = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name
    cap = cv2.VideoCapture(int(source) if str(source).isdigit() else str(source))
    if not cap.isOpened():
        print(f"не открылся источник {source}"); return
    period = 1.0 / fps

    def square(im):
        """Тот же препроцессинг, что при обучении и в export_onnx.py.

        Здесь раньше стоял cv2.resize(frame, (imgsz, imgsz)) — кадр 16:9
        сплющивался в квадрат, а ultralytics при обучении масштабирует по
        КОРОТКОЙ стороне и берёт центральный квадрат. Птица на входе получалась
        сжатой по горизонтали, то есть панель показывала не то, на чём модель
        обучалась. Валидация экспорта этого не ловит: она свой квадрат готовит
        сама и в панель не заглядывает.
        """
        h, w = im.shape[:2]
        s = imgsz / min(h, w)
        im = cv2.resize(im, (round(w * s), round(h * s)))
        H, W = im.shape[:2]
        top, left = (H - imgsz) // 2, (W - imgsz) // 2
        return im[top:top + imgsz, left:left + imgsz]

    while True:
        t0 = time.time()
        ok, frame = cap.read()
        if not ok:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0); continue
        x = square(frame)
        x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype("float32") / 255.0
        x = x.transpose(2, 0, 1)[None]
        t1 = time.perf_counter()
        out = sess.run(None, {inp: x})[0][0]
        dt = (time.perf_counter() - t1) * 1000
        p = np.asarray(out, dtype="float64")
        if abs(p.sum() - 1) > 1e-3:
            p = np.exp(p - p.max()); p = p / p.sum()
        probs = {c: float(v) for c, v in zip(classes, p)}
        qs = [probs.get(s, 0.0) for s in efe.STATES]
        z = sum(qs) or 1.0
        qs = [v / z for v in qs]
        d = efe.choose_threshold(qs, thr) if mode == "threshold" else efe.choose(qs)
        with LOCK:
            STATE["frame"] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            STATE["probs"] = probs
            STATE["label"] = max(probs, key=probs.get)
            STATE["latency"] = dt
            STATE["decision"] = d
            STATE["timeline"].append((STATE["label"], d["action"]))
            del STATE["timeline"][:-TL_MAX]
            STATE["n"] += 1
        time.sleep(max(0.0, period - (time.time() - t0)))


# ---------------------------------------------------------------- режим ROS
def loop_ros():
    import cv2, numpy as np
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import CompressedImage
    from std_msgs.msg import String

    class Panel(Node):
        def __init__(self):
            super().__init__("gradio_panel")
            self.create_subscription(CompressedImage, "/image/compressed", self.img, 5)
            self.create_subscription(String, "/model_result", self.res, 10)
            self.create_subscription(String, "/action", self.act, 10)

        def img(self, m):
            arr = np.frombuffer(m.data, dtype=np.uint8)
            f = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if f is None: return
            with LOCK:
                STATE["frame"] = cv2.cvtColor(f, cv2.COLOR_BGR2RGB); STATE["n"] += 1

        def res(self, m):
            try: r = json.loads(m.data)
            except json.JSONDecodeError: return
            with LOCK:
                STATE["probs"] = r.get("probs", {})
                STATE["label"] = r.get("label", "—")
                STATE["latency"] = r.get("latency_ms", 0.0)

        def act(self, m):
            try: d = json.loads(m.data)
            except json.JSONDecodeError: return
            with LOCK:
                STATE["decision"] = d
                STATE["timeline"].append((d.get("label", "—"), d["action"]))
                del STATE["timeline"][:-TL_MAX]

    rclpy.init()
    rclpy.spin(Panel())


# ---------------------------------------------------------------- отрисовка
# Лента состояний: две дорожки — что видит классификатор и что решает контроллер.
# Ради неё и стоило соединять проект с научной частью: это тот же рисунок, что
# Viterbi-декодирование в анализе, только вживую.
CLS_COLOR = {"feeding": "#e0b341", "alert": "#4a90d9", "empty": "#555b66"}
ACT_COLOR = {"approach": "#2f8f6b", "hold": "#8e8e8e", "retreat": "#a53b3b"}


def timeline_svg(tl):
    if not tl:
        return "<div style='color:#888'>лента появится после первых кадров</div>"
    w, cell, h = 900, max(3, min(8, 900 // max(len(tl), 1))), 18
    n = len(tl)
    parts = [f"<svg width='{min(w, n*cell)}' height='{2*h+26}' "
             f"xmlns='http://www.w3.org/2000/svg'>"]
    for i, (cls, act) in enumerate(tl):
        x = i * cell
        parts.append(f"<rect x='{x}' y='0' width='{cell}' height='{h}' "
                     f"fill='{CLS_COLOR.get(cls, '#333')}'/>")
        parts.append(f"<rect x='{x}' y='{h+4}' width='{cell}' height='{h}' "
                     f"fill='{ACT_COLOR.get(act, '#333')}'/>")
    parts.append(f"<text x='0' y='{2*h+20}' font-size='11' fill='#888'>"
                 f"верх — класс сцены, низ — действие; последние {n} кадров</text>")
    parts.append("</svg>")
    legend = ("<div style='font-size:12px;margin-top:4px'>"
              + " ".join(f"<span style='color:{c}'>■</span> {k}"
                         for k, c in {**CLS_COLOR, **ACT_COLOR}.items())
              + "</div>")
    return "".join(parts) + legend


def snapshot():
    with LOCK:
        frame = STATE["frame"]
        probs = dict(STATE["probs"])
        d = STATE["decision"]
        lat, n = STATE["latency"], STATE["n"]
        tl = list(STATE["timeline"])

    label_md = "### ждём кадры…"
    table = ""
    if d:
        label_md = (f"# {d['action_ru'].upper()}\n"
                    f"класс сцены: **{d.get('label', '—')}**, "
                    f"уверенность решения {d.get('confidence', 0):.2f}, "
                    f"режим `{d.get('mode', 'efe')}`")
        if d.get("G"):
            rows = ["| действие | риск | неоднозначность | G | вес |",
                    "|---|---|---|---|---|"]
            for u in efe.ACTIONS:
                mark = " ←" if u == d["action"] else ""
                rows.append(f"| {efe.ACTIONS_RU[u]}{mark} | {d['risk'][u]:.3f} | "
                            f"{d['ambiguity'][u]:.3f} | {d['G'][u]:.3f} | "
                            f"{d['policy'][u]:.2f} |")
            table = "\n".join(rows) + (
                "\n\n**Риск** — насколько исход разойдётся с тем, что робот хочет видеть. "
                "**Неоднозначность** — насколько исход будет неинформативен: вблизи птицу "
                "видно лучше, поэтому подъезд её снижает. Действие выбирается по "
                "наименьшей сумме, а не по порогу.")
    stat = f"кадров: {n} · задержка сети: {lat:.1f} мс"
    return frame, probs, label_md, table, stat, timeline_svg(tl)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["ros", "local"], default="local")
    ap.add_argument("--model", default="best.onnx")
    ap.add_argument("--source", default="0")
    ap.add_argument("--classes", default="alert,empty,feeding")
    ap.add_argument("--imgsz", type=int, default=224)
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--controller", choices=["efe", "threshold"], default="efe")
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--confusion", default="", help="results/*.json из train.py")
    ap.add_argument("--port", type=int, default=7860)
    a = ap.parse_args()
    # --model и --confusion можно давать от AIS/data: runs\...\best.onnx, results\...json
    a.model = aispaths.resolve_data(a.model)
    a.confusion = aispaths.resolve_data(a.confusion)

    if a.confusion and os.path.exists(a.confusion):
        d = json.load(open(a.confusion, encoding="utf-8"))
        if efe.set_A_from_confusion(d["confusion"], d["labels"]):
            print("правдоподобие A взято из матрицы ошибок модели")

    if a.mode == "local":
        cls = [c.strip() for c in a.classes.split(",")]
        threading.Thread(target=loop_local, daemon=True,
                         args=(a.model, a.source, cls, a.imgsz, a.fps,
                               a.controller, a.threshold)).start()
    else:
        threading.Thread(target=loop_ros, daemon=True).start()

    import gradio as gr
    with gr.Blocks(title="Птицы: классификация и решение") as demo:
        gr.Markdown("## Классификация поведения птицы и выбор действия робота")
        with gr.Row():
            with gr.Column(scale=3):
                img = gr.Image(label="кадр", height=380)
                stat = gr.Markdown()
            with gr.Column(scale=2):
                lab = gr.Label(num_top_classes=3, label="вероятности классов")
                dec = gr.Markdown()
        tab = gr.Markdown()
        gr.Markdown("### Лента состояний")
        tl = gr.HTML()
        timer = gr.Timer(0.3)
        timer.tick(snapshot, None, [img, lab, dec, tab, stat, tl])
    demo.launch(server_port=a.port, share=False)


if __name__ == "__main__":
    main()
