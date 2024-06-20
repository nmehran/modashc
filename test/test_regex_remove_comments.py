import unittest
from methods.shell.utilities import remove_comments


class TestRemoveComments(unittest.TestCase):

    def test_remove_comments(self):
        # Define the test cases as a dictionary of input : expected output pairs
        test_cases = {
            # # Test basic comment removal
            "This is a line # This part should be commented": "This is a line ",
            # # Test inside quotes
            "\"This is a # inside double quotes\" # But this should be commented": "\"This is a # inside double quotes\" ",
            # # Test inside single quotes
            "'It is # inside single quotes' # This should also be commented": "'It is # inside single quotes' ",
            # # Test entire line comment removal
            "// This whole line should be removed": "",
            # # Test exclusion pattern with URLs
            "http://www.example.com // This URL should not be removed": "http://www.example.com ",
            # # Test shebang and complex nested quotes
            "#!/bin/bash\n# Commented\necho \'# && cd fake\' # && cd ..": "#!/bin/bash\n\necho \'# && cd fake\' ",
            # Test commands with escaped comments and right-hand comments
            "#!/bin/bash\n# Commented\n'echo \\'# && cd fake\\' # && cd ..": "#!/bin/bash\n\n'echo \\'# && cd fake\\' ",
        }

        comment_patterns = ['#', '//']
        exclusion_patterns = ['http://', 'https://', r'\#\!.*']
        escape_exclusions = False

        for input_text, expected in test_cases.items():
            with self.subTest(case=input_text):
                result = remove_comments(input_text, comment_patterns, exclusion_patterns, escape_exclusions)
                self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
