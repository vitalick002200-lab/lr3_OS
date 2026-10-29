"""Спільні параметри варіанта й короткі допоміжні функції ЛР3."""
import csv
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

# Український текст у консолі Windows.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

DEFAULT_N = 24
NAME = "Футумайчук Віталій Андрійович"
SURNAME_LAT = "futumaichuk"
GROUP = "ОІ-23"
R = 1000
ITEMS = 2000
IO_SERIES = [(512, 2000), (4096, 2000), (65536, 2000), (1048576, 256)]
MIN_POINTS = 300
WARMUP_FRAC = 0.05
IS_WINDOWS = os.name == "nt"
_LOGFILE = None


class Variant:
    """Обчислення параметрів за номером студента n."""
    def __init__(self, n):
        self.n = (n - 1) % 30 + 1
        n = self.n
        self.NT = 2 + n % 3
        self.INC = 200 + 20 * n
        self.B = 3 + n % 5
        self.P = 1 + n % 2
        self.C = 1 + n % 3
        self.MEM_MB = 64 + 8 * n
        self.DELTA = round(0.2 + 0.1 * (n % 4), 3)
        self.TOKEN = f"LAB3-{n:02d}-{(53 * n + 7) % 97:02d}"
        self.F_NUM = 1 + n % 4

    def describe(self):
        return (f"n={self.n} NT={self.NT} INC={self.INC} B={self.B} P={self.P} C={self.C} "
                f"MEM={self.MEM_MB} МБ DELTA={self.DELTA} с TOKEN={self.TOKEN}")


def variant(n=DEFAULT_N):
    return Variant(n)


V = variant()
N, NT, INC, B, P, C = V.n, V.NT, V.INC, V.B, V.P, V.C
MEM_MB, DELTA, TOKEN, F_NUM = V.MEM_MB, V.DELTA, V.TOKEN, V.F_NUM
META = DATA / f"meta_{TOKEN}.json"


def setup_log(v, script):
    """Почати новий блок у спільному журналі запусків."""
    global _LOGFILE
    _LOGFILE = DATA / f"run_log_{v.TOKEN}.txt"
    text = (f"\n{'=' * 60}\n{time.strftime('%Y-%m-%d %H:%M:%S')}  {script}\n"
            f"{v.describe()}\n{'=' * 60}")
    with open(_LOGFILE, "a", encoding="utf-8") as file:
        file.write(text + "\n")
    print(text, flush=True)


def log(message=""):
    print(message, flush=True)
    if _LOGFILE:
        with open(_LOGFILE, "a", encoding="utf-8") as file:
            file.write(str(message) + "\n")


def write_csv(path, header, rows):
    """Зберегти результати. За методичкою перший стовпець — t_idx."""
    if header[0] != "t_idx":
        raise ValueError("Перший стовпець CSV має називатися t_idx")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)
    log(f"  CSV: {path.name}, рядків: {len(rows)}")


def percentile(values, p):
    """Перцентиль із лінійною інтерполяцією у відсортованому списку."""
    if not values:
        return float("nan")
    position = (len(values) - 1) * p / 100
    lo, hi = math.floor(position), math.ceil(position)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def summarize(values, warmup=True):
    """Відкинути перші 5 % значень і порахувати основну статистику."""
    values = list(values)
    dropped = int(len(values) * WARMUP_FRAC) if warmup else 0
    values = sorted(values[dropped:])
    if not values:
        return {"count": 0, "dropped": dropped}
    return {"count": len(values), "dropped": dropped, "min": values[0],
            "median": percentile(values, 50), "mean": sum(values) / len(values),
            "p95": percentile(values, 95), "p99": percentile(values, 99), "max": values[-1]}


def fmt_stats(label, stats, unit=""):
    if not stats.get("count"):
        return f"{label}: немає даних"
    return (f"{label}: N={stats['count']}, відкинуто={stats['dropped']}, "
            f"min={stats['min']:.3f}, медіана={stats['median']:.3f}, "
            f"середнє={stats['mean']:.3f}, p95={stats['p95']:.3f}, "
            f"p99={stats['p99']:.3f}, max={stats['max']:.3f} {unit}").rstrip()


def timer_overhead_ns(samples=20000):
    """Оцінити накладні витрати таймера за сусідніми викликами."""
    times = []
    for _ in range(samples):
        start = time.perf_counter_ns()
        times.append(time.perf_counter_ns() - start)
    return sorted(times)[len(times) // 2]


def os_thread_states(pid):
    """Зчитати стани потоків штатними засобами операційної системи."""
    if IS_WINDOWS:
        command = ["powershell", "-NoProfile", "-Command",
                   f"(Get-Process -Id {pid}).Threads | Select Id,ThreadState,WaitReason | Format-Table -AutoSize"]
    else:
        command = ["ps", "-L", "-o", "tid,stat,wchan:20,comm", "-p", str(pid)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return (result.stdout + result.stderr).strip()
    except Exception as error:
        return f"Не вдалося отримати стани потоків: {error}"


def mark_tids(text, tids):
    """Позначити рядки, де знайдено TID потрібних потоків."""
    tids = {str(tid) for tid in tids if tid is not None}
    return "\n".join((">> " if any(tid in line.split() for tid in tids) else "   ") + line
                     for line in text.splitlines())


def write_variant_txt(v, os_line, toolchain):
    text = (f"NAME={NAME}\nN={v.n}\nNT={v.NT} INC={v.INC} B={v.B} P={v.P} C={v.C}\n"
            f"MEM_MB={v.MEM_MB} DELTA={v.DELTA}\nTOKEN={v.TOKEN}\nOS={os_line}\n"
            f"LANGUAGE=Python; TOOLCHAIN={toolchain}\n")
    (ROOT / "variant.txt").write_text(text, encoding="utf-8")
    return text


def meta_update(key, value):
    try:
        data = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data[key] = value
    META.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    print(variant().describe())
