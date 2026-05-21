import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test.support import ScriptProject


class ScriptProjectTestCase(unittest.TestCase):
    def test_write_and_run_real_script(self):
        with ScriptProject() as project:
            project.write("main.sh", 'echo "hello"\n')

            result = project.run("main.sh")

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, "hello\n")

    def test_run_passes_explicit_environment(self):
        with ScriptProject() as project:
            project.write("main.sh", 'echo "env:$HARNESS_VALUE"\n')

            result = project.run("main.sh", env={"HARNESS_VALUE": "ok"})

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, "env:ok\n")

    def test_compile_restores_process_cwd(self):
        before = os.getcwd()
        with ScriptProject() as project:
            project.write("sub/dep.sh", 'echo "dep"\n')
            project.write("main.sh", 'cd sub\nsource ./dep.sh\n')

            project.compile("main.sh")

        self.assertEqual(os.getcwd(), before)

    def test_sources_are_normalized_and_cwd_is_restored(self):
        before = os.getcwd()
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            project.write("main.sh", 'source ./dep.sh\n')

            project.assert_sources(self, "main.sh", ["dep.sh", "main.sh"])

        self.assertEqual(os.getcwd(), before)


if __name__ == "__main__":
    unittest.main()
