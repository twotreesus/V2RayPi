# encoding: utf-8
import queue
import threading
from concurrent.futures import Future


class ApiSerial:
    """Serialize CoreService state at the API boundary.

    Writes run on one worker thread. Reads run on another. The two never
    overlap, so node / config / mihomo mutations cannot interleave with
    each other or with a state snapshot. Independent worker threads without
    this gate would still race on the same objects.
    """

    def __init__(self):
        self._writes = queue.Queue()
        self._reads = queue.Queue()
        self._gate = threading.Condition()
        self._pending_writes = 0
        self._writing = False
        self._reading = False
        self._generation = 0
        threading.Thread(
            target=self._write_loop, name='api-write', daemon=True,
        ).start()
        threading.Thread(
            target=self._read_loop, name='api-read', daemon=True,
        ).start()

    @property
    def generation(self):
        with self._gate:
            return self._generation

    def submit_write(self, fn):
        future = Future()
        with self._gate:
            self._pending_writes += 1
            pending = self._pending_writes
            self._gate.notify_all()
        if pending > 1:
            print('API write queued, {0} write(s) in flight'.format(pending))
        self._writes.put((fn, future))
        return future.result()

    def submit_read(self, fn):
        future = Future()
        self._reads.put((fn, future))
        return future.result()

    def _write_loop(self):
        while True:
            fn, future = self._writes.get()
            with self._gate:
                while self._reading:
                    self._gate.wait()
                self._writing = True
            try:
                future.set_result(fn())
            except Exception as error:
                future.set_exception(error)
            finally:
                with self._gate:
                    self._writing = False
                    self._pending_writes -= 1
                    self._generation += 1
                    self._gate.notify_all()

    def _read_loop(self):
        while True:
            fn, future = self._reads.get()
            with self._gate:
                while self._writing or self._pending_writes:
                    self._gate.wait()
                self._reading = True
            try:
                future.set_result(fn())
            except Exception as error:
                future.set_exception(error)
            finally:
                with self._gate:
                    self._reading = False
                    self._gate.notify_all()


api_serial = ApiSerial()
