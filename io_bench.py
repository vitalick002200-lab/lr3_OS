"""Завдання 6. Вимірювання запису: buffered проти fsync."""
import argparse
import os
import sys
import time
from pathlib import Path

import common

WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
READ_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0)


def sync_file(fd, mode):
    if mode == "fullfsync":
        import fcntl
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
    else:
        os.fsync(fd)


def write_series(path, block_size, operations, mode):
    """Виконати записи й повернути час кожної операції та фінального fsync."""
    data = os.urandom(block_size)  # підготувати дані до початку вимірювання
    times = []
    final_sync_ns = None
    fd = os.open(path, WRITE_FLAGS)
    try:
        for _ in range(operations):
            start = time.perf_counter_ns()
            os.write(fd, data)
            if mode != "buffered":
                sync_file(fd, mode)
            times.append(time.perf_counter_ns() - start)
        if mode == "buffered":
            start = time.perf_counter_ns()
            sync_file(fd, "fsync")
            final_sync_ns = time.perf_counter_ns() - start
    finally:
        os.close(fd)
    return times, final_sync_ns


def read_twice(path, v, outdir):
    """Прочитати файл двічі блоками 1 МБ, щоб порівняти холодне й повторне читання."""
    fd = os.open(path, READ_FLAGS)
    cache_dropped = False
    if hasattr(os, "posix_fadvise"):
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        cache_dropped = True
    rows = []
    try:
        for run in range(2):
            os.lseek(fd, 0, os.SEEK_SET)
            total = 0
            start = time.perf_counter()
            while True:
                block = os.read(fd, 1024 * 1024)
                if not block:
                    break
                total += len(block)
            seconds = time.perf_counter() - start
            mib_per_s = total / 1048576 / seconds
            rows.append((run, f"{seconds:.4f}", f"{mib_per_s:.1f}"))
            print(f"Читання {run + 1}: {total // 1048576} МіБ, {mib_per_s:.1f} МіБ/с")
    finally:
        os.close(fd)
    if cache_dropped:
        print("Перед першим читанням кеш попросили скинути через posix_fadvise.")
    else:
        print("Кеш не скинуто; обидва читання можуть обслуговуватися з RAM.")
    common.write_csv(outdir / f"io_read_{v.TOKEN}.csv", ["t_idx", "seconds", "mib_per_s"], rows)


def counter_series(path):
    """Повільна серія buffered-запису 64 КБ для одночасного resource_monitor."""
    block_size, operations = 65536, 2000
    pause = float(os.environ.get("LAB3_COUNTER_PAUSE", "0.035"))
    data = os.urandom(block_size)
    print(f"PID = {os.getpid()}")
    print(f"2000 записів по 64 КБ; пауза між записами {pause} с")
    time.sleep(2)
    fd = os.open(path, WRITE_FLAGS)
    try:
        for i in range(operations):
            os.write(fd, data)
            time.sleep(pause)
            if i % 500 == 0:
                print(f"Записано {i + 1} блоків")
        start = time.perf_counter_ns()
        os.fsync(fd)
        print(f"Фінальний fsync: {(time.perf_counter_ns() - start) / 1e6:.1f} мс")
    finally:
        os.close(fd)
    time.sleep(3)
    os.remove(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=common.DEFAULT_N)
    parser.add_argument("--counters", action="store_true")
    parser.add_argument("--scale", type=float, default=1.0, help="менше число лише для короткого тесту")
    parser.add_argument("--outdir", default=None)
    parser.add_argument("--testdir", default=None)
    args = parser.parse_args()

    v = common.variant(args.n)
    outdir = Path(args.outdir) if args.outdir else common.DATA
    testdir = Path(args.testdir) if args.testdir else common.DATA / "iotest"
    testdir.mkdir(parents=True, exist_ok=True)
    common.setup_log(v, "io_bench.py")

    if args.counters:
        counter_series(testdir / "io_counters.bin")
        return

    modes = ["buffered", "fsync"]
    if sys.platform == "darwin":
        modes.append("fullfsync")
    summary = []
    print(f"Накладні витрати таймера: {common.timer_overhead_ns()} нс")

    for block_size, default_count in common.IO_SERIES:
        operations = max(20, int(default_count * args.scale))
        for mode in modes:
            path = testdir / f"io_{mode}_{block_size}.bin"
            print(f"\nРежим={mode}, блок={block_size} Б, операцій={operations}")
            times, final_sync = write_series(path, block_size, operations, mode)
            common.write_csv(outdir / f"io_{mode}_{block_size}_{v.TOKEN}.csv",
                             ["t_idx", "lat_ns"], [(i, t) for i, t in enumerate(times)])

            stats = common.summarize([t / 1000 for t in times])  # мкс
            total_seconds = sum(times) / 1e9
            iops = operations / total_seconds
            mib_per_second = operations * block_size / 1048576 / total_seconds
            print("  " + common.fmt_stats("затримка", stats, "мкс"))
            print(f"  IOPS={iops:.0f}; швидкість={mib_per_second:.1f} МіБ/с")
            final_ms = "NA" if final_sync is None else f"{final_sync / 1e6:.3f}"
            summary.append((len(summary), mode, block_size, operations, f"{stats['median']:.3f}",
                            f"{stats['p95']:.3f}", f"{stats['p99']:.3f}", f"{stats['mean']:.3f}",
                            f"{iops:.1f}", f"{mib_per_second:.2f}", f"{total_seconds:.4f}", final_ms))

            if mode == "buffered" and block_size == 1048576:
                read_twice(path, v, outdir)
            os.remove(path)

    common.write_csv(outdir / f"io_summary_{v.TOKEN}.csv",
                     ["t_idx", "mode", "block_bytes", "ops", "median_us", "p95_us", "p99_us", "mean_us",
                      "iops", "mib_per_s", "total_s", "final_fsync_ms"], summary)
    try:
        testdir.rmdir()
    except OSError:
        pass
    print("Тестові файли видалено. Готово.")


if __name__ == "__main__":
    main()
