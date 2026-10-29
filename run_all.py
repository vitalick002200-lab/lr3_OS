"""Запускач усіх автоматичних експериментів ЛР3 (варіант n = 24, TOKEN = LAB3-24-18).

    python scripts\\run_all.py                      # усе по черзі (≈ 15-20 хв)
    python scripts\\run_all.py --list               # показати кроки
    python scripts\\run_all.py --only race,buffer   # лише вибрані кроки
    python scripts\\run_all.py --skip deadlock      # усе, окрім вибраних

Ручні дії (скриншоти, VMMap, другий запуск для ASLR) описано в README.md.
Закрийте важкі застосунки, підключіть живлення, не запускайте з каталогу OneDrive.
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

PY = sys.executable


def run(script, *args, check=True):
    cmd = [PY, "-u", str(HERE / script), *map(str, args)]
    print(f"\n$ {' '.join(cmd[1:])}", flush=True)
    r = subprocess.run(cmd, cwd=str(HERE))
    if check and r.returncode != 0:
        print(f"!!! {script} завершився з кодом {r.returncode}", flush=True)
    return r.returncode


def run_with_monitor(script_args, label, points):
    """Запускає програму, ловить її PID з виводу ("PID = N") і паралельно запускає resource_monitor."""
    out_txt = common.DATA / f"{label}_stdout.txt"
    f = open(out_txt, "w", encoding="utf-8")
    cmd = [PY, "-u", str(HERE / script_args[0]), *map(str, script_args[1:])]
    print(f"\n$ {' '.join(cmd[1:])}   (з resource_monitor, label={label})", flush=True)
    p = subprocess.Popen(cmd, cwd=str(HERE), stdout=f, stderr=subprocess.STDOUT)
    pid = None
    t_end = time.time() + 30
    while pid is None and time.time() < t_end:
        time.sleep(0.2)
        m = re.search(r"PID = (\d+)", out_txt.read_text(encoding="utf-8", errors="replace"))
        if m:
            pid = int(m.group(1))
    if pid is None:
        print("!!! PID програми не знайдено", flush=True)
        p.kill()
        return 1
    print(f"   PID програми = {pid}; запускаю resource_monitor ({points} точок, Δ = {common.DELTA} с)", flush=True)
    run("resource_monitor.py", pid, "--delta", common.DELTA, "--points", points, "--label", label)
    p.wait()
    f.close()
    print(out_txt.read_text(encoding="utf-8", errors="replace"), flush=True)
    return p.returncode


STEPS = {
    "passport": ("Завдання 1: паспорт середовища",
                 lambda: run("env_passport.py")),
    "race": ("Завдання 2: гонитва (5 серій по 1000 повторів)",
             lambda: run("race.py", "--all")),
    "buffer": ("Завдання 3: обмежений буфер (режими a, b, c по 3 запуски)",
               lambda: run("bounded_buffer.py", "--all")),
    "bufferif": ("Завдання 3.3: дослід «if замість while»",
                 lambda: run("buffer_if.py")),
    "mem": ("Завдання 4: mem_touch + resource_monitor (автоматичний запуск)",
            lambda: run_with_monitor(["mem_touch.py", "--hold", 22], "mem", 450)),
    "shm": ("Завдання 5.5.1: спільна пам'ять (обидва варіанти)",
            lambda: (run("shm_demo.py"), run("shm_demo.py", "--child-touch"))),
    "spawn": ("Завдання 5.5.3: spawn замість fork",
              lambda: run("spawn_demo.py")),
    "io": ("Завдання 6: ввід-вивід (8 серій + читання)",
           lambda: run("io_bench.py")),
    "iocounters": ("Завдання 6.2: лічильники I/O під resource_monitor",
                   lambda: run_with_monitor(["io_bench.py", "--counters"], "io", 450)),
    "deadlock": ("Бонус 5.8: взаємоблокування (стани потоків + 2 x 100 повторів)",
                 lambda: (run("observe_threads.py", "--label", "deadlock", "--delay", 1.0, "--",
                              "deadlock.py", "--mode", "deadlock", "--repeats", 2),
                          run("deadlock.py"))),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    a = ap.parse_args()
    if a.list:
        for k, (t, _) in STEPS.items():
            print(f"  {k:11s} {t}")
        return
    only = [x for x in a.only.split(",") if x]
    skip = [x for x in a.skip.split(",") if x]
    for k in only + skip:
        if k not in STEPS:
            sys.exit(f"невідомий крок: {k}  (див. --list)")
    v = common.variant()
    print(f"ЛР3, {v.describe()}")
    t_all = time.time()
    for k, (title, fn) in STEPS.items():
        if (only and k not in only) or k in skip:
            continue
        print("\n" + "#" * 78 + f"\n# {title}\n" + "#" * 78, flush=True)
        t0 = time.time()
        fn()
        print(f"# крок '{k}' завершено за {time.time() - t0:.0f} с", flush=True)
    print(f"\nУсе готово за {(time.time() - t_all) / 60:.1f} хв. Файли — у каталозі data\\.")


if __name__ == "__main__":
    main()
