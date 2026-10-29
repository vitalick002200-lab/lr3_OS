"""Завдання 7. Збирати метрики процесу в CSV через заданий інтервал."""
import argparse
import csv
import sys
import time
from pathlib import Path

import common
import procmetrics

COLUMNS = ["t_idx", "ts_ms", "rss_kb", "vsz_kb", "threads", "page_faults", "read_bytes", "write_bytes"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int)
    parser.add_argument("--delta", type=float, default=common.DELTA, help="інтервал між знімками, секунди")
    parser.add_argument("--points", type=int, default=600)
    parser.add_argument("--label", default="run")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if args.delta <= 0 or args.points <= 0:
        parser.error("delta та points мають бути більші за нуль")

    try:
        process = procmetrics.open_probe(args.pid)
    except procmetrics.ProcessGone:
        print(f"Процесу з PID {args.pid} не існує.", file=sys.stderr)
        return 2

    path = Path(args.out) if args.out else common.DATA / f"monitor_{args.label}_{common.TOKEN}.csv"
    start_clock = time.perf_counter()
    start_ms = time.time() * 1000
    written = 0
    try:
        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(COLUMNS)
            for t_idx in range(args.points):
                # Плануємо наступний знімок від старту, щоб похибка не накопичувалась.
                deadline = start_clock + t_idx * args.delta
                wait = deadline - time.perf_counter()
                if wait > 0:
                    time.sleep(wait)
                try:
                    stats = process.sample()
                except procmetrics.ProcessGone:
                    print("Процес завершився; зберігаю вже зібрані точки.")
                    break
                ts_ms = start_ms + (time.perf_counter() - start_clock) * 1000
                values = [procmetrics.fmt_na(stats.get(name)) for name in COLUMNS[2:]]
                writer.writerow([t_idx, f"{ts_ms:.3f}", *values])
                written += 1
                if written % 50 == 0:
                    file.flush()
    except KeyboardInterrupt:
        print("Моніторинг зупинено; CSV закрито коректно.")
    finally:
        process.close()

    print(f"Збережено {written} точок у {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
