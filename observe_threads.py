"""Знімок станів потоків процесу засобами ОС (п. 5.3.2 і бонус 5.8).

    python observe_threads.py --label c --delay 3 -- buffer.py --mode c --runs 1
    python observe_threads.py --label deadlock --delay 1 -- deadlock.py --mode deadlock --repeats 3

Скрипт сам запускає програму, чекає --delay секунд, знімає список потоків:
    Windows: (Get-Process -Id PID).Threads | Select Id,ThreadState,WaitReason
    Linux  : ps -L -o tid,stat,wchan:20,comm -p PID
і позначає потоки за TID, які програма надрукувала на старті ("[TID] роль: N").
Результат: data/thread_states_<label>_<TOKEN>.txt  (+ вивід на екран для скриншота).
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import common

HERE = Path(__file__).resolve().parent


def thread_table(pid):
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-Command",
               f"(Get-Process -Id {pid}).Threads | Select-Object Id,ThreadState,WaitReason "
               f"| Format-Table -AutoSize | Out-String -Width 200"]
    else:
        cmd = ["ps", "-L", "-o", "tid,stat,wchan:20,comm", "-p", str(pid)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return (r.stdout + r.stderr).strip(), cmd
    except Exception as e:
        return f"не вдалося виконати {cmd[0]}: {e}", cmd


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--snapshots", type=int, default=1)
    ap.add_argument("prog", nargs=argparse.REMAINDER, help="-- скрипт.py аргументи...")
    a = ap.parse_args(argv)
    prog = [x for x in a.prog if x != "--"]
    if not prog:
        ap.error("вкажіть програму після --")

    out_txt = common.DATA / f"observe_{a.label}_stdout.txt"
    logf = open(out_txt, "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable, "-u", str(HERE / prog[0])] + prog[1:],
                         stdout=logf, stderr=subprocess.STDOUT, cwd=str(HERE))
    pid = None
    t_end = time.time() + 15
    while time.time() < t_end and pid is None:
        time.sleep(0.2)
        m = re.search(r"PID = (\d+)", out_txt.read_text(encoding="utf-8", errors="replace"))
        if m:
            pid = int(m.group(1))
    if pid is None:
        pid = p.pid
        print("PID у виводі програми не знайдено, беру PID запущеного процесу")

    time.sleep(a.delay)
    lines = [f"Програма: {' '.join(prog)}   PID={pid}",
             f"Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    for k in range(a.snapshots):
        table, cmd = thread_table(pid)
        lines += [f"--- знімок {k + 1} (через {a.delay + k:.1f} с), команда: {' '.join(cmd)}", table, ""]
        if k + 1 < a.snapshots:
            time.sleep(1.0)
    txt = out_txt.read_text(encoding="utf-8", errors="replace")
    tids = re.findall(r"\[TID\] ([\w\-]+): (\d+)", txt)
    lines.append("TID, надруковані програмою (для зіставлення зі знімком):")
    lines += [f"  {role:12s} {tid}" for role, tid in tids]
    result = "\n".join(lines)
    print(result)
    (common.DATA / f"thread_states_{a.label}_{common.TOKEN}.txt").write_text(result, encoding="utf-8")
    try:
        p.wait(timeout=600)
    except subprocess.TimeoutExpired:
        p.kill()
    logf.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
