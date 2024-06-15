import os
import unittest

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
        entry_point = os.path.abspath("./sample_dir/script_main.sh")
        actual_sources = [os.path.relpath(path) for path in get_sources(entry_point)]

        self.assertEqual(expected_sources, actual_sources)


if __name__ == '__main__':
    unittest.main()
