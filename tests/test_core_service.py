import unittest
from unittest.mock import Mock, patch

from core.core_service import CoreService


class UpdateCheckTest(unittest.TestCase):
    def test_commit_subject_may_contain_pipe_characters(self):
        fetch_result = Mock(returncode=0)
        branch_result = Mock(returncode=0, stdout='main\n')
        local_result = Mock(returncode=0, stdout='100\n')
        log_result = Mock(
            returncode=0,
            stdout='200|2026-08-08|fix: preserve a|b syntax\n',
            stderr='',
        )

        with patch(
            'core.core_service.subprocess.run',
            side_effect=[
                fetch_result,
                branch_result,
                local_result,
                log_result,
            ],
        ):
            commits = CoreService.check_v2raypi_updates()

        self.assertEqual(
            commits,
            ['2026-08-08|fix: preserve a|b syntax'],
        )


if __name__ == '__main__':
    unittest.main()
