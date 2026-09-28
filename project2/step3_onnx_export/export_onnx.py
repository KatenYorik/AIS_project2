# -*- coding: utf-8 -*-
"""Шаг 5 курса: экспорт в ONNX + ЧИСЛЕННАЯ валидация + замер задержки.

    pip install ultralytics onnx onnxruntime
    python export_onnx.py --weights runs/classify/small/weights/best.pt --data datasets/birds_v1_course3

Чек-лист требует не просто экспорт, а валидацию. Валидация здесь настоящая:
прогоняем одни и те же кадры через PyTorch и через onnxruntime и сравниваем
не «работает / не работает», а три числа —
  * максимальное расхождение вероятностей,
  * доля кадров, где изменился предсказанный класс,
  * расхождение по каждому классу.
Расхождение до ~1e-4 нормально (другой порядок операций в свёртках),
больше 1e-2 или хоть одно изменившееся решение — повод разбираться.

Задержка меряется отдельно для PyTorch и ONNX, с прогревом и по медиане,
а не по среднему: одиночный выброс от сборщика мусора не должен портить число.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pl  # общие пути AIS, см. common/aispaths.py
_sys.path.insert(0, str(next(_p / "common" for _p in _pl.Path(__file__).resolve().parents
                            if (_p / "common" / "aispaths.py").is_file())))
import aispaths
aispaths.to_data()  # данные, runs, results и пути в аргументах — от AIS/data
import argparse, json, os, statistics, sys, time


def find_images(root, limit):
    out = []
    for split in ("val", "train"):
        d = os.path.join(root, split)
        if not os.path.isdir(d): continue
        for cls in sorted(os.listdir(d)):
            p = os.path.join(d, cls)
            if not os.path.isdir(p): continue
            for f in sorted(os.listdir(p))[:limit]:
                if f.lower().endswith((".jpg", ".jpeg", ".png")):
                    out.append(os.path.join(p, f))
        if out: break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True, help="best.pt после train.py")
    ap.add_argument("--data", default="datasets/birds_v1_course3", help="папка с val/")
    ap.add_argument("--imgsz", type=int, default=224)
    ap.add_argument("--per-class", type=int, default=20, help="кадров на класс для сверки")
    ap.add_argument("--runs", type=int, default=50, help="прогонов для замера задержки")
    ap.add_argument("--opset", type=int, default=12)
    a = ap.parse_args()

    from ultralytics import YOLO
    import numpy as np

    model = YOLO(a.weights)
    names = model.names
    print("классы модели:", names)

    # ---------------------------------------------------------------- экспорт
    print("\n=== ЭКСПОРТ")
    onnx_path = model.export(format="onnx", imgsz=a.imgsz, opset=a.opset, simplify=False)
    print("файл:", onnx_path, f"({os.path.getsize(onnx_path)/1e6:.1f} МБ)")
    print("исходные веса:", f"{os.path.getsize(a.weights)/1e6:.1f} МБ")

    imgs = find_images(a.data, a.per_class)
    if not imgs:
        sys.exit(f"не нашёл кадров в {a.data} — сначала собери датасет")
    print(f"кадров для сверки: {len(imgs)}")

    # ---------------------------------------------------------------- валидация
    print("\n=== ЧИСЛЕННАЯ ВАЛИДАЦИЯ")
    import onnxruntime as ort
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name

    import cv2

    def square(path):
        """Кадр, приведённый к imgsz x imgsz ТАК ЖЕ, как это делает ultralytics.

        Важная тонкость. Раньше здесь стоял простой cv2.resize в квадрат, а
        model.predict() внутри себя делает другое: масштабирует по короткой
        стороне и берёт центральный квадрат. На кадре 16:9 это заметно разные
        картинки, и сверка мерила бы разницу препроцессинга, а не экспорта.
        Теперь квадрат готовится здесь один раз и подаётся ОБОИМ путям: для
        ultralytics повторный resize 224->224 и обрезка становятся пустой
        операцией, значит любое расхождение — это уже про сам ONNX.
        """
        im = cv2.imread(path)
        h, w = im.shape[:2]
        s = a.imgsz / min(h, w)
        im = cv2.resize(im, (round(w * s), round(h * s)))
        H, W = im.shape[:2]
        top, left = (H - a.imgsz) // 2, (W - a.imgsz) // 2
        return im[top:top + a.imgsz, left:left + a.imgsz]      # BGR, uint8

    def prep(path):
        im = cv2.cvtColor(square(path), cv2.COLOR_BGR2RGB).astype("float32") / 255.0
        return im.transpose(2, 0, 1)[None]           # NCHW

    dmax, changed, per_cls = 0.0, 0, {}
    for path in imgs:
        x = prep(path)
        t = model.predict(square(path), imgsz=a.imgsz, verbose=False)[0].probs.data.cpu().numpy()
        o = sess.run(None, {inp: x})[0][0]
        # Голова классификации YOLO отдаёт УЖЕ вероятности (сумма 1, все >= 0).
        # Здесь раньше стоял безусловный exp(), а нормировка — только если сумма
        # разошлась с единицей; получался софтмакс поверх софтмакса. Порядок
        # классов он сохраняет, поэтому сверка показывала «0 смен класса» и при
        # этом расхождение 0.42 — то есть мерила собственную ошибку, а не экспорт.
        # Теперь exp применяется только к настоящим логитам.
        if o.min() < 0 or abs(o.sum() - 1) > 1e-3:
            o = np.exp(o - o.max()); o = o / o.sum()
        d = float(np.abs(t - o).max())
        dmax = max(dmax, d)
        if int(t.argmax()) != int(o.argmax()): changed += 1
        for i, n in names.items():
            per_cls[n] = max(per_cls.get(n, 0.0), float(abs(t[i] - o[i])))

    print(f"максимальное расхождение вероятностей: {dmax:.2e}")
    print(f"кадров, где изменился предсказанный класс: {changed} из {len(imgs)}")
    print("по классам:", {k: f"{v:.2e}" for k, v in per_cls.items()})
    ok = dmax < 1e-2 and changed == 0
    print("ВЕРДИКТ:", "экспорт корректен" if ok else
          "РАСХОЖДЕНИЕ ЗНАЧИМО — в отчёт писать честно и разбираться")

    # ---------------------------------------------------------------- задержка
    print("\n=== ЗАДЕРЖКА (одиночный кадр, CPU)")
    x = prep(imgs[0])
    for _ in range(5): sess.run(None, {inp: x})            # прогрев
    ts = []
    for _ in range(a.runs):
        t0 = time.perf_counter(); sess.run(None, {inp: x}); ts.append((time.perf_counter()-t0)*1000)
    ts.sort()
    onnx_med, onnx_p95 = statistics.median(ts), ts[int(0.95*len(ts))-1]

    sq0 = square(imgs[0])
    for _ in range(3): model.predict(sq0, imgsz=a.imgsz, verbose=False)
    tp = []
    for _ in range(max(a.runs // 2, 10)):
        t0 = time.perf_counter(); model.predict(sq0, imgsz=a.imgsz, verbose=False)
        tp.append((time.perf_counter()-t0)*1000)
    tp.sort()
    torch_med = statistics.median(tp)

    print(f"ONNX  : медиана {onnx_med:.1f} мс, 95-й перцентиль {onnx_p95:.1f} мс "
          f"→ {1000/onnx_med:.1f} кадров/с")
    print(f"PyTorch: медиана {torch_med:.1f} мс (включая препроцессинг ultralytics)")
    print(f"ускорение: ×{torch_med/onnx_med:.2f}")
    print("\nдля отчёта: ONNX быстрее прежде всего потому, что убран питоновский")
    print("слой ultralytics вокруг сети, а не потому, что сама сеть изменилась.")

    res = {"onnx": onnx_path, "max_prob_diff": dmax, "class_changes": changed,
           "n_images": len(imgs), "latency_ms_onnx_median": onnx_med,
           "latency_ms_onnx_p95": onnx_p95, "latency_ms_torch_median": torch_med,
           "fps_onnx": 1000/onnx_med, "valid": ok, "classes": names}
    os.makedirs("results", exist_ok=True)
    with open("results/onnx_validation.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("\nсохранено results/onnx_validation.json — эти числа идут в отчёт")


if __name__ == "__main__":
    main()
