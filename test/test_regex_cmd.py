import unittest
from methods.regex.patterns import CD_PATTERN, SOURCE_PATTERN
from methods.regex.utilities import extract_bash_commands


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
            'cd "../dir with spaces" || exit 1': 'cd "../dir with spaces"',
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
            '" cd "': None,
            "# cd /home": None,
            "\"cd /not/a/command\"": None,
            "echo \"cd /not/a/command\"": None,
            # "echo cd /no/command/separator": None,
            'echo "something" && cd "./dir1/script6.sh"': 'cd "./dir1/script6.sh"',
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
            'echo \'# && cd fake\' && cd "$(dirname "$BASH_SOURCE")" || exit 1': 'cd "$(dirname "$BASH_SOURCE")"',
            'echo \'# && cd fake\' # && cd "$(dirname "$BASH_SOURCE")" || exit 1': None  # Commented command
        }

        for case, expected in test_cases.items():
            with self.subTest(case=case):
                matches = extract_bash_commands(self.command, case)
                result = None
                if matches:
                    result = f"{matches[0][0]} {matches[0][1]}"  # First match command and argument
                self.assertEqual(result, expected)


class TestSourceRegex(unittest.TestCase):
    def setUp(self):
        self.pattern = SOURCE_PATTERN

    def test_source_command(self):
        test_cases = {
            'source': ['source'],
            'source   ': ['source'],
            'source file.sh': ['source file.sh'],
            'source /path/to/file.sh': ['source /path/to/file.sh'],
            'source "quoted file.sh"': ['source "quoted file.sh"'],
            'source file.sh # comment': ['source file.sh'],
            'echo "Hello" && source file.sh': ['&& source file.sh'],
            'ls -l || source file.sh ; echo "Done"': ['|| source file.sh'],
            'source file1.sh && source file2.sh': ['source file1.sh', '&& source file2.sh'],
            'source file.sh arg1 arg2': ['source file.sh arg1 arg2'],
            'source "file with spaces.sh"': ['source "file with spaces.sh"'],
            'source $HOME/.bashrc': ['source $HOME/.bashrc'],
            'source ~/my_script.sh': ['source ~/my_script.sh'],
            'source file.sh > /dev/null 2>&1': ['source file.sh > /dev/null 2>&1'],
            '  source   file.sh   ': ['source   file.sh'],
            'source # comment': ['source'],
            'source && echo "test"': ['source'],
            'notsource file.sh': [],
            'echo source': [],
            '"source" file.sh': [],
            'echo "test && source file.sh"': [],
            '# && source file.sh': [],
            'echo "source file.sh"': [],
            'source "file.sh" # comment with "quotes"': ['source "file.sh"'],
            'source `which my_script.sh`': ['source `which my_script.sh`'],
            'source <(echo "echo Hello")': ['source <(echo "echo Hello")'],
            'echo "This is the main script" && source "./dir1/script6.sh"': ['&& source "./dir1/script6.sh"'],
            'source file.sh && source "quoted.sh" || source unquoted.sh': [
                'source file.sh', '&& source "quoted.sh"', '|| source unquoted.sh'
            ],
            'source "unusual/file&&name#" && source $(ls bin/bash | xargs | awk\'\' \'{print $1}\')': [
                'source "unusual/file&&name#"', '&& source $(ls bin/bash | xargs | awk\'\' \'{print $1}\')'
            ]
        }

        for input_string, expected_matches in test_cases.items():
            with self.subTest(input=input_string):
                matches = [''.join(m).strip() for m in self.pattern.findall(input_string)]
                self.assertEqual(matches, expected_matches)


if __name__ == '__main__':
    unittest.main()
