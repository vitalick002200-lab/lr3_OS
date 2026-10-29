"""Завдання 5.5.3. У Windows дочірній процес запускається через spawn, а не fork()."""
import argparse
import mmap
import multiprocessing as mp
import os
import time
from pathlib import Path

import common
import procmetrics


def child(pipe):
    """Дочірній процес надсилає батьку свої метрики одразу після запуску."""
    stats = procmetrics.own_sample()
    pipe.send((os.getpid(), stats.get("rss_kb"), stats.get("private_kb")))
    pipe.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=common.DEFAULT_N)
    parser.add_argument("--mem-mb", type=int, default=None, help="малий обсяг лише для тесту")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--outdir", default=None)
    args = parser.parse_args()

    v = common.variant(args.n)
    outdir = Path(args.outdir) if args.outdir else common.DATA
    size = (args.mem_mb or v.MEM_MB) * 1024 * 1024
    page = mmap.PAGESIZE
    common.setup_log(v, "spawn_demo.py")

    # Батько займає MEM пам'яті: виділяє масив і торкається кожної сторінки.
    big_data = bytearray(size)
    for offset in range(0, size, page):
        big_data[offset] = 1
    parent_stats = procmetrics.own_sample()
    print(f"Батько PID={os.getpid()}, MEM={size // 1048576} МБ, "
          f"RSS={procmetrics.fmt_kb(parent_stats.get('rss_kb'))} КБ")

    rows = []
    for t_idx in range(args.repeats):
        parent_pipe, child_pipe = mp.get_context("spawn").Pipe()
        process = mp.get_context("spawn").Process(target=child, args=(child_pipe,))
        start = time.perf_counter()
        process.start()
        child_pid, child_rss, child_private = parent_pipe.recv()  # сигнал: нащадок готовий
        elapsed_ms = (time.perf_counter() - start) * 1000
        process.join()
        parent_pipe.close()

        parent_rss = procmetrics.own_sample().get("rss_kb")
        rows.append((t_idx, f"{elapsed_ms:.3f}", child_rss, child_private, parent_rss))
        print(f"Запуск {t_idx + 1}: старт→готовність={elapsed_ms:.1f} мс; "
              f"RSS нащадка={procmetrics.fmt_kb(child_rss)} КБ; "
              f"RSS батька={procmetrics.fmt_kb(parent_rss)} КБ; PID нащадка={child_pid}")

    common.write_csv(outdir / f"spawn_{v.TOKEN}.csv",
                     ["t_idx", "start_to_ready_ms", "child_rss_kb", "child_private_kb", "parent_rss_kb"], rows)
    print("У режимі spawn нащадок запускається як новий інтерпретатор і не успадковує big_data.")
    del big_data


if __name__ == "__main__":
    mp.freeze_support()
    main()
