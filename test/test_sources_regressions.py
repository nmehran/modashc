import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from methods.sources import get_commands, get_sources


class SourceRegressionTestCase(unittest.TestCase):
    def test_get_commands_keeps_hash_inside_words_and_paths(self):
        self.assertEqual(
            list(get_commands('echo foo#bar; source dep.sh')),
            ['echo foo#bar', 'source dep.sh'],
        )
        self.assertEqual(
            list(get_commands('source ./dir#1/dep.sh; echo done')),
            ['source ./dir#1/dep.sh', 'echo done'],
        )
        self.assertEqual(
            list(get_commands('echo foo # comment; source dep.sh')),
            ['echo foo'],
        )

    def test_get_commands_ignores_quoted_separators_and_comments(self):
        self.assertEqual(
            list(get_commands('echo "a;b"; source file.sh')),
            ['echo "a;b"', 'source file.sh'],
        )
        self.assertEqual(
            list(get_commands('echo "not # comment"; source file.sh # trailing')),
            ['echo "not # comment"', 'source file.sh'],
        )

    def test_get_sources_does_not_mutate_process_cwd(self):
        before = os.getcwd()
        try:
            get_sources(str(REPO_ROOT / "test" / "sample_dir" / "script_main.sh"))
            after = os.getcwd()
        finally:
            os.chdir(before)

        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
