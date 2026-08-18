import unittest

from core.performance_history import PerformanceHistory


class PerformanceHistoryTest(unittest.TestCase):
    def _history(self, cores=None, memory=None, mihomo=None):
        return PerformanceHistory(
            cpu_reader=lambda: cores if cores is not None else [10.0, 30.0],
            memory_reader=lambda: memory or {"percent": 40.0, "total": 2048, "used": 800},
            mihomo_reader=lambda: mihomo or {
                "cpu_percent": 0.0, "memory_percent": 0.0, "memory_mb": 0,
            },
        )

    def test_snapshot_is_idle_until_the_first_sample(self):
        snapshot = self._history().snapshot()

        self.assertEqual(snapshot["cpu"], {})
        self.assertEqual(snapshot["memory"], PerformanceHistory.IDLE_MEMORY)
        self.assertEqual(snapshot["history"]["cpu"], [])
        self.assertEqual(snapshot["history"]["cpu_mihomo"], [])
        self.assertEqual(snapshot["history"]["memory_mihomo"], [])
        self.assertEqual(snapshot["mihomo"], PerformanceHistory.IDLE_MIHOMO)
        self.assertEqual(snapshot["history"]["upload"], [])
        self.assertEqual(snapshot["history"]["window"], PerformanceHistory.WINDOW_SECONDS)

    def test_sample_records_per_core_usage_and_its_average(self):
        history = self._history(cores=[10.0, 30.0, 50.0, 70.0])
        history.sample({"upload": 1.0, "download": 2.0})

        snapshot = history.snapshot()
        self.assertEqual(snapshot["cpu"], {
            "core 1": 10.0, "core 2": 30.0, "core 3": 50.0, "core 4": 70.0,
        })
        self.assertEqual(snapshot["history"]["cpu"], [40.0])
        self.assertEqual(snapshot["history"]["cpu_mihomo"], [0.0])
        self.assertEqual(snapshot["memory"], {"percent": 40.0, "total": 2048, "used": 800})
        self.assertEqual(snapshot["history"]["memory"], [40.0])
        self.assertEqual(snapshot["history"]["memory_mihomo"], [0.0])

    def test_a_machine_without_per_core_readings_reports_no_load(self):
        history = self._history(cores=[])
        history.sample({"upload": 0.0, "download": 0.0})

        snapshot = history.snapshot()
        self.assertEqual(snapshot["cpu"], {})
        self.assertEqual(snapshot["history"]["cpu"], [0.0])

    def test_traffic_series_is_a_moving_average_of_the_samples(self):
        history = self._history()
        for rate in [10.0, 0.0, 0.0, 0.0, 0.0, 0.0]:
            history.sample({"upload": rate, "download": rate * 2})

        upload = history.snapshot()["history"]["upload"]
        # The window grows until it holds SMOOTH_SAMPLES readings, then the spike
        # leaves it again.
        self.assertEqual(upload, [10.0, 5.0, 3.33, 2.5, 2.0, 0.0])
        self.assertEqual(history.snapshot()["history"]["download"][0], 20.0)

    def test_a_missing_rate_counts_as_idle(self):
        history = self._history()
        history.sample({})

        snapshot = history.snapshot()
        self.assertEqual(snapshot["history"]["upload"], [0.0])
        self.assertEqual(snapshot["history"]["download"], [0.0])

    def test_window_keeps_only_the_most_recent_samples(self):
        history = self._history()
        for index in range(PerformanceHistory.WINDOW_SECONDS + 10):
            history.sample({"upload": float(index), "download": 0.0})

        series = history.snapshot()["history"]["upload"]
        self.assertEqual(len(series), PerformanceHistory.WINDOW_SECONDS)
        # The oldest ten samples were dropped, so the newest reading is the last.
        newest = PerformanceHistory.WINDOW_SECONDS + 9
        span = range(newest - PerformanceHistory.SMOOTH_SAMPLES + 1, newest + 1)
        self.assertEqual(series[-1], round(sum(span) / len(span), 2))

    def test_reading_twice_does_not_change_the_window(self):
        history = self._history()
        history.sample({"upload": 1.0, "download": 2.0})

        self.assertEqual(history.snapshot(), history.snapshot())

    def test_snapshot_does_not_expose_the_stored_samples(self):
        history = self._history()
        history.sample({"upload": 1.0, "download": 2.0})

        snapshot = history.snapshot()
        snapshot["cpu"]["core 1"] = 99.0
        snapshot["memory"]["percent"] = 99.0

        self.assertEqual(history.snapshot()["cpu"]["core 1"], 10.0)
        self.assertEqual(history.snapshot()["memory"]["percent"], 40.0)

    def test_mihomo_process_usage_is_recorded_alongside_the_system(self):
        history = self._history(mihomo={
            "cpu_percent": 4.5, "memory_percent": 1.2, "memory_mb": 48,
        })
        history.sample({"upload": 0.0, "download": 0.0})

        snapshot = history.snapshot()
        self.assertEqual(snapshot["mihomo"], {
            "cpu_percent": 4.5, "memory_percent": 1.2, "memory_mb": 48,
        })
        self.assertEqual(snapshot["history"]["cpu_mihomo"], [4.5])
        self.assertEqual(snapshot["history"]["memory_mihomo"], [1.2])


if __name__ == "__main__":
    unittest.main()
