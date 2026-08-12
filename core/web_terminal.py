# encoding: utf-8
"""Interactive PTY sessions for the web terminal."""
import codecs
import fcntl
import os
import pty
import queue
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import uuid


def _shell_env():
    env = os.environ.copy()
    # Drop debugger attach state so the login shell is a normal process, not a
    # pydevd-traced Python being replaced (that path times out under Cursor).
    for key in list(env):
        if key.startswith(('PYDEVD_', 'DEBUGPY_', 'PYCHARM_')):
            env.pop(key, None)
    env.pop('PYTHONBREAKPOINT', None)
    env.pop('PYTHONSTARTUP', None)
    env['TERM'] = 'xterm-256color'
    env.setdefault('COLORTERM', 'truecolor')
    return env


def _web_terminal_rc_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'script', 'web_terminal',
    )


def _shell_command(shell: str, env: dict):
    # Interactive (not login) + dedicated rc files: keep user PATH/aliases, but
    # replace Powerline/Nerd Font prompts that xterm cannot render.
    name = os.path.basename(shell)
    rc_dir = _web_terminal_rc_dir()
    if name == 'zsh':
        env['ZDOTDIR'] = rc_dir
        return [shell, '-i']
    if name == 'bash':
        return [shell, '--rcfile', os.path.join(rc_dir, 'bashrc'), '-i']
    return [shell, '-i']


def _detach_debugger_before_shell():
    try:
        sys.settrace(None)
    except Exception:
        pass
    try:
        sys.setprofile(None)
    except Exception:
        pass


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    rows = max(1, min(int(rows), 500))
    cols = max(2, min(int(cols), 500))
    winsize = struct.pack('HHHH', rows, cols, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        pass


class WebTerminalSession:
    def __init__(self, rows: int = 24, cols: int = 80):
        self.id = uuid.uuid4().hex
        self.alive = True
        self.output = queue.Queue()
        self._write_lock = threading.Lock()
        self._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.master_fd = -1
        self.proc = None

        env = _shell_env()
        shell = env.get('SHELL') or '/bin/bash'
        if not os.path.isfile(shell):
            shell = '/bin/sh'
        cwd = env.get('HOME') or '/'
        if not os.path.isdir(cwd):
            cwd = '/'

        command = _shell_command(shell, env)
        master_fd, slave_fd = pty.openpty()
        _set_winsize(slave_fd, rows, cols)
        try:
            # openpty + Popen avoids pty.fork()'s "replace the traced Python
            # process" path that pydevd blocks on for several seconds.
            self.proc = subprocess.Popen(
                command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                env=env,
                start_new_session=True,
                close_fds=True,
                preexec_fn=_detach_debugger_before_shell,
            )
        finally:
            os.close(slave_fd)

        self.master_fd = master_fd
        self.pid = self.proc.pid
        self.resize(rows, cols)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._reaper = threading.Thread(target=self._wait_child, daemon=True)
        self._reaper.start()

    def _read_loop(self):
        while self.alive and self.master_fd >= 0:
            try:
                readable, _, _ = select.select([self.master_fd], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not readable:
                continue
            try:
                data = os.read(self.master_fd, 8192)
            except OSError:
                break
            if not data:
                break
            text = self._decoder.decode(data)
            if text:
                self.output.put(text)

        try:
            tail = self._decoder.decode(b'', final=True)
        except Exception:
            tail = ''
        if tail:
            self.output.put(tail)
        self.alive = False
        self.output.put(None)

    def _wait_child(self):
        if self.proc is not None:
            try:
                self.proc.wait()
            except Exception:
                pass
        self.alive = False

    def write(self, data: str) -> None:
        if not data or not self.alive or self.master_fd < 0:
            return
        payload = data.encode('utf-8', errors='replace')
        with self._write_lock:
            try:
                os.write(self.master_fd, payload)
            except OSError:
                self.alive = False

    def resize(self, rows: int, cols: int) -> None:
        if self.master_fd < 0:
            return
        _set_winsize(self.master_fd, rows, cols)

    def close(self) -> None:
        was_alive = self.alive
        self.alive = False
        if was_alive and self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGHUP)
            except OSError:
                try:
                    self.proc.terminate()
                except OSError:
                    pass
            try:
                self.proc.wait(timeout=1)
            except Exception:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    pass
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = -1
        self.output.put(None)


class WebTerminalManager:
    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()

    def create(self, rows: int = 24, cols: int = 80) -> WebTerminalSession:
        # Side-router admin panel: keep a single interactive shell.
        with self._lock:
            stale = list(self._sessions.values())
            self._sessions.clear()
        for session in stale:
            session.close()

        session = WebTerminalSession(rows=rows, cols=cols)
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str):
        with self._lock:
            return self._sessions.get(session_id)

    def close(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if not session:
            return False
        session.close()
        return True
