"""Завдання 3. Обмежений кільцевий буфер (схема 3)."""
import argparse
import os
import threading
import time
from pathlib import Path

import common


class Buffer:
    """Кільцевий масив, один м'ютекс і дві умовні змінні."""
    def __init__(self, size):
        self.size = size
        self.data = [None] * size
        self.inp = 0
        self.out = 0
        self.count = 0
        self.waits_put = 0
        self.waits_get = 0
        self.mutex = threading.Lock()
        self.not_full = threading.Condition(self.mutex)
        self.not_empty = threading.Condition(self.mutex)

    def put(self, item):
        with self.mutex:
            while self.count == self.size:
                self.waits_put += 1
                self.not_full.wait()
            if item is not None:
                item = (item[0], item[1], time.perf_counter_ns())
            self.data[self.inp] = item
            self.inp = (self.inp + 1) % self.size
            self.count += 1
            self.not_empty.notify()  # розбудити одного споживача

    def get(self):
        with self.mutex:
            while self.count == 0:
                self.waits_get += 1
                self.not_empty.wait()
            item = self.data[self.out]
            self.out = (self.out + 1) % self.size
            self.count -= 1
            self.not_full.notify()  # розбудити одного виробника
            return item


def producer(buffer, index, items, v, delay, tids):
    tids[index] = threading.get_native_id()
    print(f"[TID] producer-{index}: {tids[index]}", flush=True)
    # Виробники разом створюють ITEMS елементів, розділивши номери між собою.
    for number in range(index, items, v.P):
        item = (number, number * v.n + 1)
        buffer.put(item)
        if delay:
            time.sleep(delay)


def consumer(buffer, index, delay, results, tids):
    tids[index] = threading.get_native_id()
    print(f"[TID] consumer-{index}: {tids[index]}", flush=True)
    while True:
        item = buffer.get()
        if item is None:  # STOP
            return
        number, value, put_ns = item
        results[index].append((number, value, time.perf_counter_ns() - put_ns))
        if delay:
            time.sleep(delay)


def run_once(mode, v, items, take_states):
    buffer = Buffer(v.B)
    consumer_tids = [None] * v.C
    producer_tids = [None] * v.P
    results = [[] for _ in range(v.C)]

    # Режим b: сповільнений споживач; режим c: сповільнений виробник.
    consumer_delay = 0.001 if mode == "b" else 0
    producer_delay = 0.005 if mode == "c" else 0
    consumers = [threading.Thread(target=consumer,
                 args=(buffer, i, consumer_delay, results, consumer_tids)) for i in range(v.C)]
    producers = [threading.Thread(target=producer,
                 args=(buffer, i, items, v, producer_delay, producer_tids)) for i in range(v.P)]

    print(f"PID = {os.getpid()}", flush=True)
    start = time.perf_counter()
    for thread in consumers + producers:
        thread.start()

    states = ""
    if take_states:
        time.sleep(3)  # режим c дає час побачити споживачів у стані очікування
        states = common.mark_tids(common.os_thread_states(os.getpid()), consumer_tids)
        common.log("Стани потоків (>> — споживачі):\n" + states)

    for thread in producers:
        thread.join()
    for _ in range(v.C):
        buffer.put(None)  # STOP кладемо після завершення всіх виробників
    for thread in consumers:
        thread.join()

    received = [item for group in results for item in group]
    numbers = [item[0] for item in received]
    expected_sum = sum(number * v.n + 1 for number in range(items))
    ok_count = len(received) == items
    ok_sum = sum(item[1] for item in received) == expected_sum
    ok_numbers = sorted(numbers) == list(range(items))
    return {
        "received": received, "ok_count": ok_count, "ok_sum": ok_sum,
        "ok_numbers": ok_numbers, "waits_put": buffer.waits_put,
        "waits_get": buffer.waits_get, "count_end": buffer.count,
        "seconds": time.perf_counter() - start, "states": states,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=common.DEFAULT_N)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--mode", choices=["a", "b", "c"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--items", type=int, default=common.ITEMS)
    parser.add_argument("--no-states", action="store_true")
    parser.add_argument("--outdir", default=None)
    args = parser.parse_args()
    if not args.all and not args.mode:
        parser.error("вкажіть --all або --mode")

    v = common.variant(args.n)
    outdir = Path(args.outdir) if args.outdir else common.DATA
    common.setup_log(v, "bounded_buffer.py")
    modes = ["a", "b", "c"] if args.all else [args.mode]
    waits_rows = []

    for mode in modes:
        print(f"\nРежим {mode} (запусків: {args.runs})")
        latency_rows = []
        for run in range(1, args.runs + 1):
            observe = mode == "c" and run == 1 and not args.no_states
            result = run_once(mode, v, args.items, observe)
            items_got = sorted(result["received"])
            ok = result["ok_count"] and result["ok_sum"] and result["ok_numbers"]
            print(f"  запуск {run}: кількість={result['ok_count']}, сума={result['ok_sum']}, "
                  f"усі номери один раз={result['ok_numbers']} -> {'OK' if ok else 'ПОМИЛКА'}")
            print(f"  waits_put={result['waits_put']}, waits_get={result['waits_get']}, "
                  f"час={result['seconds']:.2f} с, count у кінці={result['count_end']}")
            for number, _value, latency in items_got:
                latency_rows.append((len(latency_rows), run, number, latency))
            waits_rows.append((len(waits_rows), mode, run, result["waits_put"],
                               result["waits_get"], "OK" if ok else "ПОМИЛКА"))

        common.write_csv(outdir / f"buffer_{mode}_{v.TOKEN}.csv",
                         ["t_idx", "run", "item", "latency_ns"], latency_rows)

    common.write_csv(outdir / f"buffer_waits_{v.TOKEN}.csv",
                     ["t_idx", "mode", "run", "waits_put", "waits_get", "check"], waits_rows)
    print("Готово.")


if __name__ == "__main__":
    main()
