import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from methods.sources import get_sources


class TestGetSources(unittest.TestCase):
    def test_sources(self):

        # Using relative paths for comparison
        expected_sources = [
            "dir1/script6.sh",
            "script5.sh",
            "script4.sh",
            "dir with spaces/script3.sh",
            "dir2/script2.sh",
            "dir1/script1.sh",
            "script_main.sh"
        ]

        # Example usage
        entry_point = os.path.abspath(TEST_DIR / "sample_dir" / "script_main.sh")
        entry_directory = os.path.dirname(entry_point)
        actual_sources = [os.path.relpath(path, entry_directory) for path in get_sources(entry_point)[0]]

        self.assertEqual(expected_sources, actual_sources)


if __name__ == '__main__':
    unittest.main()
