import os
import subprocess
import tempfile
import unittest


SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'script',
    'restart_v2raypi.sh',
)

SAMPLE_CONF = """\
[unix_http_server]
file=/tmp/supervisor.sock   ; the path to the socket file

[supervisord]
logfile=/tmp/supervisord.log ; main log file
pidfile=/tmp/supervisord.pid ; supervisord pidfile

[supervisorctl]
serverurl=unix:///tmp/supervisor.sock ; use a unix:// URL
"""


class RestartV2RayPiScriptTest(unittest.TestCase):
    def test_moves_control_socket_out_of_tmp(self):
        with tempfile.NamedTemporaryFile('w+', delete=False) as handle:
            handle.write(SAMPLE_CONF)
            path = handle.name
        try:
            subprocess.check_call(['bash', SCRIPT, '--ensure-only', path])
            with open(path) as rewritten_file:
                rewritten = rewritten_file.read()
        finally:
            os.unlink(path)
            bak = path + '.bak'
            if os.path.exists(bak):
                os.unlink(bak)

        self.assertIn('file=/run/supervisor.sock', rewritten)
        self.assertIn('serverurl=unix:///run/supervisor.sock', rewritten)
        self.assertIn('pidfile=/run/supervisord.pid', rewritten)
        self.assertIn('logfile=/var/log/supervisor/supervisord.log', rewritten)
        self.assertNotIn('file=/tmp/supervisor.sock', rewritten)
        self.assertNotIn('unix:///tmp/supervisor.sock', rewritten)


if __name__ == '__main__':
    unittest.main()
