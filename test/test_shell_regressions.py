import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test.support import ScriptProject


class ShellRegressionTestCase(unittest.TestCase):
    def test_modashc_shell_executes_script_argument_non_interactively(self):
        with ScriptProject() as project:
            marker = project.path("marker")
            target = project.write("target.sh", f'#!/bin/bash\necho "ran" > "{marker}"\n', executable=True)

            result = subprocess.run(
                ["bash", str(REPO_ROOT / "setup" / "modashc_shell.sh"), str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=2,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertTrue(marker.exists(), result.stdout)
            self.assertEqual(marker.read_text(), "ran\n")

    def test_modashc_shell_rejects_disallowed_script_command(self):
        with ScriptProject() as project:
            marker = project.path("marker")
            target = project.write(
                "target.sh",
                f'#!/bin/bash\nuname > "{marker}"\necho "after"\n',
                executable=True,
            )

            result = subprocess.run(
                ["bash", str(REPO_ROOT / "setup" / "modashc_shell.sh"), str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=2,
            )

            self.assertEqual(result.returncode, 126, result.stdout)
            self.assertIn("Command not allowed: uname", result.stdout)
            self.assertFalse(marker.exists(), result.stdout)

    def test_modashc_shell_rejects_disallowed_command_substitution(self):
        with ScriptProject() as project:
            marker = project.path("marker")
            target = project.write(
                "target.sh",
                f'#!/bin/bash\necho "$(uname)"\necho "after" > "{marker}"\n',
                executable=True,
            )

            result = subprocess.run(
                ["bash", str(REPO_ROOT / "setup" / "modashc_shell.sh"), str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=2,
            )

            self.assertEqual(result.returncode, 126, result.stdout)
            self.assertIn("Command not allowed: uname", result.stdout)
            self.assertFalse(marker.exists(), result.stdout)

    def test_modashc_shell_allows_quoted_environment_assignment_prefixes(self):
        with ScriptProject() as project:
            target = project.write(
                "target.sh",
                '#!/bin/bash\nVALUE="a b" printenv VALUE\nitems=(one two)\nitems[0]=zero\necho "${items[0]} ${items[1]}"\n',
                executable=True,
            )

            result = subprocess.run(
                ["bash", str(REPO_ROOT / "setup" / "modashc_shell.sh"), str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=2,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(result.stdout, "a b\nzero two\n")

    def test_modashc_shell_allows_control_flow_keywords(self):
        with ScriptProject() as project:
            target = project.write(
                "target.sh",
                '#!/bin/bash\nfor value in one two; do echo "$value"; done\ncase two in two) echo "case";; esac\n',
                executable=True,
            )

            result = subprocess.run(
                ["bash", str(REPO_ROOT / "setup" / "modashc_shell.sh"), str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=2,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(result.stdout, "one\ntwo\ncase\n")

    def test_runner_invokes_modashc_shell_instead_of_bash(self):
        runner = (REPO_ROOT / "setup" / "run_modashc_shell.sh").read_text()

        self.assertIn('sudo -u modashc "$MODASHC_SHELL_PATH" "$SCRIPT_PATH"', runner)
        self.assertNotIn('sudo -u modashc /bin/bash "$SCRIPT_PATH"', runner)


if __name__ == "__main__":
    unittest.main()
