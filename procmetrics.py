"""Зчитування метрик процесу за PID.

Windows (основний бекенд "native") - системні API через ctypes, без сторонніх модулів:
  rss_kb        = WorkingSetSize            (K32GetProcessMemoryInfo)  - те саме, що WorkingSet64
  private_kb    = PrivateUsage              (K32GetProcessMemoryInfo)  - те саме, що PrivateMemorySize64
  vsz_kb        = сума регіонів у стані MEM_COMMIT (VirtualQueryEx)    - "Committed" у VMMap
  threads       = cntThreads                (CreateToolhelp32Snapshot / Process32NextW)
  page_faults   = PageFaultCount            (K32GetProcessMemoryInfo)  - те саме, що Win32_Process.PageFaults
  read_bytes    = ReadTransferCount         (GetProcessIoCounters)
  write_bytes   = WriteTransferCount        (GetProcessIoCounters)
Недоступна метрика повертається як None (у CSV це NA).

Бекенд "psutil" - необов'язковий запасний варіант (pip install psutil).
На Linux є мінімальний бекенд через /proc - його використано лише для перевірки логіки скриптів.
"""
import os
import sys
import time

IS_WIN = sys.platform == "win32"
FIELDS = ["rss_kb", "vsz_kb", "private_kb", "threads", "page_faults", "read_bytes", "write_bytes"]


class ProcessGone(Exception):
    """Процесу з таким PID немає (або він завершився)."""


# =============================================================================== Windows
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_VM_READ = 0x0010
    STILL_ACTIVE = 259
    MEM_COMMIT = 0x1000
    TH32CS_SNAPPROCESS = 0x00000002
    ERROR_ACCESS_DENIED = 5
    ERROR_INVALID_PARAMETER = 87
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    _mbi_fields = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
    ]
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        _mbi_fields.append(("PartitionId", wintypes.WORD))
    _mbi_fields += [
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]

    class MEMORY_BASIC_INFORMATION(ctypes.Structure):
        _fields_ = _mbi_fields

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
                                            wintypes.DWORD]
    k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
    k32.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IO_COUNTERS)]
    k32.GetProcessIoCounters.restype = wintypes.BOOL
    k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                   ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.restype = wintypes.BOOL

    _MAX_ADDR = 0x7FFFFFFFFFFF if ctypes.sizeof(ctypes.c_void_p) == 8 else 0x7FFF0000

    def _thread_count(pid):
        """Кількість потоків процесу через Toolhelp32; None, якщо процесу немає."""
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == INVALID_HANDLE:
            return -1  # снімок не вдався: невідомо
        try:
            pe = PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k32.Process32FirstW(snap, ctypes.byref(pe))
            while ok:
                if pe.th32ProcessID == pid:
                    return int(pe.cntThreads)
                ok = k32.Process32NextW(snap, ctypes.byref(pe))
            return None
        finally:
            k32.CloseHandle(snap)

    def _committed_bytes(handle):
        """Сума розмірів регіонів у стані MEM_COMMIT (аналог 'Committed' у VMMap)."""
        mbi = MEMORY_BASIC_INFORMATION()
        size = ctypes.sizeof(mbi)
        addr = 0
        total = 0
        while addr < _MAX_ADDR:
            r = k32.VirtualQueryEx(handle, ctypes.c_void_p(addr), ctypes.byref(mbi), size)
            if r == 0:
                break
            if mbi.State == MEM_COMMIT:
                total += mbi.RegionSize
            nxt = (mbi.BaseAddress or 0) + mbi.RegionSize
            if nxt <= addr:
                break
            addr = nxt
        return total

    class NativeProbe:
        def __init__(self, pid):
            self.pid = int(pid)
            self.h = None
            self.can_query = False
            h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, self.pid)
            if h:
                self.h = h
                self.can_query = True
                return
            err = ctypes.get_last_error()
            if err == ERROR_INVALID_PARAMETER:
                raise ProcessGone(f"процесу з PID {pid} не існує")
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
            if h:
                self.h = h
            elif _thread_count(self.pid) is None:
                raise ProcessGone(f"процесу з PID {pid} не існує")
            # інакше процес існує, але доступу немає: працюємо в режимі NA

        def alive(self):
            if self.h:
                # GetExitCodeProcess не потребує права SYNCHRONIZE (на відміну від WaitForSingleObject)
                code = wintypes.DWORD(0)
                if k32.GetExitCodeProcess(self.h, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return _thread_count(self.pid) is not None
            return _thread_count(self.pid) is not None

        def sample(self):
            out = {k: None for k in FIELDS}
            thr = _thread_count(self.pid)
            if thr is None:
                raise ProcessGone(f"процес {self.pid} завершився")
            out["threads"] = None if thr == -1 else thr
            if self.h:
                pmc = PROCESS_MEMORY_COUNTERS_EX()
                pmc.cb = ctypes.sizeof(pmc)
                if k32.K32GetProcessMemoryInfo(self.h, ctypes.byref(pmc), pmc.cb):
                    out["rss_kb"] = pmc.WorkingSetSize // 1024
                    out["private_kb"] = pmc.PrivateUsage // 1024
                    out["page_faults"] = int(pmc.PageFaultCount)
                io = IO_COUNTERS()
                if k32.GetProcessIoCounters(self.h, ctypes.byref(io)):
                    out["read_bytes"] = int(io.ReadTransferCount)
                    out["write_bytes"] = int(io.WriteTransferCount)
                if self.can_query:
                    out["vsz_kb"] = _committed_bytes(self.h) // 1024
            if not self.alive():
                raise ProcessGone(f"процес {self.pid} завершився")
            return out

        def close(self):
            if self.h:
                k32.CloseHandle(self.h)
                self.h = None


# =============================================================================== psutil (запасний)
class PsutilProbe:
    """Запасний бекенд. На Windows vsz_kb = vms = PagefileUsage (тобто private commit)."""

    def __init__(self, pid):
        import psutil  # noqa: PLC0415
        self.psutil = psutil
        self.pid = int(pid)
        try:
            self.p = psutil.Process(self.pid)
        except psutil.NoSuchProcess as e:
            raise ProcessGone(f"процесу з PID {pid} не існує") from e

    def alive(self):
        return self.p.is_running()

    def sample(self):
        ps = self.psutil
        out = {k: None for k in FIELDS}
        try:
            mi = self.p.memory_info()
            out["rss_kb"] = mi.rss // 1024
            out["vsz_kb"] = mi.vms // 1024
            out["private_kb"] = getattr(mi, "private", mi.vms) // 1024
            out["page_faults"] = getattr(mi, "num_page_faults", None)
            out["threads"] = self.p.num_threads()
            try:
                io = self.p.io_counters()
                out["read_bytes"] = io.read_bytes
                out["write_bytes"] = io.write_bytes
            except Exception:  # noqa: BLE001
                pass
        except ps.NoSuchProcess as e:
            raise ProcessGone(f"процес {self.pid} завершився") from e
        except ps.AccessDenied:
            pass
        return out

    def close(self):
        pass


# =============================================================================== Linux (для перевірки логіки)
class ProcFsProbe:
    def __init__(self, pid):
        self.pid = int(pid)
        if not os.path.isdir(f"/proc/{self.pid}"):
            raise ProcessGone(f"процесу з PID {pid} не існує")

    def alive(self):
        try:
            with open(f"/proc/{self.pid}/stat") as f:
                return f.read().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return False

    def sample(self):
        out = {k: None for k in FIELDS}
        try:
            st = {}
            with open(f"/proc/{self.pid}/status") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    st[k] = v.strip()
            out["rss_kb"] = int(st["VmRSS"].split()[0])
            out["vsz_kb"] = int(st["VmSize"].split()[0])
            out["private_kb"] = int(st.get("RssAnon", "0 kB").split()[0])
            out["threads"] = int(st["Threads"])
            with open(f"/proc/{self.pid}/stat") as f:
                rest = f.read().rsplit(")", 1)[1].split()
            out["page_faults"] = int(rest[7]) + int(rest[9])   # minflt + majflt
        except (OSError, KeyError) as e:
            raise ProcessGone(f"процес {self.pid} завершився") from e
        try:
            with open(f"/proc/{self.pid}/io") as f:
                io = dict(line.split(": ") for line in f.read().splitlines())
            out["read_bytes"] = int(io["rchar"])
            out["write_bytes"] = int(io["wchar"])
        except (OSError, KeyError, ValueError):
            pass
        return out

    def close(self):
        pass


def open_probe(pid, backend="native"):
    if backend == "psutil":
        return PsutilProbe(pid)
    if IS_WIN:
        return NativeProbe(pid)
    if os.path.isdir("/proc"):
        return ProcFsProbe(pid)
    return PsutilProbe(pid)


def own_sample():
    """Метрики поточного процесу (для знімків у mem_touch / shm_demo)."""
    p = open_probe(os.getpid())
    try:
        return p.sample()
    finally:
        p.close()


def fmt_na(v):
    return "NA" if v is None else str(v)


def fmt_kb(v):
    return "NA" if v is None else f"{v:,}".replace(",", " ")


if __name__ == "__main__":
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else os.getpid()
    pr = open_probe(pid)
    print(pr.sample())
    pr.close()