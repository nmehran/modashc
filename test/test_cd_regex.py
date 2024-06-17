import unittest
import re
from methods.patterns import CD_PATTERN


class TestCDCommandRegex(unittest.TestCase):
    def setUp(self):
        # Updated regex with proper escapes
        self.regex = CD_PATTERN

    def test_cd_commands(self):
        test_cases = {
            "cd /usr/bin": "cd /usr/bin",
            "cd \"../some_dir\" || exit 1": "cd \"../some_dir\"",
            "cd some_dir": "cd some_dir",
            "cd \"$(dirname something)\"": "cd \"$(dirname something)\"",
            "cd $(echo ../dir)": "cd $(echo ../dir)",
            "cd '/some directory/with spaces'": "cd '/some directory/with spaces'",
            "cd /directory/with\\ spaces": "cd /directory/with\\ spaces",
            "cd ~": "cd ~",
            "cd .": "cd .",
            "   cd ..": "cd ..",
            "cd ../../../": "cd ../../../",
            "cd ${HOME}/dir": "cd ${HOME}/dir",
            "cd ~/Documents": "cd ~/Documents",
            "echo 'random text cd /home'": None,
            "# cd /home": None,
            "\"cd /not/a/command\"": None,
            "echo \"cd /not/a/command\"": None,
            "cd /home || echo 'failed'": "cd /home",
            "cd /etc && ls": "cd /etc"
        }

        for case, expected in test_cases.items():
            with self.subTest(case=case):
                match = self.regex.match(case)
                if match:
                    result = f"{match.group(1)} {match.group(2)}"
                else:
                    result = None
                self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
