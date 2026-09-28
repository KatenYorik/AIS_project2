#!/usr/bin/env bash
# Сводка по логу решений контроллера. Числа для отчёта Проекта 2.
#
#     bash log_summary.sh ~/demo_log_125406.csv
#
# Колонки лога: stamp, label, p_feeding, p_alert, p_empty, action,
#               confidence, risk_best, ambiguity_best
L="${1:-$HOME/demo_log.csv}"
[ -f "$L" ] || { echo "нет файла: $L"; exit 1; }

N=$(( $(wc -l < "$L") - 1 ))
T0=$(sed -n 2p "$L" | cut -d, -f1)
T1=$(tail -1 "$L" | cut -d, -f1)

echo "файл:     $L"
echo "решений:  $N"
awk -v a="$T0" -v b="$T1" -v n="$N" 'BEGIN{
  d=b-a; if(d>0) printf "длительность: %.1f с, частота решений %.2f /с\n", d, n/d
}'

echo
echo "=== ДЕЙСТВИЯ"
tail -n +2 "$L" | cut -d, -f6 | sort | uniq -c | sort -rn
echo
echo "=== КЛАССЫ"
tail -n +2 "$L" | cut -d, -f2 | sort | uniq -c | sort -rn
echo
echo "=== ПАРЫ класс -> действие"
tail -n +2 "$L" | awk -F, '{print $2" -> "$6}' | sort | uniq -c | sort -rn
echo
echo "=== СКОЛЬКО ОТРЕЗКОВ ПОДРЯД (устойчивость решения)"
tail -n +2 "$L" | cut -d, -f6 | uniq -c | awk '{s[$2]+=1; l[$2]+=$1}
  END{for(a in s) printf "  %-9s отрезков %3d, средняя длина %.1f кадра\n", a, s[a], l[a]/s[a]}'
echo
echo "=== УВЕРЕННОСТЬ РЕШЕНИЯ по действиям (среднее)"
tail -n +2 "$L" | awk -F, '{s[$6]+=$7; n[$6]++}
  END{for(a in s) printf "  %-9s %.3f  (%d решений)\n", a, s[a]/n[a], n[a]}'
