import os
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from core.web_terminal import (
    WebTerminalManager,
    WebTerminalSession,
    _ensure_utf8_locale,
    _shell_command,
    _shell_env,
)


class WebTerminalManagerTest(unittest.TestCase):
    def test_create_replaces_previous_session(self):
        manager = WebTerminalManager()
        first = Mock()
        first.id = 'first'
        second = Mock()
        second.id = 'second'

        with patch(
            'core.web_terminal.WebTerminalSession',
            side_effect=[first, second],
        ):
            created_first = manager.create()
            created_second = manager.create()

        self.assertIs(created_first, first)
        self.assertIs(created_second, second)
        first.close.assert_called_once_with()
        self.assertIs(manager.get('second'), second)
        self.assertIsNone(manager.get('first'))


class WebTerminalShellCommandTest(unittest.TestCase):
    def test_zsh_uses_zdotdir_rc(self):
        env = _shell_env()
        command = _shell_command('/bin/zsh', env)
        self.assertEqual(command, ['/bin/zsh', '-i'])
        self.assertTrue(env['ZDOTDIR'].endswith('script/web_terminal'))
        self.assertTrue(
            os.path.isfile(os.path.join(env['ZDOTDIR'], '.zshrc')),
        )

    def test_bash_uses_rcfile(self):
        env = _shell_env()
        command = _shell_command('/bin/bash', env)
        self.assertEqual(command[0], '/bin/bash')
        self.assertEqual(command[1], '--rcfile')
        self.assertTrue(command[2].endswith('script/web_terminal/bashrc'))
        self.assertEqual(command[3], '-i')
        self.assertTrue(os.path.isfile(command[2]))


class WebTerminalLocaleTest(unittest.TestCase):
    def test_missing_locale_defaults_to_c_utf8(self):
        env = {}
        _ensure_utf8_locale(env)
        self.assertEqual(env['LANG'], 'C.UTF-8')
        self.assertEqual(env['LC_CTYPE'], 'C.UTF-8')

    def test_posix_locale_is_upgraded_to_utf8(self):
        env = {'LANG': 'C', 'LC_ALL': 'C'}
        _ensure_utf8_locale(env)
        self.assertEqual(env['LC_ALL'], 'C.UTF-8')

    def test_existing_utf8_locale_is_kept(self):
        env = {'LANG': 'en_US.UTF-8'}
        _ensure_utf8_locale(env)
        self.assertEqual(env['LANG'], 'en_US.UTF-8')
        self.assertNotIn('LC_ALL', env)
        self.assertNotIn('LC_CTYPE', env)


class WebTerminalSessionIoTest(unittest.TestCase):
    def test_write_encodes_text_to_pty(self):
        session = WebTerminalSession.__new__(WebTerminalSession)
        session.alive = True
        session.master_fd = 7
        session._write_lock = threading.Lock()

        with patch('core.web_terminal.os.write') as write:
            session.write('hi')
            write.assert_called_once_with(7, b'hi')

    def test_write_sends_x10_mouse_bytes_as_latin1(self):
        session = WebTerminalSession.__new__(WebTerminalSession)
        session.alive = True
        session.master_fd = 7
        session._write_lock = threading.Lock()

        with patch('core.web_terminal.os.write') as write:
            session.write('\x1b[M \xff!', binary=True)
            write.assert_called_once_with(7, b'\x1b[M \xff!')

    def test_output_queue_accepts_decoded_chunks(self):
        session = WebTerminalSession.__new__(WebTerminalSession)
        session.output = queue.Queue()
        session.output.put('prompt$ ')
        self.assertEqual(session.output.get_nowait(), 'prompt$ ')


if __name__ == '__main__':
    unittest.main()
