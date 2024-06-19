import unittest
from methods.patterns import CD_PATTERN
from methods.shell.utilities import extract_bash_commands


class TestCDCommandRegex(unittest.TestCase):
    def setUp(self):
        # Updated regex with proper escapes
        self.regex = CD_PATTERN
        self.command = 'cd'

    def test_cd_command_extraction(self):
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
            "   cd '..'": "cd '..'",
            "   cd ..": "cd ..",
            "cd ../../../": "cd ../../../",
            "cd ${HOME}/dir": "cd ${HOME}/dir",
            "cd ~/Documents": "cd ~/Documents",
            "echo 'random text cd /home'": None,
            "# cd /home": None,
            "\"cd /not/a/command\"": None,
            "echo \"cd /not/a/command\"": None,
            "cd /home || echo 'failed'": "cd /home",
            "cd /etc && ls": "cd /etc",
            'echo "done" && cd /tmp && echo "changed"': 'cd /tmp',
            'echo "starting" && cd "/complex/path" && echo "done"': 'cd "/complex/path"',
            'echo "not a command cd /fake" && cd /real && echo "done"': 'cd /real',
            'cd "$(echo /quoted/path)"': 'cd "$(echo /quoted/path)"',
            'cd `echo /backtick/path`': 'cd `echo /backtick/path`',
            'cd /multiple; cd /paths': 'cd /multiple',
            'cd $(echo $(dirname $(dirname /path)))': 'cd $(echo $(dirname $(dirname /path)))',
            'echo $(cd /nested/path && ls)': 'cd /nested/path',  # command substitution with command separator
            'echo "$(cd /nested/path)"': 'cd /nested/path',  # command substitution within double-quote
            'echo \'$(cd /nested/path && ls)\'': None,  # False command substitution within single-quote
            'cd "$(dirname "$BASH_SOURCE")" || exit 1': 'cd "$(dirname "$BASH_SOURCE")"'
        }

        for case, expected in test_cases.items():
            with self.subTest(case=case):
                matches = extract_bash_commands(self.command, case)
                result = None
                if matches:
                    result = f"{matches[0][0]} {matches[0][1]}"  # First match command and argument
                self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
