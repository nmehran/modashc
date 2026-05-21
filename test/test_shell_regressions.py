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


if __name__ == "__main__":
    unittest.main()
