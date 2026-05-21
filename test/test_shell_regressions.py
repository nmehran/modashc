import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class ShellRegressionTestCase(unittest.TestCase):
    def test_modashc_shell_executes_script_argument_non_interactively(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "marker"
            target = root / "target.sh"
            target.write_text(f'#!/bin/bash\necho "ran" > "{marker}"\n')
            target.chmod(0o755)

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
