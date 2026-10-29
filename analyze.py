"""Обробка результатів ЛР3 (розділ 6 методички): статистика, таблиці, графіки.

    pip install matplotlib numpy
    python scripts\\analyze.py [--data data]

Читає CSV з каталогу data, перші 5 % повторів кожної серії відкидає як розігрів
(у CSV вони лишаються) і записує:
    data/analysis_<TOKEN>.json    усі обчислені числа
    data/analysis_<TOKEN>.md      таблиці для звіту
    data/plots/*.png              графіки (TOKEN у назві кожного)
Відсутні файли пропускаються з повідомленням.
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:  # графіки необов'язкові для чисел
    plt = None

V = common.variant()
TOKEN = V.TOKEN
OUT = {}
MD = []


def read(path, numeric=True):
    path = Path(path)
    if not path.exists():
        print(f"  (немає файлу {path.name})")
        return None
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows


def col(rows, name, cast=float):
    out = []
    for r in rows:
        try:
            out.append(cast(r[name]))
        except (ValueError, KeyError):
            pass
    return out


def st(values, warm=True):
    a = np.asarray(values, dtype=float)
    k = int(math.floor(common.WARMUP_FRAC * len(a))) if warm else 0
    a = a[k:]
    if a.size == 0:
        return {}
    return {"count": int(a.size), "dropped": k, "min": float(a.min()), "median": float(np.median(a)),
            "mean": float(a.mean()), "p95": float(np.percentile(a, 95)),
            "p99": float(np.percentile(a, 99)), "max": float(a.max())}


def f(x, d=1):
    return "NA" if x is None else f"{x:.{d}f}".replace(".", ",")


def table(title, header, rows):
    MD.append(f"\n**{title}**\n")
    MD.append("| " + " | ".join(header) + " |")
    MD.append("|" + "|".join("---" for _ in header) + "|")
    for r in rows:
        MD.append("| " + " | ".join(str(x) for x in r) + " |")


def save(fig, name):
    if plt is None:
        return
    p = D / "plots"
    p.mkdir(exist_ok=True)
    fig.savefig(p / f"{name}_{TOKEN}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  графік {name}_{TOKEN}.png")


# ---------------------------------------------------------------------- завдання 2
def task2():
    series = [("Без синхронізації, 0,005 с", f"race_none_0.005_{TOKEN}.csv"),
              ("Без синхронізації, 1e-6 с", f"race_none_1e-6_{TOKEN}.csv"),
              ("L (Lock)", f"race_L_{TOKEN}.csv"),
              ("S (Semaphore)", f"race_S_{TOKEN}.csv"),
              ("G (локальне накопичення)", f"race_G_{TOKEN}.csv")]
    res = {}
    for name, fn in series:
        rows = read(D / fn)
        if rows is None:
            continue
        lost = col(rows, "lost")
        # Підтримуємо обидві версії CSV: попередню (time_us) і за схемою 2 (time_ns).
        if rows and "time_ns" in rows[0]:
            tus = [x / 1000.0 for x in col(rows, "time_ns")]
        else:
            tus = col(rows, "time_us")
        k = int(common.WARMUP_FRAC * len(lost))
        res[name] = {"file": fn, "R": len(lost),
                     "bad_all": int(sum(1 for x in lost if x > 0)),
                     "bad_kept": int(sum(1 for x in lost[k:] if x > 0)), "kept": len(lost) - k,
                     "lost": st(lost), "time_us": st(tus), "lost_raw": lost}
    if not res:
        return
    base1 = res.get("Без синхронізації, 0,005 с", {}).get("time_us", {}).get("median")
    base2 = res.get("Без синхронізації, 1e-6 с", {}).get("time_us", {}).get("median")
    rows = []
    for name, r in res.items():
        base = base1 if "0,005" in name else base2
        ratio = r["time_us"]["median"] / base if base else None
        r["ratio"] = ratio
        rows.append([name, f"{r['bad_all']} з {r['R']} ({100 * r['bad_all'] / r['R']:.1f} %)".replace(".", ","),
                     f(r["lost"]["median"], 0), f(r["lost"]["p95"], 0), f(r["lost"]["max"], 0),
                     f(r["time_us"]["median"]), f(r["time_us"]["p95"]), f(ratio, 2)])
    table(f"Таблиця 2 – Порівняння засобів синхронізації [{TOKEN}] (час — мкс; статистика після відкидання 5 % розігріву)",
          ["Версія", "Повторів із втратами", "lost: медіана", "lost: p95", "lost: max",
           "Медіана часу, мкс", "p95 часу, мкс", "Відносно версії без синхронізації"], rows)
    OUT["task2"] = {k: {kk: vv for kk, vv in v.items() if kk != "lost_raw"} for k, v in res.items()}
    if plt is None:
        return
    key = "Без синхронізації, 1e-6 с"
    if key in res:
        fig, ax = plt.subplots(figsize=(6, 3.6))
        data = np.asarray(res[key]["lost_raw"])
        ax.hist(data, bins=min(40, int(data.max()) + 1 if data.max() > 0 else 1), color="#2F5597")
        ax.set_xlabel("Втрачені оновлення за повтор, шт.")
        ax.set_ylabel("Кількість повторів")
        ax.set_title(f"Гістограма lost, інтервал 1e-6 с, R = {len(data)} [{TOKEN}]")
        save(fig, "task2_hist_lost")
    names = list(res)
    med = [res[n]["time_us"]["median"] for n in names]
    p95 = [res[n]["time_us"]["p95"] for n in names]
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    ax.bar(range(len(names)), med, color="#2F5597",
           yerr=[[0] * len(names), [max(0, a - b) for a, b in zip(p95, med)]], capsize=4)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([n.replace(", ", "\n") for n in names], fontsize=7)
    ax.set_ylabel("Час повтору, мкс (медіана, «вус» — p95)")
    ax.set_title(f"Ціна способів синхронізації [{TOKEN}]")
    save(fig, "task2_bars_time")


# ---------------------------------------------------------------------- завдання 3
def task3():
    waits = read(D / f"buffer_waits_{TOKEN}.csv")
    out = {}
    if waits:
        rows = [[r["mode"], r["run"], r["waits_put"], r["waits_get"], r["check"]] for r in waits]
        table(f"Таблиця 3 – Обмежений буфер B = {V.B}, P = {V.P}, C = {V.C}, ITEMS = {common.ITEMS} [{TOKEN}]",
              ["Режим", "Запуск", "waits_put", "waits_get", "Перевірка"], rows)
        out["waits"] = waits
    lat_rows = []
    for m, name in (("a", "a) рівновага"), ("b", "b) повільний споживач"), ("c", "c) повільний виробник")):
        rows = read(D / f"buffer_{m}_{TOKEN}.csv")
        if rows is None:
            continue
        runs = sorted({r["run"] for r in rows}, key=int)
        vals = []
        for run in runs:
            lat = [float(r["latency_ns"]) / 1000.0 for r in rows if r["run"] == run]
            vals += lat[int(common.WARMUP_FRAC * len(lat)):]
        s = st(vals, warm=False)
        out[f"latency_{m}"] = s
        lat_rows.append([name, s["count"], f(s["median"]), f(s["mean"]), f(s["p95"]), f(s["p99"]), f(s["max"])])
    if lat_rows:
        table(f"Затримка елемента в буфері, мкс (3 запуски разом, після відкидання 5 % кожного) [{TOKEN}]",
              ["Режим", "N", "медіана", "середнє", "p95", "p99", "max"], lat_rows)
    bi = read(D / f"buffer_if_{TOKEN}.csv")
    if bi:
        table(f"Дослід «if замість while», C = 3, режим a, interval 1e-6 [{TOKEN}]",
              ["Запуск", "отримано", "унікальних", "дублікатів", "пропущено", "STOP покладено",
               "завершилось по STOP", "count в кінці"],
              [[r["t_idx"], r["received"], r["unique"], r["duplicates"], r["missing"], r["stops_put"],
                r["ended_by_stop"], r["final_count"]] for r in bi])
        out["buffer_if"] = bi
    OUT["task3"] = out


# ---------------------------------------------------------------------- завдання 4
def task4():
    ph = read(D / f"phases_{TOKEN}.csv")
    if ph:
        table(f"Таблиця 4 – Фази A–D (власні лічильники процесу; VSZ = Committed, КБ) [{TOKEN}]",
              ["Фаза", "VSZ/Committed, КБ", "Private, КБ", "RSS/WorkingSet, КБ", "Page faults", "Приріст"],
              [[r["phase"], r["vsz_kb"], r["private_kb"], r["rss_kb"], r["page_faults"], r["page_faults_delta"]]
               for r in ph])
        OUT["phases"] = ph
    pg = read(D / f"pages_{TOKEN}.csv")
    if pg:
        p1 = np.asarray(col(pg, "pass1_ns")); p2 = np.asarray(col(pg, "pass2_ns"))
        s1, s2 = st(p1), st(p2)
        cost = s1["median"] - s2["median"]
        OUT["pages"] = {"pass1": s1, "pass2": s2, "minor_fault_cost_ns": cost,
                        "mean_diff_ns": s1["mean"] - s2["mean"], "pages": len(p1)}
        table(f"Час дотику до сторінки, нс ({len(p1)} сторінок) [{TOKEN}]",
              ["Прохід", "N", "min", "медіана", "середнє", "p95", "p99", "max"],
              [[n, s["count"], f(s["min"], 0), f(s["median"], 0), f(s["mean"], 0), f(s["p95"], 0),
                f(s["p99"], 0), f(s["max"], 0)] for n, s in (("pass1", s1), ("pass2", s2))])
        MD.append(f"\nОцінка ціни minor fault = медіана(pass1) − медіана(pass2) = **{cost:.0f} нс**; "
                  f"за різницею середніх = {s1['mean'] - s2['mean']:.0f} нс.")
        if plt is not None:
            k = int(common.WARMUP_FRAC * len(p1))
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.boxplot([p1[k:], p2[k:]], tick_labels=["pass1 (перший дотик)", "pass2 (повторний)"], showfliers=False)
            ax.set_yscale("log")
            ax.set_ylabel("Час запису 1 байта в сторінку, нс (log)")
            ax.set_title(f"Перший і повторний дотик до сторінок [{TOKEN}]")
            save(fig, "task4_box_pages")
            fig, ax = plt.subplots(figsize=(6.5, 3.6))
            bins = np.logspace(math.log10(max(1, min(p1.min(), p2.min()))), math.log10(max(p1.max(), p2.max())), 60)
            ax.hist(p1[k:], bins=bins, alpha=.6, label="pass1")
            ax.hist(p2[k:], bins=bins, alpha=.6, label="pass2")
            ax.set_xscale("log"); ax.set_xlabel("нс (log)"); ax.set_ylabel("Кількість сторінок"); ax.legend()
            ax.set_title(f"Гістограми часу дотику [{TOKEN}]")
            save(fig, "task4_hist_pages")


# ---------------------------------------------------------------------- завдання 5
def task5():
    out = {}
    for tag in ("write", "touch"):
        rows = read(D / f"shm_{tag}_{TOKEN}.csv")
        if rows:
            out[f"shm_{tag}"] = rows
            table(f"Спільна пам'ять 5.5.1, нащадок: {tag} [{TOKEN}]",
                  ["Процес", "PID", "RSS/WorkingSet, КБ", "Private, КБ", "VSZ/Committed, КБ",
                   "Вільна RAM до, МБ", "після батька, МБ", "після нащадка, МБ"],
                  [[r["role"], r["pid"], r["rss_kb"], r["private_kb"], r["vsz_kb"], r["free_before_mb"],
                    r["free_after_parent_mb"], r["free_after_child_mb"]] for r in rows])
    sp = read(D / f"spawn_{TOKEN}.csv")
    if sp:
        ms = col(sp, "start_to_ready_ms")
        s = st(ms, warm=False)
        out["spawn"] = {"rows": sp, "ms": s}
        table(f"Spawn 5.5.3 [{TOKEN}]", ["Запуск", "старт→готовий, мс", "RSS нащадка, КБ", "RSS батька, КБ"],
              [[int(r["t_idx"]) + 1, r["start_to_ready_ms"], r["child_rss_kb"], r["parent_rss_kb"]] for r in sp])
        MD.append(f"\nМедіана часу старт→готовий: **{s['median']:.1f} мс**.")
    OUT["task5"] = out


# ---------------------------------------------------------------------- завдання 6
def task6():
    rows = read(D / f"io_summary_{TOKEN}.csv")
    if not rows:
        return
    tab = []
    for r in rows:
        blk = int(r["block_bytes"])
        iops = float(r["iops"]); mibs = float(r["mib_per_s"])
        pred = iops * blk / 1048576
        dev = abs(mibs - pred) / pred * 100 if pred else 0
        r["pred_mibs"] = pred
        r["dev_pct"] = dev
        tab.append([r["mode"], blk, r["ops"], r["median_us"], r["p95_us"], r["p99_us"], f(iops, 0), f(mibs, 1),
                    f(pred, 1), f(dev, 2), r["final_fsync_ms"]])
    table(f"Таблиця 5 – Запис: затримка, IOPS, МіБ/с [{TOKEN}]",
          ["Режим", "Блок, Б", "Операцій", "медіана, мкс", "p95, мкс", "p99, мкс", "IOPS", "МіБ/с",
           "IOPS×блок, МіБ/с", "відхилення, %", "фінальний fsync, мс"], tab)
    OUT["task6"] = {"summary": rows}
    rd = read(D / f"io_read_{TOKEN}.csv")
    if rd:
        table(f"Читання файлу 256 МіБ блоками по 1 МБ [{TOKEN}]", ["Читання", "с", "МіБ/с"],
              [[int(r["t_idx"]) + 1, r["seconds"], r["mib_per_s"]] for r in rd])
        OUT["task6"]["read"] = rd
    if plt is None:
        return
    modes = sorted({r["mode"] for r in rows})
    fig, ax = plt.subplots(figsize=(6.5, 4))
    for m in modes:
        sub = [r for r in rows if r["mode"] == m]
        ax.plot([int(r["block_bytes"]) for r in sub], [float(r["median_us"]) for r in sub], "o-", label=m)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Розмір блоку, Б"); ax.set_ylabel("Медіана затримки, мкс"); ax.legend()
    ax.set_title(f"Затримка запису від розміру блоку [{TOKEN}]")
    save(fig, "task6_latency")
    fig, ax = plt.subplots(figsize=(6.5, 4))
    for m in modes:
        sub = [r for r in rows if r["mode"] == m]
        ax.plot([int(r["block_bytes"]) for r in sub], [float(r["mib_per_s"]) for r in sub], "o-", label=m)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Розмір блоку, Б"); ax.set_ylabel("Пропускна здатність, МіБ/с"); ax.legend()
    ax.set_title(f"Пропускна здатність від розміру блоку [{TOKEN}]")
    save(fig, "task6_throughput")


# ---------------------------------------------------------------------- завдання 7
def task7():
    out = {}
    for label, y, ylabel, title in (("mem", "rss_kb", "RSS / WorkingSet, КБ", "RSS у часі (завдання 4)"),
                                    ("io", "write_bytes", "write_bytes (WriteTransferCount), МіБ",
                                     "Записані байти у часі (завдання 6, buffered 64 КБ)")):
        rows = read(D / f"monitor_{label}_{TOKEN}.csv")
        if not rows:
            continue
        ts = np.asarray(col(rows, "ts_ms"))
        iv = np.diff(ts)
        out[label] = {"points": len(rows), "delta_set_s": V.DELTA,
                      "interval_ms": {"median": float(np.median(iv)), "p95": float(np.percentile(iv, 95)),
                                      "max": float(iv.max())}}
        na = {c: sum(1 for r in rows if r[c] == "NA") for c in rows[0] if c not in ("t_idx", "ts_ms")}
        out[label]["na_counts"] = na
        if plt is not None:
            vals = np.asarray(col(rows, y), dtype=float)
            if y == "write_bytes":
                vals = vals / 1048576
            t = (ts[:len(vals)] - ts[0]) / 1000.0
            fig, ax = plt.subplots(figsize=(7, 3.6))
            ax.plot(t, vals, lw=1.2, color="#2F5597")
            ax.set_xlabel("Час, с"); ax.set_ylabel(ylabel); ax.set_title(f"{title} [{TOKEN}]")
            save(fig, f"task7_{label}")
    if out:
        table(f"Реальний інтервал між знімками resource_monitor (Δ = {str(V.DELTA).replace('.', ',')} с) [{TOKEN}]",
              ["Серія", "Точок", "медіана, мс", "p95, мс", "max, мс"],
              [[k, v["points"], f(v["interval_ms"]["median"]), f(v["interval_ms"]["p95"]), f(v["interval_ms"]["max"])]
               for k, v in out.items()])
    OUT["task7"] = out


def bonus():
    out = {}
    rows = []
    for m in ("deadlock", "ordered"):
        r = read(D / f"deadlock_{m}_{TOKEN}.csv")
        if r:
            n = len(r); d = sum(int(x["deadlocked"]) for x in r)
            out[m] = {"repeats": n, "deadlocks": d, "time_ms": st(col(r, "time_ms"), warm=False)}
            rows.append([m, n, d, f(out[m]["time_ms"]["median"])])
    if rows:
        table(f"Бонус: взаємоблокування [{TOKEN}]", ["Версія", "Повторів", "Блокувань", "Медіана часу, мс"], rows)
    OUT["bonus"] = out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(common.DATA))
    a = ap.parse_args()
    D = Path(a.data)
    MD.append(f"# Результати ЛР3, n = {V.n}, TOKEN = {TOKEN}")
    for fn in (task2, task3, task4, task5, task6, task7, bonus):
        try:
            fn()
        except Exception as e:  # один збій не має зупиняти решту
            print(f"!!! {fn.__name__}: {type(e).__name__}: {e}")
    (D / f"analysis_{TOKEN}.json").write_text(json.dumps(OUT, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (D / f"analysis_{TOKEN}.md").write_text("\n".join(MD), encoding="utf-8")
    print(f"Готово: analysis_{TOKEN}.json, analysis_{TOKEN}.md" + ("" if plt else " (matplotlib відсутній — без графіків)"))
