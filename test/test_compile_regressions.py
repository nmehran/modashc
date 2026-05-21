import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from methods.compile import compile_sources


class CompileRegressionTestCase(unittest.TestCase):
    def compile_entry(self, entry_point, output_file):
        original_cwd = os.getcwd()
        try:
            compile_sources(str(entry_point), str(output_file))
        finally:
            os.chdir(original_cwd)

    def run_bash(self, script_path, cwd):
        return subprocess.run(
            ["bash", str(script_path)],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def compile_and_run(self, entry_point, cwd):
        output_file = Path(entry_point).with_name("compiled.sh")
        self.compile_entry(entry_point, output_file)
        return self.run_bash(output_file, cwd)

    def assert_compiled_matches_bash(self, entry_point, cwd):
        expected = self.run_bash(entry_point, cwd)
        actual = self.compile_and_run(entry_point, cwd)

        self.assertEqual(actual.returncode, expected.returncode, actual.stdout)
        self.assertEqual(actual.stdout, expected.stdout)

    def test_relative_entry_point_compiles_to_runnable_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_file = Path(tmp) / "merged_script.sh"
            original_cwd = os.getcwd()
            try:
                os.chdir(REPO_ROOT)
                self.compile_entry("test/sample_dir/script_main.sh", output_file)
            finally:
                os.chdir(original_cwd)

            result = self.run_bash(output_file, REPO_ROOT)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("This is the main script", result.stdout)

    def test_parent_variables_are_available_before_sourced_file_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dep.sh").write_text('echo "dep:${FOO:-missing}"\n')
            entry = root / "main.sh"
            entry.write_text("FOO=bar\nsource ./dep.sh\n")

            self.assert_compiled_matches_bash(entry, root)

    def test_nounset_state_before_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dep.sh").write_text('echo "dep:${UNSET_VAR}"\n')
            entry = root / "main.sh"
            entry.write_text("set +u\nsource ./dep.sh\n")

            self.assert_compiled_matches_bash(entry, root)

    def test_non_sh_sourced_file_is_compiled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").write_text('echo "from config"\n')
            entry = root / "main.sh"
            entry.write_text('source ./config\necho "from main"\n')

            self.assert_compiled_matches_bash(entry, root)

    def test_source_inside_multiline_function_matches_bash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime.sh").write_text('echo "runtime"\n')
            entry = root / "main.sh"
            entry.write_text(textwrap.dedent("""\
                helper() {
                  echo "before"
                  source ./runtime.sh
                  echo "after"
                }

                helper
                """))

            self.assert_compiled_matches_bash(entry, root)


if __name__ == "__main__":
    unittest.main()
