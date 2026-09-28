# -*- coding: utf-8 -*-
"""Оценка матрицы переходов B по РЕАЛЬНЫМ данным — своим и чужим.

    python estimate_B.py --wb bounding_boxes.csv --mine labels_all.csv --out B_data.json

Зачем. В контроллере три матрицы. A (надёжность классификатора) берётся из матрицы
ошибок модели. C (предпочтения) задаётся руками — это про то, чего мы хотим, измерить
нельзя. А B — как сцена меняется сама по себе — до сих пор была выдумана.

Но «сцена меняется сама по себе» — это ровно то, что измеряет наблюдательный датасет.
Значит столбец B для действия «стоять» можно не придумывать, а посчитать: по 431
траектории Visual WetlandBirds и по своей съёмке. Действия «подъехать» и «отъехать»
остаются возмущениями этой естественной динамики, и только их величина задаётся руками.

Итог: в модели остаётся выдуманным одно C. Всё остальное измерено.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pl  # общие пути AIS, см. common/aispaths.py
_sys.path.insert(0, str(next(_p / "common" for _p in _pl.Path(__file__).resolve().parents
                            if (_p / "common" / "aispaths.py").is_file())))
import aispaths
aispaths.to_data()  # данные, runs, results и пути в аргументах — от AIS/data
import sys
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

import argparse, ast, collections, csv, json

STATES = ["feeding", "alert", "empty"]
WB = {0: "feeding", 5: "alert"}                    # опознано в РЕЗУЛЬТАТЫ_WETLANDBIRDS
MINE = {"head_down": "feeding", "handling": "feeding",
        "head_up_ahead": "alert", "head_up_turnL": "alert",
        "head_up_turnR": "alert", "no_bird": "empty"}


def counts_to_P(cnt):
    """Счётчик переходов → матрица P[s'][s] = P(s' | s) со сглаживанием."""
    P = [[0.0]*3 for _ in range(3)]
    for si, s in enumerate(STATES):
        tot = sum(cnt[(s, sp)] for sp in STATES)
        for pi, sp in enumerate(STATES):
            P[pi][si] = (cnt[(s, sp)] + 0.5) / (tot + 1.5)   # +0.5 против нулей
    return P


def show(name, P, step):
    print(f"\n{name} (шаг {step} с)")
    head = "из / в"
    print(f"{head:>10s}" + "".join(f"{s:>10s}" for s in STATES))
    for si, s in enumerate(STATES):
        print(f"{s:>10s}" + "".join(f"{P[pi][si]:10.3f}" for pi in range(3)))
    dwell = [step / (1 - P[i][i]) if P[i][i] < 1 else float("inf") for i in range(3)]
    print("время в состоянии, с: " +
          "  ".join(f"{s} {d:.1f}" for s, d in zip(STATES, dwell)))
    return dwell


def from_wetlandbirds(path, step_frames=15, fps=30.0):
    tracks = collections.defaultdict(list)
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            try:
                boxes = ast.literal_eval(r["bounding_boxes"]); fr = int(float(r["frame"]))
            except Exception:
                continue
            for t in boxes:
                if len(t) >= 6:
                    tracks[(r["video_name"], int(t[5]))].append((fr, int(t[4])))
    cnt = collections.Counter()
    n = 0
    for seq in tracks.values():
        seq.sort()
        seq = [(fr, WB.get(b)) for fr, b in seq][::step_frames]     # прореживаем
        for (f1, a), (f2, b) in zip(seq, seq[1:]):
            if a is None or b is None: continue
            if f2 - f1 > step_frames * 2: continue                  # разрыв в треке
            cnt[(a, b)] += 1; n += 1
    # «empty» у них не размечен: птица в кадре всегда. Оставляем состояние,
    # но переходы в него и из него берём из своей съёмки — там оно есть.
    return cnt, n, step_frames / fps


def from_mine(path, step=0.5):
    seq = collections.defaultdict(list)
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        s = MINE.get(r["label"])
        clip, t = r["file"].rsplit("_t", 1)
        seq[clip].append((int(t) / 10.0, s))
    cnt = collections.Counter(); n = 0
    for c in seq:
        rows = sorted(seq[c])
        for (t1, a), (t2, b) in zip(rows, rows[1:]):
            if a is None or b is None: continue
            if abs(t2 - t1 - step) > 1e-6: continue
            cnt[(a, b)] += 1; n += 1
    return cnt, n, step


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wb", default="bounding_boxes.csv")
    ap.add_argument("--mine", default="labels_all.csv")
    ap.add_argument("--out", default="B_data.json")
    a = ap.parse_args()

    print("=" * 70)
    print("ЕСТЕСТВЕННАЯ ДИНАМИКА СЦЕНЫ: сколько её можно измерить, а не выдумать")
    print("=" * 70)

    res = {}
    try:
        cnt, n, step = from_wetlandbirds(a.wb)
        Pw = counts_to_P(cnt)
        print(f"\nчужие данные: переходов {n}")
        dw = show("Visual WetlandBirds, 13 видов", Pw, step)
        res["wetlandbirds"] = {"P": Pw, "step_s": step, "n": n, "dwell_s": dw}
    except FileNotFoundError:
        print("bounding_boxes.csv не найден — чужие данные пропущены")

    cnt, n, step = from_mine(a.mine)
    Pm = counts_to_P(cnt)
    print(f"\nсвои данные: переходов {n}")
    dm = show("Своя съёмка, 16 клипов", Pm, step)
    res["mine"] = {"P": Pm, "step_s": step, "n": n, "dwell_s": dm}

    if "wetlandbirds" in res:
        print("\n" + "=" * 70)
        print("СРАВНЕНИЕ")
        print("=" * 70)
        print("Шаг у них 0,5 с и у нас 0,5 с — матрицы сравнимы напрямую.")
        for i, s in enumerate(("feeding", "alert")):
            a_, b_ = Pw[i][i], Pm[i][i]
            print(f"  {s:8s}: вероятность остаться — чужие {a_:.3f}, свои {b_:.3f}")
        print("\nЕсли числа близки, значит динамика кормления и осмотра похожа")
        print("у болотных птиц и у синиц на кормушке, и брать B у них законно.")
        print("Если далеки — берём своё, а чужое приводим как сравнение.")

    json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nсохранено {a.out} — читается контроллером через set_B_from_data()")


if __name__ == "__main__":
    main()
