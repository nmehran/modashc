import unittest
import re
from methods.patterns import PATH_PATTERN


class TestPathPattern(unittest.TestCase):
    def setUp(self):
        self.path_regex = PATH_PATTERN
        self.test_cases = [
            (r"'/home/user/file.txt'", True),
            (r"\"C:\\Users\\New Folder\\file.txt\"", False),
            (r"'single_quote_path/'", True),
            (r"\"double_quote_path\\file\"", False),
            (r"'mixed/slashes\\path'", True),
            (r"'unmatched_double\"'", False),
            (r"unquoted/path", False),
            (r"'illegal*chars'", False),
            (r"\"\"", False),
            (r"/trailing/slash/", False),
            (r"'unbalanced\"'", False),
            (r"''", False)  # Empty string inside quotes
        ]

    def test_path_patterns(self):
        for path, expected in self.test_cases:
            with self.subTest(path=path):
                result = bool(self.path_regex.match(path))
                self.assertEqual(result, expected, f"Failed: {path} (Expected: {expected}, Got: {result})")


if __name__ == '__main__':
    unittest.main()
