import subprocess
import unittest
from unittest.mock import patch

from core.traffic_monitor import (
    DOWNLOAD_CHAIN,
    UPLOAD_CHAIN,
    TrafficMonitor,
)


class TrafficMonitorTest(unittest.TestCase):
    def test_iptables_parser_reads_exact_byte_counter(self):
        output = """Chain V2RAYPI_TRAFFIC_UP (1 references)\n pkts bytes target     prot opt in out source destination\n   12 123456789 RETURN     all  --  *  *  0.0.0.0/0 0.0.0.0/0\n"""
        completed = subprocess.CompletedProcess([], 0, stdout=output)
        with patch("core.traffic_monitor.subprocess.run", return_value=completed) as run:
            self.assertEqual(TrafficMonitor._read_iptables_counter(UPLOAD_CHAIN), 123456789)
        self.assertEqual(run.call_args.args[0], [
            "iptables", "-t", "mangle", "-L", UPLOAD_CHAIN, "-v", "-x", "-n",
        ])

    def test_iptables_counter_failure_returns_none(self):
        with patch(
            "core.traffic_monitor.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            self.assertIsNone(TrafficMonitor._read_iptables_counter(DOWNLOAD_CHAIN))

    def test_sample_uses_client_facing_counters_and_handles_reset(self):
        values = {
            UPLOAD_CHAIN: [1024, 3072, 100],
            DOWNLOAD_CHAIN: [2048, 6144, 200],
        }
        clock = iter([100.0, 102.0, 104.0])

        def read_counter(chain):
            return values[chain].pop(0)

        monitor = TrafficMonitor(
            counter_reader=read_counter,
            system_reader=lambda: (999999, 999999),
            cache_seconds=0,
        )
        with patch("core.traffic_monitor.time.monotonic", side_effect=clock):
            self.assertEqual(monitor.sample(), {
                "upload": 0.0, "download": 0.0, "source": "iptables",
            })
            self.assertEqual(monitor.sample(), {
                "upload": 1.0, "download": 2.0, "source": "iptables",
            })
            # The counters were reset when the firewall rules were reapplied.
            self.assertEqual(monitor.sample(), {
                "upload": 0.0, "download": 0.0, "source": "iptables",
            })

    def test_falls_back_to_system_counters_when_rules_are_unavailable(self):
        system_values = iter([(100, 200), (1124, 2248)])

        monitor = TrafficMonitor(
            counter_reader=lambda chain: None,
            system_reader=lambda: next(system_values),
            cache_seconds=0,
        )
        with patch("core.traffic_monitor.time.monotonic", side_effect=[10.0, 11.0]):
            self.assertEqual(monitor.sample()["source"], "system")
            self.assertEqual(monitor.sample(), {
                "upload": round(1024 / 1024, 2),
                "download": round(2048 / 1024, 2),
                "source": "system",
            })


if __name__ == "__main__":
    unittest.main()
