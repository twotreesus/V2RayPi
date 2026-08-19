import threading
import time
import unittest

from core.api_serial import ApiSerial


class ApiSerialTest(unittest.TestCase):
    def setUp(self):
        self.serial = ApiSerial()

    def test_writes_run_one_at_a_time(self):
        order = []
        started = threading.Event()
        release = threading.Event()

        def first():
            order.append('first-start')
            started.set()
            self.assertTrue(release.wait(1))
            order.append('first-end')

        def second():
            order.append('second')

        first_thread = threading.Thread(target=lambda: self.serial.submit_write(first))
        second_thread = threading.Thread(target=lambda: self.serial.submit_write(second))
        first_thread.start()
        self.assertTrue(started.wait(1))
        second_thread.start()
        time.sleep(0.05)
        self.assertEqual(order, ['first-start'])
        release.set()
        first_thread.join(1)
        second_thread.join(1)
        self.assertEqual(order, ['first-start', 'first-end', 'second'])

    def test_read_waits_for_in_flight_write(self):
        order = []
        started = threading.Event()
        release = threading.Event()

        def write():
            order.append('write-start')
            started.set()
            self.assertTrue(release.wait(1))
            order.append('write-end')

        def read():
            order.append('read')

        writer = threading.Thread(target=lambda: self.serial.submit_write(write))
        writer.start()
        self.assertTrue(started.wait(1))
        reader = threading.Thread(target=lambda: self.serial.submit_read(read))
        reader.start()
        time.sleep(0.05)
        self.assertEqual(order, ['write-start'])
        release.set()
        writer.join(1)
        reader.join(1)
        self.assertEqual(order, ['write-start', 'write-end', 'read'])

    def test_write_waits_for_in_flight_read(self):
        order = []
        started = threading.Event()
        release = threading.Event()

        def read():
            order.append('read-start')
            started.set()
            self.assertTrue(release.wait(1))
            order.append('read-end')

        def write():
            order.append('write')

        reader = threading.Thread(target=lambda: self.serial.submit_read(read))
        reader.start()
        self.assertTrue(started.wait(1))
        writer = threading.Thread(target=lambda: self.serial.submit_write(write))
        writer.start()
        time.sleep(0.05)
        self.assertEqual(order, ['read-start'])
        release.set()
        reader.join(1)
        writer.join(1)
        self.assertEqual(order, ['read-start', 'read-end', 'write'])

    def test_write_increments_generation(self):
        before = self.serial.generation
        self.serial.submit_write(lambda: None)
        self.assertEqual(self.serial.generation, before + 1)

    def test_write_exception_still_increments_generation(self):
        before = self.serial.generation
        with self.assertRaises(RuntimeError):
            def boom():
                raise RuntimeError('write failed')
            self.serial.submit_write(boom)
        self.assertEqual(self.serial.generation, before + 1)
