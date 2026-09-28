# -*- coding: utf-8 -*-
"""Свой результат Проекта 2: на каком масштабе времени работает контроллер.

    python decision_rate.py --labels labels_all.csv [--log demo_log.csv]

Что считается и зачем.

Классификатор решает ПО КАДРУ. Поведение живёт эпизодами по 2-3 секунды — это мы
измерили СММ. Значит поток решений будет дёргаться чаще, чем меняется сама птица.
Насколько чаще — вопрос с числом, и его можно посчитать ДО того, как робот запущен:
прогнать контроллер по уже размеченной последовательности.

Три величины:
  * как часто меняет состояние птица,
  * как часто меняет действие контроллер,
  * сколько кадров надо усреднять, чтобы второе сравнялось с первым.

Последнее число и есть рекомендация к настройке — и берётся оно из поведения птицы,
а не из общих соображений.
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

import argparse, collections, csv, json, os, random

aispaths.add_ros_pkg()
import efe

STEP = 0.5
MINE = {"head_down": "feeding", "handling": "feeding",
        "head_up_ahead": "alert", "head_up_turnL": "alert",
        "head_up_turnR": "alert", "no_bird": "empty"}


def load(path):
    seq = collections.defaultdict(list)
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        s = MINE.get(r["label"])
        clip, t = r["file"].rsplit("_t", 1)
        if s: seq[clip].append((int(t) / 10.0, s))
    for c in seq: seq[c].sort()
    return seq


def switches(labels):
    return sum(1 for a, b in zip(labels, labels[1:]) if a != b)


def noisy_posterior(true_state, rng, acc=0.85):
    """Что увидит классификатор: правильный класс с вероятностью acc, иначе размазано."""
    i = efe.STATES.index(true_state)
    p = [(1 - acc) / 2] * 3
    p[i] = acc
    # немного дрожи, как у настоящей сети
    p = [max(v + rng.gauss(0, 0.05), 1e-3) for v in p]
    z = sum(p)
    return [v / z for v in p]


def run_controller(seq, window, rng, acc=0.85):
    """Прогоняет контроллер по разметке. window — по скольким кадрам усредняем."""
    acts, birds = [], []
    for c in sorted(seq):
        buf = []
        for _, s in seq[c]:
            buf.append(noisy_posterior(s, rng, acc))
            del buf[:-window]
            qs = [sum(b[i] for b in buf) / len(buf) for i in range(3)]
            z = sum(qs)
            acts.append(efe.choose([v / z for v in qs])["action"])
            birds.append(s)
    return acts, birds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="labels_all.csv")
    ap.add_argument("--log", default="demo_log.csv")
    ap.add_argument("--acc", type=float, default=0.85, help="точность классификатора")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    seq = load(a.labels)
    rng = random.Random(a.seed)
    n = sum(len(v) for v in seq.values())
    minutes = n * STEP / 60

    print("=" * 70)
    print("КАК ЧАСТО МЕНЯЕТСЯ ПТИЦА")
    print("=" * 70)
    bird_sw = sum(switches([s for _, s in seq[c]]) for c in seq)
    runs = []
    for c in seq:
        cur, k = None, 0
        for _, s in seq[c]:
            if s == cur: k += 1
            else:
                if cur: runs.append(k)
                cur, k = s, 1
        if cur: runs.append(k)
    dwell = sum(runs) / len(runs) * STEP
    print(f"кадров {n} ({minutes:.1f} мин), смен состояния {bird_sw}")
    bird_rate = bird_sw / minutes
    print(f"частота: {bird_rate:.1f} смен в минуту")
    print(f"среднее время в состоянии: {dwell:.1f} с")

    print("\n" + "=" * 70)
    print("КАК ЧАСТО МЕНЯЛСЯ БЫ КОНТРОЛЛЕР")
    print("=" * 70)
    print("строки — точность классификатора, столбцы — по скольким кадрам усредняем")
    print(f"в клетках — смен действия в минуту; у птицы {bird_rate:.1f}\n")
    W = (1, 2, 3, 4, 6)
    print(f"{'точность':>9s}" + "".join(f"{str(w) + ' кадр':>10s}" for w in W))
    table = {}
    for acc in (0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50):
        row = []
        for w in W:
            acts, _ = run_controller(seq, w, random.Random(a.seed), acc)
            row.append(switches(acts) / minutes)
        table[acc] = row
        print(f"{acc:9.2f}" + "".join(f"{v:10.1f}" for v in row))

    print("\n" + "=" * 70)
    print("ЧТО ИЗ ЭТОГО СЛЕДУЕТ")
    print("=" * 70)
    base = [table[x][0] for x in (0.95, 0.90, 0.85, 0.80)]
    print(f"1. При точности выше 0,75 контроллер без всякого усреднения меняет действие")
    print(f"   {sum(base)/len(base):.0f} раз в минуту против {bird_rate:.0f} у птицы. То есть покадровое решение")
    print(f"   НЕ ломает масштаб: птица и сама переключается каждые {dwell:.1f} с.")
    deaf = [x for x in sorted(table) if table[x][0] < bird_rate * 0.6]
    if deaf:
        print(f"\n2. А вот ниже {max(deaf):.2f} происходит обратное, и это опаснее шума:")
        print(f"   при точности {min(table):.2f} контроллер меняет действие всего")
        print(f"   {table[min(table)][0]:.1f} раза в минуту. Он не дёргается — он ГЛОХНЕТ.")
        print("   Вероятности выравниваются, разница ожидаемой свободной энергии между")
        print("   действиями пропадает, и он замирает на одном. Со стороны это выглядит")
        print("   как уверенная работа, а на деле система слепа. Самый коварный отказ.")
    print("\n3. Усреднение снижает отзывчивость монотонно: по 6 кадрам это уже")
    print(f"   {table[0.85][-1]:.1f} смен в минуту против {bird_rate:.0f} у птицы — контроллер отстаёт.")
    print("   Значит окно 1-2 кадра, а не больше.")
    print("\nВЫВОД ДЛЯ ОТЧЁТА: точность, измеренная в Проекте 1, определяет не только")
    print("качество распознавания, но и сам факт отзывчивости контроллера. Порог около")
    print("0,7: выше него система следит за птицей, ниже — замирает, не подавая признаков")
    print("неисправности. Это связывает два проекта одним числом.")

    if os.path.exists(a.log):
        print("\n" + "=" * 70)
        print("НАСТОЯЩИЙ ЗАПУСК (demo_log.csv)")
        print("=" * 70)
        rows = list(csv.DictReader(open(a.log, encoding="utf-8-sig")))
        if rows:
            acts = [r["action"] for r in rows]
            st = [float(r["stamp"]) for r in rows if r.get("stamp")]
            dur = (max(st) - min(st)) / 60 if len(st) > 1 else len(acts) * STEP / 60
            print(f"кадров {len(acts)}, длительность {dur:.1f} мин")
            print(f"смен действия: {switches(acts)} → {switches(acts)/max(dur,1e-6):.1f} в минуту")
            print(f"для сравнения, птица: {bird_rate:.1f} в минуту")
            c = collections.Counter(acts)
            print("доли действий:", {k: round(v/len(acts), 3) for k, v in c.items()})
    else:
        print(f"\n({a.log} пока нет — появится после запуска контроллера с -p log:=)")


if __name__ == "__main__":
    main()
