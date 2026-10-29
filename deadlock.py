"""Бонус 5.8. Взаємоблокування і його усунення глобальним порядком замків."""
import argparse
import threading
import time
from pathlib import Path

import common


def worker(first, second, result, index, show_tid):
    if show_tid:
        print(f"[TID] worker-{index}: {threading.get_native_id()}", flush=True)
    with first:
        time.sleep(0.01)  # даємо другому потоку час захопити свій перший замок
        got_second = second.acquire(timeout=2)
        result[index] = got_second
        if got_second:
            second.release()


def one_run(safe_order, show_tid=False):
    lock_a = threading.Lock()
    lock_b = threading.Lock()
    result = [None, None]

    # Безпечна версія: обидва потоки беруть A, потім B.
    # Небезпечна: перший бере A->B, другий бере B->A.
    if safe_order:
        order2 = (lock_a, lock_b)
    else:
        order2 = (lock_b, lock_a)
    t1 = threading.Thread(target=worker, args=(lock_a, lock_b, result, 0, show_tid))
    t2 = threading.Thread(target=worker, args=(*order2, result, 1, show_tid))

    start = time.perf_counter()
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    elapsed_ms = (time.perf_counter() - start) * 1000
    deadlocked = any(value is False for value in result)
    return deadlocked, elapsed_ms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=common.DEFAULT_N)
    parser.add_argument("--mode", choices=["deadlock", "ordered", "both"], default="both")
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--outdir", default=None)
    args = parser.parse_args()

    v = common.variant(args.n)
    outdir = Path(args.outdir) if args.outdir else common.DATA
    common.setup_log(v, "deadlock.py")
    modes = ["deadlock", "ordered"] if args.mode == "both" else [args.mode]
    for mode in modes:
        rows = []
        count = 0
        print(f"\nРежим {mode}: {args.repeats} повторів")
        for i in range(args.repeats):
            dead, elapsed = one_run(mode == "ordered", show_tid=(i == 0))
            count += int(dead)
            rows.append((i, int(dead), f"{elapsed:.1f}"))
        common.write_csv(outdir / f"deadlock_{mode}_{v.TOKEN}.csv",
                         ["t_idx", "deadlocked", "time_ms"], rows)
        print(f"Виявлено блокувань: {count} з {args.repeats}")
        print("  " + common.fmt_stats("час, мс", common.summarize([float(r[2]) for r in rows])))


if __name__ == "__main__":
    main()
