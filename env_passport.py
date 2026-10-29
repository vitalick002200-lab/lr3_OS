"""Завдання 1. Паспорт середовища (версія 2).

Запускає штатні команди Windows (PowerShell), виводить результат у консоль
(зробіть скриншот розділів "Розмір сторінки" та "Swap / стиснення"), зберігає все
у data/passport_<TOKEN>.txt і оновлює рядки OS / TOOLCHAIN у variant.txt.
Наприкінці перевіряє власні лічильники процесу (procmetrics) штатною командою Get-Process.
"""
import argparse
import mmap
import os
import platform
import subprocess
import sys
import sysconfig
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import procmetrics  # noqa: E402

IS_WIN = sys.platform == "win32"


def ps(cmd, timeout=90):
    """Виконує команду PowerShell, повертає (текст, код)."""
    if not IS_WIN:
        return "(PowerShell недоступний на цій ОС)", 1
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        txt = (r.stdout or "").strip()
        if r.stderr.strip():
            txt += "\n[stderr] " + r.stderr.strip()
        return txt, r.returncode
    except Exception as e:  # noqa: BLE001
        return f"(помилка запуску: {e})", 1


def section(title, command, text):
    common.log(f"\n--- {title}")
    common.log(f"Команда/джерело: {command}")
    common.log(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=common.DEFAULT_N)
    args = ap.parse_args()
    v = common.variant(args.n)
    common.setup_log(v, "env_passport.py")
    common.log(f"Паспорт середовища, {v.describe()}")

    # ---- ОС, CPU, RAM
    c = "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture | Format-List"
    os_txt, _ = ps(c)
    section("ОС", c, os_txt if IS_WIN else platform.platform())
    cap = ver = build = ""
    for line in os_txt.splitlines():
        if line.startswith("Caption"):
            cap = line.split(":", 1)[1].strip()
        elif line.startswith("Version"):
            ver = line.split(":", 1)[1].strip()
        elif line.startswith("BuildNumber"):
            build = line.split(":", 1)[1].strip()
    os_line = f"{cap} (версія {ver}, збірка {build}), {platform.machine()}" if cap else platform.platform()

    c = "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | Format-List"
    section("CPU і кількість логічних процесорів L", c, ps(c)[0])
    common.log(f"Python: os.cpu_count() = {os.cpu_count()}  (L)")

    c = ("Get-CimInstance Win32_ComputerSystem | Select-Object @{n='TotalRAM_GB';e={[math]::Round($_.TotalPhysicalMemory/1GB,2)}} "
         "| Format-List")
    section("RAM (всього)", c, ps(c)[0])
    c = ("Get-CimInstance Win32_OperatingSystem | Select-Object @{n='FreeRAM_MB';e={[math]::Round($_.FreePhysicalMemory/1024)}},"
         "@{n='TotalVisible_MB';e={[math]::Round($_.TotalVisibleMemorySize/1024)}} | Format-List")
    section("Вільна RAM на початку роботи", c, ps(c)[0])

    # ---- сторінка
    common.log("\n--- Розмір сторінки пам'яті")
    common.log('Команда/джерело: python -c "import mmap; print(mmap.PAGESIZE)"')
    common.log(f"mmap.PAGESIZE = {mmap.PAGESIZE}  (mmap.ALLOCATIONGRANULARITY = {mmap.ALLOCATIONGRANULARITY})")

    # ---- swap / стиснення
    c = "Get-CimInstance Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage | Format-List"
    section("Swap / pagefile (МБ)", c, ps(c)[0])
    c = "Get-MMAgent | Select-Object MemoryCompression,PageCombining,ApplicationLaunchPrefetching | Format-List"
    section("Стиснення пам'яті: увімкнено?", c, ps(c)[0])
    c = ("Get-Process -Name 'Memory Compression' -ErrorAction SilentlyContinue | "
         "Select-Object Name,Id,@{n='WorkingSet_MB';e={[math]::Round($_.WorkingSet64/1MB,1)}} | Format-List")
    section("Стиснення пам'яті: скільки зайнято (процес Memory Compression)", c, ps(c)[0])

    # ---- накопичувач
    drive = Path(common.ROOT).drive.rstrip(":") or "C"
    c = f"Get-Volume -DriveLetter {drive} | Select-Object DriveLetter,FileSystem,FileSystemLabel,DriveType | Format-List"
    section(f"Файлова система робочого каталогу ({common.ROOT})", c, ps(c)[0])
    c = "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,@{n='Size_GB';e={[math]::Round($_.Size/1GB)}} | Format-List"
    section("Тип накопичувача (MediaType: SSD/HDD)", c, ps(c)[0])
    if "onedrive" in str(common.ROOT).lower() or "icloud" in str(common.ROOT).lower():
        common.log("\n!!! УВАГА: каталог лежить у OneDrive/iCloud - перенесіть його, наприклад, у C:\\lab3_futumaichuk_24 !!!")

    # ---- Python
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    common.log("\n--- Мова, версія інтерпретатора")
    common.log("Команда/джерело: python --version; sys.version; sys._is_gil_enabled()")
    common.log(f"sys.version = {sys.version}")
    common.log(f"реалізація = {sys.implementation.name}, GIL увімкнено: {gil}, "
               f"Py_GIL_DISABLED = {sysconfig.get_config_var('Py_GIL_DISABLED')}")
    common.log(f"sys.getswitchinterval() = {sys.getswitchinterval()} с")
    common.log(f"Накладні витрати таймера perf_counter_ns (медіана порожнього інтервалу): {common.timer_overhead_ns()} нс")
    if sys.version_info < (3, 10):
        common.log("!!! Потрібен Python 3.10 або новіший !!!")

    toolchain = f"CPython {platform.python_version()} ({'з GIL' if gil else 'free-threaded, без GIL'})"
    txt = common.write_variant_txt(v, os_line, toolchain)
    common.log("\n--- variant.txt оновлено:")
    common.log(txt)

    # ---- самоперевірка лічильників (потрібна для resource_monitor)
    common.log("--- Самоперевірка лічильників процесу (скрипт vs штатна команда)")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        import time
        time.sleep(1.5)
        probe = procmetrics.open_probe(child.pid)
        s = probe.sample()
        probe.close()
        common.log(f"procmetrics (системні API) для PID {child.pid}: {s}")
        if IS_WIN:
            c = (f"Get-Process -Id {child.pid} | Select-Object Id,WorkingSet64,PrivateMemorySize64,"
                 f"VirtualMemorySize64 | Format-List; "
                 f"'PageFaults (Win32_Process): ' + (Get-CimInstance Win32_Process -Filter 'ProcessId={child.pid}').PageFaults")
            section("Ті самі метрики штатною командою", c, ps(c)[0])
            common.log("Очікуйте: WorkingSet64/1024 ~ rss_kb, PrivateMemorySize64/1024 ~ private_kb "
                       "(розбіжність у кілька КБ нормальна). vsz_kb - сума committed-регіонів, як 'Committed' у VMMap.")
    except procmetrics.ProcessGone as e:
        common.log(f"самоперевірка не вдалась: {e}")
    finally:
        child.kill()
    common.log("\nГотово. Зробіть скриншоти розділів 'Розмір сторінки' і 'Swap / стиснення'.")


if __name__ == "__main__":
    main()
