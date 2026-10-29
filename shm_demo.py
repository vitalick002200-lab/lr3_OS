"""Завдання 5.5.1. Два процеси користуються одним блоком спільної пам'яті."""
import argparse
import mmap
import multiprocessing as mp
import os
import time
from multiprocessing import shared_memory
from pathlib import Path

import common
import procmetrics


def child(name, token, ready, wait_seconds, touch_pages):
    """Дочірній процес відкриває блок за ім'ям і записує TOKEN."""
    memory = shared_memory.SharedMemory(name=name)
    text = token.encode("ascii")
    memory.buf[:len(text)] = text
    if touch_pages:
        for offset in range(0, memory.size, mmap.PAGESIZE):
            _ = memory.buf[offset]
    ready.set()  # повідомити батьку, що запис уже виконаний
    time.sleep(wait_seconds)
    memory.close()


def free_ram_mb():
    """Приблизний обсяг вільної RAM, щоб порівняти з сумою RSS."""
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                        ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                        ("avail_extended", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.avail_phys / 1048576
    try:
        with open("/proc/meminfo", encoding="utf-8") as file:
            for line in file:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return float("nan")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=common.DEFAULT_N)
    parser.add_argument("--mem-mb", type=int, default=None, help="менше значення лише для тесту")
    parser.add_argument("--child-touch", action="store_true")
    parser.add_argument("--wait", type=float, default=30)
    parser.add_argument("--outdir", default=None)
    args = parser.parse_args()

    v = common.variant(args.n)
    outdir = Path(args.outdir) if args.outdir else common.DATA
    size = (args.mem_mb or v.MEM_MB) * 1024 * 1024 // 2  # MEM / 2
    page = mmap.PAGESIZE
    tag = "touch" if args.child_touch else "write"
    common.setup_log(v, "shm_demo.py")
    free_before = free_ram_mb()

    memory = shared_memory.SharedMemory(create=True, size=size)
    process = None
    try:
        # Батько записує один байт у кожну сторінку.
        for offset in range(0, size, page):
            memory.buf[offset] = 1
        free_parent = free_ram_mb()

        context = mp.get_context("spawn")
        ready = context.Event()
        process = context.Process(
            target=child, args=(memory.name, v.TOKEN, ready, args.wait, args.child_touch))
        process.start()
        if not ready.wait(60):
            raise RuntimeError("Дочірній процес не повідомив про готовність")

        got = bytes(memory.buf[:len(v.TOKEN)]).decode("ascii")
        print(f"Батько прочитав: {got}; збіг з TOKEN: {got == v.TOKEN}")
        free_child = free_ram_mb()
        print(f"PID батька={os.getpid()}, PID нащадка={process.pid}")

        rows = []
        for index, (role, pid) in enumerate((("parent", os.getpid()), ("child", process.pid))):
            probe = procmetrics.open_probe(pid)
            stats = probe.sample()
            probe.close()
            rows.append((index, role, pid, stats.get("rss_kb"), stats.get("private_kb"),
                         stats.get("vsz_kb"), free_before, free_parent, free_child, tag))
            print(f"{role}: RSS/WorkingSet={procmetrics.fmt_kb(stats.get('rss_kb'))} КБ; "
                  f"Private={procmetrics.fmt_kb(stats.get('private_kb'))} КБ")

        common.write_csv(outdir / f"shm_{tag}_{v.TOKEN}.csv",
                         ["t_idx", "role", "pid", "rss_kb", "private_kb", "vsz_kb",
                          "free_before_mb", "free_after_parent_mb", "free_after_child_mb", "child_mode"], rows)
        process.join(args.wait + 10)
    finally:
        if process is not None and process.is_alive():
            process.terminate()
            process.join()
        memory.close()
        memory.unlink()
        print("Спільний блок закрито й видалено.")


if __name__ == "__main__":
    mp.freeze_support()
    main()
