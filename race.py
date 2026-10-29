"""Завдання 2. Гонитва за спільним лічильником (схема 2)."""
import argparse
import sys
import threading
import time
from pathlib import Path

import common

counter = 0
lock = threading.Lock()
semaphore = threading.Semaphore(1)


def step(value):
    # Значення не змінює; додатковий виклик допомагає показати гонитву в Python.
    return value


def worker(mode, barrier, inc):
    global counter
    barrier.wait()  # усі потоки починають цикл разом

    if mode == "G":  # локальний підрахунок, один запис у спільний counter
        local = 0
        for _ in range(inc):
            local += 1
        with lock:
            counter += local
        return

    for _ in range(inc):
        if mode == "L":
            with lock:
                counter += 1
        elif mode == "S":
            with semaphore:
                counter += 1
        else:  # none: три окремі дії, між якими можлива гонитва
            temp = counter          # ПРОЧИТАТИ counter
            temp = step(temp) + 1    # tmp = tmp + 1
            counter = temp          # ЗАПИСАТИ counter


def one_repeat(mode, nt, inc, expected):
    """Один повтор: обнулити counter, запустити потоки й порахувати втрати."""
    global counter
    counter = 0
    barrier = threading.Barrier(nt)
    start = time.perf_counter_ns()  # за схемою: таймер перед створенням потоків
    threads = []
    for _ in range(nt):
        thread = threading.Thread(target=worker, args=(mode, barrier, inc))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter_ns() - start

    actual = counter
    return expected, actual, expected - actual, elapsed


def run_series(mode, interval, repeats, v, outdir):
    """Виконати R повторів і зберегти CSV."""
    sys.setswitchinterval(interval)
    expected = v.NT * v.INC  # одне очікуване значення для всієї серії
    rows = []
    for t_idx in range(repeats):
        expected, actual, lost, elapsed = one_repeat(mode, v.NT, v.INC, expected)
        rows.append((t_idx, expected, actual, lost, elapsed))

    if mode == "none":
        tag = f"{interval:g}".replace("e-06", "e-6")
        name = f"race_none_{tag}_{v.TOKEN}.csv"
    else:
        name = f"race_{mode}_{v.TOKEN}.csv"
    common.write_csv(outdir / name,
                     ["t_idx", "expected", "actual", "lost", "time_ns"], rows)

    lost_values = [row[3] for row in rows]
    time_values = [row[4] / 1000 for row in rows]  # мкс
    lost_stats = common.summarize(lost_values)
    time_stats = common.summarize(time_values)
    used = lost_values[int(0.05 * len(lost_values)):]
    failed = sum(value > 0 for value in used)
    print(f"{mode}, interval={interval:g} с: втрати у {failed}/{len(used)} повторах")
    print("  " + common.fmt_stats("lost", lost_stats))
    print("  " + common.fmt_stats("час повтору", time_stats, "мкс"))
    if mode != "none" and any(lost_values):
        print("ПОМИЛКА: у синхронізованому режимі є втрачені оновлення.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=common.DEFAULT_N)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--version", choices=["none", "L", "S", "G"])
    parser.add_argument("--interval", type=float, default=0.005)
    parser.add_argument("--repeats", type=int, default=common.R)
    parser.add_argument("--outdir", default=None)
    args = parser.parse_args()
    if not args.all and not args.version:
        parser.error("вкажіть --all або --version")

    v = common.variant(args.n)
    outdir = Path(args.outdir) if args.outdir else common.DATA
    common.setup_log(v, "race.py")
    print(f"NT={v.NT}, INC={v.INC}, очікуване значення={v.NT * v.INC}")
    print(f"Накладні витрати таймера: {common.timer_overhead_ns()} нс")

    if args.all:
        series = [("none", 0.005), ("none", 1e-6), ("L", 1e-6),
                  ("S", 1e-6), ("G", 1e-6)]
    else:
        series = [(args.version, args.interval)]
    try:
        for mode, interval in series:
            run_series(mode, interval, args.repeats, v, outdir)
    finally:
        sys.setswitchinterval(0.005)
    print("Готово.")


if __name__ == "__main__":
    main()
