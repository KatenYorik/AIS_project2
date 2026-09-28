# -*- coding: utf-8 -*-
"""Контроллер на ожидаемой свободной энергии. Общий код для узла ROS 2 и панели.

Чек-лист курса требует «контроллер с порогом уверенности». Порог — три строки.
Здесь вместо него действие выбирается минимизацией ожидаемой свободной энергии
по трём действиям. Порог при этом никуда не девается: он получается сам, из
предпочтений C и матрицы переходов B, — и потому его не надо назначать руками.

Обозначения те же, что в Parr, Pezzulo & Friston (2022), гл. 4:

    s ∈ {feeding, alert, empty}      скрытое состояние сцены
    o ∈ {feeding, alert, empty}      наблюдение — выход классификатора
    u ∈ {approach, hold, retreat}    действие робота

    A_u[o, s]   = P(o | s, u)        правдоподобие: насколько надёжен классификатор
                                     ПРИ ЭТОМ действии — вблизи птицу видно лучше
    B[u][s', s] = P(s' | s, u)       как действие меняет сцену
    C[o]        = log P(o)           предпочтения (ненормированные лог-веса)

    G(u) = risk + ambiguity
    risk      = KL( Q(o|u) || P(o) )      — насколько исход разойдётся с желаемым
    ambiguity = E_{Q(s|u)} H[ A(·|s) ]    — насколько исход будет неинформативен

Действие выбирается как argmin G. Мягкий выбор через softmax(−γG) нужен только
для показа: в демо полезно видеть, насколько решение уверенное.
"""
from __future__ import annotations

import math

STATES = ["feeding", "alert", "empty"]
ACTIONS = ["approach", "hold", "retreat"]
ACTIONS_RU = {"approach": "подъехать", "hold": "стоять", "retreat": "отъехать"}

# ---------------------------------------------------------------- модель
# A: классификатор неидеален. Диагональ — доля верных решений, остальное размазано.
# Числа берутся из МАТРИЦЫ ОШИБОК обученной модели: см. set_A_from_confusion().
_A = [[0.85, 0.10, 0.05],
      [0.10, 0.85, 0.05],
      [0.05, 0.05, 0.90]]

# Ключевая деталь: правдоподобие ЗАВИСИТ ОТ ДЕЙСТВИЯ. Вблизи птица занимает
# больше кадра и классификатор точнее, издали — хуже. Без этого эпистемический
# член одинаков для всех действий, не влияет на выбор, и вся конструкция
# вырождается в «всегда отъезжать»: подъезжать было бы незачем.
# SHARP — во сколько раз действие «обостряет» или «размывает» правдоподобие.
SHARP = {"approach": 2.0, "hold": 1.0, "retreat": 0.45}


def _A_for(u):
    """Правдоподобие при действии u: возводим в степень и перенормируем по столбцам.

    Степень >1 делает распределение острее (уверенное наблюдение),
    <1 — площе (мутный далёкий кадр). Столбец — это P(o | s).
    """
    k = SHARP[u]
    out = [[0.0]*3 for _ in range(3)]
    for s in range(3):
        col = [max(_A[o][s], EPS) ** k for o in range(3)]
        z = sum(col)
        for o in range(3): out[o][s] = col[o] / z
    return out

# B[u][s'][s]: приближение пугает птицу (кормление → осмотр → улетела),
# отъезд даёт ей успокоиться, стояние почти ничего не меняет.
_B = {
    "approach": [[0.45, 0.05, 0.02],      # → feeding
                 [0.40, 0.60, 0.08],      # → alert
                 [0.15, 0.35, 0.90]],     # → empty
    "hold":     [[0.80, 0.15, 0.03],
                 [0.15, 0.75, 0.07],
                 [0.05, 0.10, 0.90]],
    "retreat":  [[0.85, 0.35, 0.10],
                 [0.10, 0.55, 0.20],
                 [0.05, 0.10, 0.70]],
}

# C: чего робот «хочет» увидеть. Спокойно кормящаяся птица — хорошо,
# осмотр — нейтрально, пустая кормушка — плохо. Это лог-веса, не вероятности.
_C = [2.0, 0.3, -1.5]

EPS = 1e-12


def set_A_from_confusion(cm, labels):
    """Подставить в A настоящую матрицу ошибок модели (строки — истина).

    Так предпочтения и переходы остаются заданными руками, а надёжность
    наблюдения берётся из измерений. Это то, что отличает работающую
    модель от красивой.
    """
    global _A
    idx = {l: i for i, l in enumerate(labels)}
    if set(labels) != set(STATES): return False
    A = [[0.0]*3 for _ in range(3)]
    for si, s in enumerate(STATES):
        row = cm[idx[s]]
        tot = sum(row) or 1
        for oi, o in enumerate(STATES):
            A[oi][si] = row[idx[o]] / tot          # P(o | s)
    # сглаживание, чтобы нули не давали бесконечных логарифмов
    for oi in range(3):
        for si in range(3):
            A[oi][si] = 0.95 * A[oi][si] + 0.05 / 3
    _A = A
    return True


def _entropy(col):
    return -sum(p * math.log(p + EPS) for p in col)


def expected_free_energy(qs):
    """qs — распределение по состояниям (softmax классификатора).

    Возвращает {действие: (G, risk, ambiguity)}.
    """
    Zc = sum(math.exp(c) for c in _C)
    logP = [c - math.log(Zc) for c in _C]
    out = {}
    for u in ACTIONS:
        B = _B[u]
        qs_u = [sum(B[sp][s] * qs[s] for s in range(3)) for sp in range(3)]
        z = sum(qs_u) or 1.0
        qs_u = [v / z for v in qs_u]
        A_u = _A_for(u)
        qo = [sum(A_u[o][s] * qs_u[s] for s in range(3)) for o in range(3)]
        z = sum(qo) or 1.0
        qo = [v / z for v in qo]
        risk = sum(qo[o] * (math.log(qo[o] + EPS) - logP[o]) for o in range(3))
        amb = sum(qs_u[s] * _entropy([A_u[o][s] for o in range(3)]) for s in range(3))
        out[u] = (risk + amb, risk, amb)
    return out


def choose(qs, gamma=4.0):
    """Полный ответ контроллера: действие, разложение G и уверенность."""
    G = expected_free_energy(qs)
    best = min(G, key=lambda u: G[u][0])
    gmin = min(v[0] for v in G.values())
    w = {u: math.exp(-gamma * (G[u][0] - gmin)) for u in ACTIONS}
    z = sum(w.values())
    p = {u: w[u] / z for u in ACTIONS}
    return {
        "action": best,
        "action_ru": ACTIONS_RU[best],
        "confidence": p[best],
        "G": {u: round(G[u][0], 4) for u in ACTIONS},
        "risk": {u: round(G[u][1], 4) for u in ACTIONS},
        "ambiguity": {u: round(G[u][2], 4) for u in ACTIONS},
        "policy": {u: round(p[u], 3) for u in ACTIONS},
    }


def choose_threshold(qs, thr=0.6):
    """Запасной вариант на день демонстрации: обычный порог уверенности.

    Если что-то пойдёт не так с активным выводом — переключиться сюда флагом,
    и требование чек-листа выполнено буквально.
    """
    i = max(range(3), key=lambda k: qs[k])
    if qs[i] < thr:
        act = "hold"
    else:
        act = {"feeding": "approach", "alert": "hold", "empty": "retreat"}[STATES[i]]
    return {"action": act, "action_ru": ACTIONS_RU[act], "confidence": qs[i],
            "G": {}, "risk": {}, "ambiguity": {}, "policy": {}}
