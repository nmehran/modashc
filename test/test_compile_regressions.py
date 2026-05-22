import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test.support import ScriptProject


class CompileRegressionTestCase(unittest.TestCase):
    def test_relative_entry_point_compiles_to_runnable_script(self):
        with ScriptProject() as project:
            output_file = project.path("merged_script.sh")

            project.compile("test/sample_dir/script_main.sh", output=output_file, cwd=REPO_ROOT, mode="executable")
            result = project.run(output_file, cwd=REPO_ROOT)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("This is the main script", result.stdout)

    def test_static_dependency_forms_match_bash(self):
        cases = {
            "relative source": ("main.sh", 'source ./dep.sh\necho "main"\n', {"dep.sh": 'echo "dep"\n'}, None),
            "dot source": ("main.sh", '. ./dep.sh\necho "main"\n', {"dep.sh": 'echo "dep"\n'}, None),
            "parent relative source": (
                "app/main.sh",
                'source ../shared/dep.sh\necho "main"\n',
                {"shared/dep.sh": 'echo "dep"\n'},
                "app",
            ),
            "spaces in path": (
                "main.sh",
                'source "./dir with spaces/dep.sh"\necho "main"\n',
                {"dir with spaces/dep.sh": 'echo "dep"\n'},
                None,
            ),
            "hash in path": (
                "main.sh",
                'source "./dir#tag/dep.sh"\necho "main"\n',
                {"dir#tag/dep.sh": 'echo "dep"\n'},
                None,
            ),
            "non sh source": ("main.sh", 'source ./config\necho "main"\n', {"config": 'echo "config"\n'}, None),
        }

        for name, (entry_path, entry_content, files, cwd) in cases.items():
            with self.subTest(name=name), ScriptProject() as project:
                for path, content in files.items():
                    project.write(path, content)
                project.write(entry_path, entry_content)

                project.assert_compiled_matches(self, entry_path, cwd=cwd)

    def test_absolute_dependency_forms_match_bash(self):
        with ScriptProject() as project:
            absolute_dep = project.write("dep.sh", 'echo "absolute"\n')
            project.write("main.sh", f'source "{absolute_dep}"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            absolute_dep = project.write("dep.sh", 'echo "absolute var"\n')
            project.write("main.sh", f'DEP_PATH="{absolute_dep}"\nsource "$DEP_PATH"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            absolute_dep = project.write("abs dir#tag/dep.sh", 'echo "absolute special"\n')
            project.write("main.sh", f'source "{absolute_dep}"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_context_sensitive_dependency_forms_match_bash(self):
        with ScriptProject() as project:
            project.write("subdir/dep.sh", 'echo "dep"\n')
            project.write("main.sh", 'cd subdir && source ./dep.sh\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("subdir/data.txt", "payload\n")
            project.write("subdir/worker.sh", textwrap.dedent("""\
                cd "$(dirname "$BASH_SOURCE")" || exit 1
                cat ./data.txt
                """))
            project.write("main.sh", 'cd "$(dirname "$BASH_SOURCE")" || exit 1\nsource ./subdir/worker.sh\n')

            project.assert_compiled_matches(self, "main.sh", cwd=Path("/"))

    def test_dynamic_but_statically_resolvable_sources_match_bash(self):
        cases = {
            "variable dirname": 'THIS_DIR="$(dirname "$BASH_SOURCE")"\nsource "$THIS_DIR/dep.sh"\necho "main"\n',
            "inline dirname": 'source "$(dirname "$BASH_SOURCE")/dep.sh"\necho "main"\n',
            "realpath": 'source "$(realpath ./dep.sh)"\necho "main"\n',
        }

        for name, content in cases.items():
            with self.subTest(name=name), ScriptProject() as project:
                project.write("dep.sh", 'echo "dep"\n')
                project.write("main.sh", content)

                project.assert_compiled_matches(self, "main.sh")

    def test_environment_absolute_source_matches_bash(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep from env"\n')
            project.write("main.sh", 'source "$DEP_PATH"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh", env={"DEP_PATH": dep})

    def test_safe_cat_dynamic_source_matches_bash(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep from cat"\n')
            project.write("dep-path.txt", "./dep.sh\n")
            project.write("main.sh", 'source "$(cat dep-path.txt)"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("deps dir#tag/dep file.sh", 'echo "dep from special cat path"\n')
            project.write("path files/dep#path.txt", "./deps dir#tag/dep file.sh\n")
            project.write("main.sh", 'source "$(cat \'path files/dep#path.txt\')"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_safe_find_dynamic_source_matches_bash(self):
        with ScriptProject() as project:
            project.write("plugins/init.sh", 'echo "dep from find"\n')
            project.write("main.sh", 'source "$(find ./plugins -type f -name init.sh -print -quit)"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("plugins/root.sh", 'echo "root should not match depth"\n')
            project.write("plugins/nested/init.sh", 'echo "dep from filtered find"\n')
            project.write("main.sh", (
                'source "$(find ./plugins -maxdepth 2 -mindepth 2 '
                '-path ./plugins/nested/init.sh -print -quit)"\n'
                'echo "main"\n'
            ))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("plugin dir#tag/init.sh", 'echo "dep from special find root"\n')
            project.write("main.sh", 'source "$(find \'./plugin dir#tag\' -type f -name init.sh -print -quit)"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_safe_eval_source_matches_bash(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep from eval"\n')
            project.write("main.sh", 'eval "source ./dep.sh"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep from eval var"\n')
            project.write("main.sh", 'DEP_PATH="{0}"\neval ". \\"$DEP_PATH\\""\necho "main"\n'.format(dep))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep from eval command var"\n')
            project.write("main.sh", 'COMMAND="source ./dep.sh"\neval "$COMMAND"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_eval_source_replacement_ignores_quoted_decoys(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep from eval"\n')
            project.write("main.sh", 'echo \'eval "source ./dep.sh"\'; eval "source ./dep.sh"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_eval_source_after_logical_operator_matches_bash(self):
        with ScriptProject() as project:
            project.write("subdir/dep.sh", 'echo "dep from chained eval"\n')
            project.write("main.sh", 'cd subdir && eval "source ./dep.sh"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_non_source_eval_and_bash_c_commands_match_bash(self):
        with ScriptProject() as project:
            project.write("main.sh", 'eval "echo from eval"\nbash -c "echo from child"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_source_state_on_same_logical_line_matches_bash(self):
        with ScriptProject() as project:
            project.write("a.sh", 'FROM_A=./b.sh\n')
            project.write("b.sh", 'echo "dep from variable set by first source"\n')
            project.write("main.sh", 'source ./a.sh && source "$FROM_A"\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_heredoc_source_text_is_not_treated_as_dependency(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep should not run"\n')
            project.write("main.sh", textwrap.dedent("""\
                cat <<EOF
                source ./dep.sh
                EOF
                echo "main"
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            project.write("main.sh", 'echo "<<EOF"\necho $((1 << 2))\nsource ./dep.sh\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_parent_variables_are_available_before_sourced_file_runs(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep:${FOO:-missing}"\n')
            project.write("main.sh", "FOO=bar\nsource ./dep.sh\n")

            project.assert_compiled_matches(self, "main.sh")

    def test_nounset_state_before_source_is_preserved(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep:${UNSET_VAR}"\n')
            project.write("main.sh", "set +u\nsource ./dep.sh\n")

            project.assert_compiled_matches(self, "main.sh")

    def test_source_inside_multiline_function_matches_bash(self):
        with ScriptProject() as project:
            project.write("runtime.sh", 'echo "runtime"\n')
            project.write("main.sh", textwrap.dedent("""\
                helper() {
                  echo "before"
                  source ./runtime.sh
                  echo "after"
                }

                helper
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_duplicate_sources_execute_each_time_bash_would_execute_them(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            project.write("main.sh", "source ./dep.sh\nsource ./dep.sh\n")

            project.assert_compiled_matches(self, "main.sh")

    def test_shared_dependency_preserves_state_at_each_source_site(self):
        with ScriptProject() as project:
            project.write("shared.sh", 'echo "shared:$VALUE"\n')
            project.write("main.sh", textwrap.dedent("""\
                VALUE=one
                source ./shared.sh
                VALUE=two
                source ./shared.sh
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_circular_sources_raise_clear_error(self):
        with ScriptProject() as project:
            project.write("a.sh", "source ./b.sh\n")
            project.write("b.sh", "source ./a.sh\n")

            with self.assertRaises(RecursionError):
                project.compile("a.sh")

    def test_unsupported_source_families_fail_without_writing_output(self):
        cases = {
            "unknown scalar": ('source "$DEP"\n', 'source "$DEP"'),
            "array reference": ('deps=(./dep.sh)\nsource "${deps[0]}"\n', 'source "${deps[0]}"'),
            "for loop": (
                'for file in ./plugins/*.sh; do source "$file"; done\n',
                'do source "$file"',
            ),
            "if block": (
                'if [[ -f ./dep.sh ]]; then\n  source ./dep.sh\nfi\n',
                'source ./dep.sh',
            ),
            "case block": (
                'case "$ENV" in\n  prod) source ./prod.sh ;;\nesac\n',
                'prod) source ./prod.sh',
            ),
            "command builtin source": (
                'command source ./dep.sh\n',
                'command source ./dep.sh',
            ),
            "builtin source": (
                'builtin source ./dep.sh\n',
                'builtin source ./dep.sh',
            ),
            "command path source": (
                'command -p source ./dep.sh\n',
                'command -p source ./dep.sh',
            ),
            "assignment-prefixed source": (
                'FOO=bar source ./dep.sh\n',
                'FOO=bar source ./dep.sh',
            ),
            "assignment-prefixed command source": (
                'FOO=bar command source ./dep.sh\n',
                'FOO=bar command source ./dep.sh',
            ),
            "compact function source": (
                'helper(){ source ./dep.sh; }\nhelper\n',
                'helper(){ source ./dep.sh',
            ),
            "compact function keyword source": (
                'function helper { source ./dep.sh; }\nhelper\n',
                'function helper { source ./dep.sh',
            ),
        }

        for name, (content, expected_fragment) in cases.items():
            with self.subTest(name=name), ScriptProject() as project:
                project.write("dep.sh", 'echo "dep"\n')
                project.write("prod.sh", 'echo "prod"\n')
                project.write("plugins/a.sh", 'echo "plugin"\n')
                project.write("main.sh", content)
                output = project.write("compiled.sh", "existing output\n")

                with self.assertRaisesRegex((ValueError, NotImplementedError), "unsupported|unresolved|control flow") as cm:
                    project.compile("main.sh", output=output, mode="executable")

                self.assertIn(expected_fragment, str(cm.exception))
                self.assertEqual(output.read_text(), "existing output\n")

    def test_runtime_dynamic_sources_raise_clear_diagnostic(self):
        cases = {
            "cat multiple operands": (
                'source "$(cat dep-path.txt other.txt)"\n',
                'source "$(cat dep-path.txt other.txt)"',
            ),
            "cat multiple lines": (
                'source "$(cat dep-path.txt)"\n',
                'source "$(cat dep-path.txt)"',
            ),
            "cat pipe": (
                'source "$(cat dep-path.txt | head -1)"\n',
                'source "$(cat dep-path.txt | head -1)"',
            ),
            "cat missing path file": (
                'source "$(cat missing-path.txt)"\n',
                'source "$(cat missing-path.txt)"',
            ),
            "cat empty path file": (
                'source "$(cat empty-path.txt)"\n',
                'source "$(cat empty-path.txt)"',
            ),
            "find multiple matches": (
                'source "$(find . -name dep.sh)"\n',
                'source "$(find . -name dep.sh)"',
            ),
            "find no match": (
                'source "$(find ./nested -type f -name missing.sh -print -quit)"\n',
                'source "$(find ./nested -type f -name missing.sh -print -quit)"',
            ),
            "find exec": (
                'source "$(find . -name dep.sh -exec echo {} \\;)"\n',
                'source "$(find . -name dep.sh -exec echo {} \\;)"',
            ),
            "find quit without print": (
                'source "$(find ./nested -type f -name dep.sh -quit)"\n',
                'source "$(find ./nested -type f -name dep.sh -quit)"',
            ),
            "eval extra command": (
                'eval "source ./dep.sh; echo unsafe"\n',
                'eval "source ./dep.sh; echo unsafe"',
            ),
            "eval nested dynamic": (
                'eval "source $(cat dep-path.txt)"\n',
                'eval "source $(cat dep-path.txt)"',
            ),
            "eval unresolved payload source": (
                'COMMAND="source $DEP"\neval "$COMMAND"\n',
                'eval "$COMMAND"',
            ),
            "backticks": (
                "source `cat dep-path.txt`\n",
                "source `cat dep-path.txt`",
            ),
        }

        for name, (content, expected_fragment) in cases.items():
            with self.subTest(name=name), ScriptProject() as project:
                project.write("dep.sh", 'echo "dep"\n')
                project.write("nested/dep.sh", 'echo "nested dep"\n')
                if name == "cat multiple lines":
                    project.write("dep-path.txt", "./dep.sh\n./nested/dep.sh\n")
                else:
                    project.write("dep-path.txt", "./dep.sh\n")
                project.write("empty-path.txt", "\n")
                project.write("other.txt", "./nested/dep.sh\n")
                project.write("main.sh", content)
                output = project.path("compiled.sh")

                with self.assertRaisesRegex((ValueError, NotImplementedError), "unsupported|ambiguous|dynamic|source") as cm:
                    project.compile("main.sh", output=output, mode="executable")

                self.assertIn(expected_fragment, str(cm.exception))
                self.assertFalse(output.exists())

    def test_bash_c_source_is_rejected_for_executable_mode(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            project.write("main.sh", 'bash -c "source ./dep.sh"\n')

            with self.assertRaisesRegex(NotImplementedError, "child-shell|unsupported"):
                project.compile("main.sh", mode="executable")


if __name__ == "__main__":
    unittest.main()
