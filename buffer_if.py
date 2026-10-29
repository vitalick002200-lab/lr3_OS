"""Завдання 3.3. Навмисно неправильна версія: if замість while."""
import argparse
import os
import sys
import threading
import time
from pathlib import Path

import common

CONSUMERS = 3  # за методичкою в цьому досліді завжди C = 3


class BrokenBuffer:
    def __init__(self, size):
        self.size = size
        self.data = [None] * size
        self.inp = self.out = self.count = 0
        self.mutex = threading.Lock()
        self.not_full = threading.Condition(self.mutex)
        self.not_empty = threading.Condition(self.mutex)

    def put(self, item):
        with self.mutex:
            while self.count == self.size:
                if not self.not_full.wait(timeout=0.1):
                    return False  # не дозволяємо помилковому досліду зависнути
            self.data[self.inp] = item
            self.inp = (self.inp + 1) % self.size
            self.count += 1
            self.not_empty.notify_all()  # навмисно будимо всіх споживачів
            return True

    def get(self):
        with self.mutex:
            if self.count == 0:  # ПОМИЛКА: тут має бути while
                self.not_empty.wait(timeout=0.2)
            # Після пробудження count не перевіряється повторно.
            item = self.data[self.out]
            self.out = (self.out + 1) % self.size
            self.count -= 1
            self.not_full.notify()
            return item


def one_run(v, items):
    buf = BrokenBuffer(v.B)
    got = [[] for _ in range(CONSUMERS)]
    errors = []
    stopped = [False] * CONSUMERS

    def producer(index):
        for number in range(index, items, v.P):
            if not buf.put((number, number * v.n + 1)):
                errors.append("виробник не дочекався місця в буфері")
                return

    def consumer(index):
        try:
            while True:
                item = buf.get()
                if item is None:
                    stopped[index] = True
                    return
                got[index].append(item)
        except Exception as error:
            errors.append(type(error).__name__ + ": " + str(error))

    consumers = [threading.Thread(target=consumer, args=(i,), daemon=True) for i in range(CONSUMERS)]
    producers = [threading.Thread(target=producer, args=(i,), daemon=True) for i in range(v.P)]
    for thread in consumers + producers:
        thread.start()
    for thread in producers:
        thread.join(timeout=3)

    # STOP додаємо після спроби завершити виробників.
    stops = sum(buf.put(None) for _ in range(CONSUMERS))
    for thread in consumers:
        thread.join(timeout=1)

    numbers = [number for group in got for number, _ in group]
    unique = len(set(numbers))
    duplicates = len(numbers) - unique
    return (len(numbers), unique, duplicates, items - unique, stops,
            sum(stopped), buf.count, len(errors), "; ".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=common.DEFAULT_N)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--items", type=int, default=common.ITEMS)
    parser.add_argument("--outdir", default=None)
    args = parser.parse_args()
    v = common.variant(args.n)
    outdir = Path(args.outdir) if args.outdir else common.DATA
    common.setup_log(v, "buffer_if.py")
    sys.setswitchinterval(1e-6)
    rows = []
    print(f"Помилковий буфер: C={CONSUMERS}, ITEMS={args.items}, switchinterval=1e-6 с")
    try:
        for run in range(args.runs):
            result = one_run(v, args.items)
            rows.append((run, *result[:-1]))
            print(f"запуск {run + 1}: отримано={result[0]}, унікальних={result[1]}, "
                  f"дублікатів={result[2]}, пропущено={result[3]}, помилок={result[7]}")
            if result[8]:
                print("  " + result[8])
    finally:
        sys.setswitchinterval(0.005)
    common.write_csv(outdir / f"buffer_if_{v.TOKEN}.csv",
                     ["t_idx", "received", "unique", "duplicates", "missing", "stops_put",
                      "ended_by_stop", "final_count", "errors"], rows)
    print("Готово. Цей код навмисно неправильний; його не використовуйте замість BoundedBuffer.")


if __name__ == "__main__":
    main()
