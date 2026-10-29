"""Завдання 4. Перший і повторний дотик до сторінок (схема 4)."""
import argparse
import ctypes
import mmap
import os
import time
from pathlib import Path

import common
import procmetrics


def touch_pages(memory, memory_bytes, page_size):
    """Записати байт на початок кожної сторінки й виміряти кожен запис."""
    times = []
    for offset in range(0, memory_bytes, page_size):
        start = time.perf_counter_ns()
        memory[offset] = 1
        times.append(time.perf_counter_ns() - start)
    return times


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=common.DEFAULT_N)
    parser.add_argument("--mem-mb", type=int, default=None, help="малий розмір лише для тесту")
    parser.add_argument("--no-pause", action="store_true")
    parser.add_argument("--hold", type=float, default=0, help="пауза в секундах замість Enter")
    parser.add_argument("--tag", default="", help="суфікс CSV для повторного запуску")
    parser.add_argument("--outdir", default=None)
    args = parser.parse_args()

    v = common.variant(args.n)
    outdir = Path(args.outdir) if args.outdir else common.DATA
    mem_mb = args.mem_mb or v.MEM_MB
    memory_bytes = mem_mb * 1024 * 1024
    page_size = mmap.PAGESIZE
    page_count = memory_bytes // page_size
    pid = os.getpid()
    suffix = f"_{args.tag}" if args.tag else ""
    probe = procmetrics.open_probe(pid)
    phases = []
    previous_faults = None

    def pause(text):
        if args.no_pause:
            return
        print(text)
        if args.hold:
            time.sleep(args.hold)
        else:
            input("  Зробіть знімок у засобах ОС і натисніть Enter...")

    def snapshot(name):
        nonlocal previous_faults
        stats = probe.sample()
        faults = stats.get("page_faults")
        delta = None if faults is None or previous_faults is None else faults - previous_faults
        previous_faults = faults
        phases.append((name, stats.get("vsz_kb"), stats.get("private_kb"),
                       stats.get("rss_kb"), faults, delta))
        print(f"Фаза {name}: VSZ={stats.get('vsz_kb')} КБ, Private={stats.get('private_kb')} КБ, "
              f"RSS={stats.get('rss_kb')} КБ, page_faults={faults}, приріст={delta}")

    print(f"PID={pid}; пам'ять={mem_mb} МБ; сторінка={page_size} Б; сторінок={page_count}")
    print(f"Накладні витрати таймера: {common.timer_overhead_ns()} нс")

    # A — початковий процес, ще без mmap.
    print("\nФаза A: до створення mmap")
    snapshot("A")
    pause("Зніміть показники фази A.")

    # B — зарезервувати пам'ять, але ще не торкатися кожної сторінки.
    print("\nФаза B: після mmap")
    memory = mmap.mmap(-1, memory_bytes)
    address_view = ctypes.c_char.from_buffer(memory)
    address = ctypes.addressof(address_view)
    print(f"Адреса mmap: 0x{address:X} ({address})")
    snapshot("B")
    pause("Зніміть показники фази B і карту адресного простору.")

    # C — перший запис по одному байту в кожну сторінку.
    print("\nФаза C: перший прохід")
    pass1 = touch_pages(memory, memory_bytes, page_size)
    snapshot("C")
    pause("Зніміть показники фази C.")

    # D — повторити той самий прохід по вже торкнутих сторінках.
    print("\nФаза D: повторний прохід")
    pass2 = touch_pages(memory, memory_bytes, page_size)
    snapshot("D")
    pause("Зніміть показники фази D.")

    common.write_csv(outdir / f"pages{suffix}_{v.TOKEN}.csv",
                     ["t_idx", "pass1_ns", "pass2_ns"],
                     [(i, pass1[i], pass2[i]) for i in range(page_count)])
    common.write_csv(outdir / f"phases{suffix}_{v.TOKEN}.csv",
                     ["t_idx", "phase", "vsz_kb", "private_kb", "rss_kb", "page_faults", "page_faults_delta"],
                     [(i, name, *["NA" if x is None else x for x in values])
                      for i, (name, *values) in enumerate(phases)])

    print("  " + common.fmt_stats("pass1, нс", common.summarize(pass1)))
    print("  " + common.fmt_stats("pass2, нс", common.summarize(pass2)))
    print("CSV збережено. Відображення буде звільнено.")
    del address_view
    memory.close()
    probe.close()


if __name__ == "__main__":
    main()
