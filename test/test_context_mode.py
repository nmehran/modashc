import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test.support import ScriptProject


class ContextModeTestCase(unittest.TestCase):
    def test_cli_default_mode_is_context(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep body"\n')
            entry = project.write("main.sh", 'source ./dep.sh\necho "main body"\n')
            output = project.path("context-output.sh")

            result = subprocess.run(
                [sys.executable, str(REPO_ROOT / "modashc.py"), str(entry), str(output)],
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout)
            content = output.read_text()
            self.assertIn("# modashc context", content)
            self.assertIn("# mode: context", content)
            self.assertIn("# modashc: source ./dep.sh -> dep.sh", content)

    def test_context_output_uses_unique_dependency_first_sections(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep body"\n')
            project.write("main.sh", textwrap.dedent("""\
                source ./dep.sh
                source ./dep.sh
                echo "main body"
                """))

            output = project.compile("main.sh")
            content = output.read_text()

        self.assertLess(content.index('echo "dep body"'), content.index('echo "main body"'))
        self.assertEqual(content.count('echo "dep body"'), 1)
        self.assertEqual(content.count("# modashc: source ./dep.sh -> dep.sh"), 2)

    def test_context_output_includes_non_sh_sourced_files(self):
        with ScriptProject() as project:
            project.write("config", 'export FEATURE_FLAG=yes\n')
            project.write("main.sh", 'source ./config\necho "$FEATURE_FLAG"\n')

            output = project.compile("main.sh")
            content = output.read_text()

        self.assertIn("config", content)
        self.assertIn("export FEATURE_FLAG=yes", content)
        self.assertIn("# modashc: source ./config -> config", content)

    def test_context_output_preserves_original_source_lines(self):
        with ScriptProject() as project:
            project.write("dir with spaces/dep.sh", 'echo "dep body"\n')
            project.write("main.sh", 'source "./dir with spaces/dep.sh"\necho "main body"\n')

            output = project.compile("main.sh")
            content = output.read_text()

        self.assertIn('# modashc: source "./dir with spaces/dep.sh" -> dir with spaces/dep.sh', content)
        self.assertIn('source "./dir with spaces/dep.sh"', content)

    def test_context_output_resolves_safe_cat_source(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep body"\n')
            project.write("dep-path.txt", "./dep.sh\n")
            project.write("main.sh", 'source "$(cat dep-path.txt)"\necho "main body"\n')

            output = project.compile("main.sh")
            content = output.read_text()

        self.assertIn('echo "dep body"', content)
        self.assertIn('# modashc: source "$(cat dep-path.txt)" -> dep.sh', content)
        self.assertIn('source "$(cat dep-path.txt)"', content)

    def test_context_output_resolves_safe_find_source(self):
        with ScriptProject() as project:
            project.write("plugins/init.sh", 'echo "dep body"\n')
            project.write("main.sh", 'source "$(find ./plugins -type f -name init.sh -print -quit)"\necho "main body"\n')

            output = project.compile("main.sh")
            content = output.read_text()

        self.assertIn('echo "dep body"', content)
        self.assertIn('# modashc: source "$(find ./plugins -type f -name init.sh -print -quit)" -> plugins/init.sh', content)
        self.assertIn('source "$(find ./plugins -type f -name init.sh -print -quit)"', content)

    def test_context_output_resolves_safe_eval_source(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep body"\n')
            project.write("main.sh", 'eval "source ./dep.sh"\necho "main body"\n')

            output = project.compile("main.sh")
            content = output.read_text()

        self.assertIn('echo "dep body"', content)
        self.assertIn('# modashc: source ./dep.sh -> dep.sh', content)
        self.assertIn('eval "source ./dep.sh"', content)

    def test_context_output_classifies_bash_c_source_as_child_shell(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep body"\n')
            project.write("main.sh", 'bash -c "source ./dep.sh"\necho "main body"\n')

            output = project.compile("main.sh")
            content = output.read_text()

        self.assertIn('echo "dep body"', content)
        self.assertIn('# modashc: bash -c "source ./dep.sh" -> dep.sh (child-shell)', content)
        self.assertIn('bash -c "source ./dep.sh"', content)

    def test_context_mode_is_not_runtime_parity_mode(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep body"\n')
            project.write("main.sh", textwrap.dedent("""\
                echo "before source"
                source ./dep.sh
                echo "after source"
                """))

            output = project.compile("main.sh")
            content = output.read_text()

        self.assertLess(content.index('echo "dep body"'), content.index('echo "before source"'))

    def test_executable_mode_has_no_context_annotations(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep body"\n')
            project.write("main.sh", 'source ./dep.sh\necho "main body"\n')

            output = project.compile("main.sh", mode="executable")
            content = output.read_text()

        self.assertNotIn("# modashc: source", content)
        self.assertNotIn("# [", content)


if __name__ == "__main__":
    unittest.main()
