"""Traffic-rate sampling for the side-router.

The host's aggregate network counters are not a good measurement for a
transparent side-router: one client flow can cross the same host in both
directions, and proxy traffic can be counted more than once.  The iptables
rules installed by ``script/config_iptable.sh`` maintain counters at the
client-facing boundaries instead:

* upload: packets entering the router from the LAN;
* download: packets forwarded to the LAN or emitted by the proxy to the LAN.

This module only samples those counters.  It deliberately keeps a system
counter fallback for macOS/development environments where the Linux rules do
not exist.

A rate is a delta over an interval, so whoever advances the baseline defines
the interval.  Sampling is therefore driven by a single scheduled job rather
than by incoming HTTP requests: several pages poll ``/get_performance``
independently, and letting each request advance the baseline would slice one
second into unrelated fragments and hand every caller a different rate.
Requests only read the most recent rate via :meth:`TrafficMonitor.latest`.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable, Optional, Tuple

import psutil


UPLOAD_CHAIN = "V2RAYPI_TRAFFIC_UP"
DOWNLOAD_CHAIN = "V2RAYPI_TRAFFIC_DOWN"


class TrafficMonitor:
    """Convert monotonically increasing byte counters into KB/s rates."""

    IDLE_RATES = {"upload": 0.0, "download": 0.0, "source": None}

    def __init__(
        self,
        counter_reader: Optional[Callable[[str], Optional[int]]] = None,
        system_reader: Optional[Callable[[], Tuple[int, int]]] = None,
    ):
        self._counter_reader = counter_reader or self._read_iptables_counter
        self._system_reader = system_reader or self._read_system_counters
        self._last_counters: Optional[Tuple[str, int, int]] = None
        self._last_time: Optional[float] = None
        self._latest_rates: Optional[dict] = None
        self._lock = threading.Lock()

    @staticmethod
    def _read_iptables_counter(chain: str) -> Optional[int]:
        """Return the byte counter of the single RETURN rule in *chain*.

        ``-x`` is important here: without it iptables may abbreviate large
        counters (for example ``1.2M``), which cannot be safely differentiated
        from a real number when calculating deltas.
        """
        try:
            result = subprocess.run(
                ["iptables", "-t", "mangle", "-L", chain, "-v", "-x", "-n"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
                timeout=1,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0].isdigit() and fields[1].isdigit():
                return int(fields[1])
        return None

    @staticmethod
    def _read_system_counters() -> Tuple[int, int]:
        counters = psutil.net_io_counters()
        if counters is None:
            return 0, 0
        return counters.bytes_sent, counters.bytes_recv

    def _sample_counters(self) -> Tuple[str, int, int]:
        upload = self._counter_reader(UPLOAD_CHAIN)
        download = self._counter_reader(DOWNLOAD_CHAIN)
        if upload is not None and download is not None:
            return "iptables", upload, download

        upload, download = self._system_reader()
        return "system", upload, download

    def latest(self) -> dict:
        """Return the most recently measured rates without resampling."""
        with self._lock:
            if self._latest_rates is None:
                return dict(self.IDLE_RATES)
            return dict(self._latest_rates)

    def poll(self) -> dict:
        """Advance the baseline and measure the rate since the previous poll.

        Only the sampling job should call this; see the module docstring.
        """
        now = time.monotonic()
        with self._lock:
            source, upload, download = self._sample_counters()
            current = (source, upload, download)
            elapsed = now - self._last_time if self._last_time is not None else 0.0

            # iptables chains are rebuilt on node apply, which resets their
            # counters.  Treat a reset (or a backend switch) as a new baseline.
            if (
                self._last_counters is None
                or self._last_counters[0] != source
                or upload < self._last_counters[1]
                or download < self._last_counters[2]
                or elapsed <= 0
            ):
                upload_rate = download_rate = 0.0
            else:
                upload_rate = (upload - self._last_counters[1]) / elapsed / 1024
                download_rate = (download - self._last_counters[2]) / elapsed / 1024

            self._last_counters = current
            self._last_time = now
            self._latest_rates = {
                "upload": round(max(0.0, upload_rate), 2),
                "download": round(max(0.0, download_rate), 2),
                "source": source,
            }
            return dict(self._latest_rates)
