"""Rolling performance window behind the status charts.

The charts show the last minute of CPU, memory and traffic.  Recording that
window belongs here rather than in the browser: a page that accumulates its own
samples starts from an empty chart every time it is opened, and it only sees the
seconds it was on screen for.

Sampling is driven by the same scheduled job that advances the traffic
baseline.  ``psutil.cpu_percent`` without an interval reports the load since its
own previous call, so letting each request sample would hand every poller a
different slice of the same second, exactly the problem described in
:mod:`core.traffic_monitor`.  Requests only read the recorded window.
"""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from typing import Callable, Deque, List, Optional

import psutil

from .mihomo_controller import SERVICE_NAME


class PerformanceHistory:
    """The most recent samples, oldest first."""

    # One sample per second, so the window length is also the sample count.
    WINDOW_SECONDS = 60

    # A byte-counter delta over a single second jitters enough to make the
    # traffic charts hard to read, so the reported rates are a moving average.
    SMOOTH_SAMPLES = 5

    IDLE_MEMORY = {"percent": 0.0, "total": 0, "used": 0}
    IDLE_MIHOMO = {"cpu_percent": 0.0, "memory_percent": 0.0, "memory_mb": 0}

    def __init__(
        self,
        cpu_reader: Optional[Callable[[], List[float]]] = None,
        memory_reader: Optional[Callable[[], dict]] = None,
        mihomo_reader: Optional[Callable[[], dict]] = None,
    ):
        self._cpu_reader = cpu_reader or self._read_cpu
        self._memory_reader = memory_reader or self._read_memory
        self._mihomo_reader = mihomo_reader or self._read_mihomo
        self._mihomo_proc: Optional[psutil.Process] = None
        self._samples: Deque[dict] = deque(maxlen=self.WINDOW_SECONDS)
        self._lock = threading.Lock()

    @staticmethod
    def _read_cpu() -> List[float]:
        # interval=None reports the load since the previous call, which is this
        # class's own sampling interval; a blocking interval would instead stall
        # the scheduled job for that long.
        return psutil.cpu_percent(interval=None, percpu=True)

    @staticmethod
    def _read_memory() -> dict:
        memory = psutil.virtual_memory()
        return {
            "percent": memory.percent,
            "total": int(memory.total / (1024 * 1024)),
            "used": int((memory.total - memory.available) / (1024 * 1024)),
        }

    def _open_mihomo_process(self) -> Optional[psutil.Process]:
        try:
            result = subprocess.run(
                ['pgrep', '-x', SERVICE_NAME],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return None
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                return psutil.Process(int(line))
            except (ValueError, psutil.Error):
                continue
        return None

    def _read_mihomo(self) -> dict:
        proc = self._mihomo_proc
        try:
            if proc is None or not proc.is_running():
                proc = self._open_mihomo_process()
                self._mihomo_proc = proc
                if proc is None:
                    return dict(self.IDLE_MIHOMO)
                # The first cpu_percent call after attaching is always 0.
                proc.cpu_percent(interval=None)
                cpu = 0.0
            else:
                cpu = proc.cpu_percent(interval=None)
            cores = psutil.cpu_count() or 1
            rss = proc.memory_info().rss
            return {
                "cpu_percent": round(cpu / cores, 1),
                "memory_percent": round(proc.memory_percent(), 1),
                "memory_mb": int(rss / (1024 * 1024)),
            }
        except (psutil.Error, OSError):
            self._mihomo_proc = None
            return dict(self.IDLE_MIHOMO)

    def sample(self, network: dict) -> None:
        """Record one second of measurements.

        Only the sampling job should call this; see the module docstring.  The
        traffic rates are passed in because the job measures them over the very
        same interval.
        """
        cores = self._cpu_reader() or []
        mihomo = dict(self._mihomo_reader() or self.IDLE_MIHOMO)
        with self._lock:
            self._samples.append({
                "cpu": {
                    "core {0}".format(index + 1): usage
                    for index, usage in enumerate(cores)
                },
                "cpu_percent": round(sum(cores) / len(cores), 1) if cores else 0.0,
                "memory": self._memory_reader(),
                "mihomo": {
                    "cpu_percent": float(mihomo.get("cpu_percent") or 0.0),
                    "memory_percent": float(mihomo.get("memory_percent") or 0.0),
                    "memory_mb": int(mihomo.get("memory_mb") or 0),
                },
                "upload": network.get("upload", 0.0),
                "download": network.get("download", 0.0),
            })

    def snapshot(self) -> dict:
        """Return the newest reading plus the whole window for the charts."""
        with self._lock:
            samples = list(self._samples)

        latest = samples[-1] if samples else None
        return {
            "cpu": dict(latest["cpu"]) if latest else {},
            "memory": dict(latest["memory"]) if latest else dict(self.IDLE_MEMORY),
            "mihomo": dict(latest["mihomo"]) if latest else dict(self.IDLE_MIHOMO),
            "history": {
                "window": self.WINDOW_SECONDS,
                "cpu": [sample["cpu_percent"] for sample in samples],
                "cpu_mihomo": [sample["mihomo"]["cpu_percent"] for sample in samples],
                "memory": [sample["memory"]["percent"] for sample in samples],
                "memory_mihomo": [sample["mihomo"]["memory_percent"] for sample in samples],
                "upload": self._smooth([sample["upload"] for sample in samples]),
                "download": self._smooth([sample["download"] for sample in samples]),
            },
        }

    @classmethod
    def _smooth(cls, rates: List[float]) -> List[float]:
        averaged = []
        for index in range(len(rates)):
            span = rates[max(0, index - cls.SMOOTH_SAMPLES + 1):index + 1]
            averaged.append(round(sum(span) / len(span), 2))
        return averaged
