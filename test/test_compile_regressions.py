import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from methods.source_effects import DiagnosticSeverity
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
                'source ./dir#tag/dep.sh\necho "main"\n',
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

    def test_exact_array_index_source_matches_bash(self):
        with ScriptProject() as project:
            project.write("deps/feature.sh", 'echo "feature"\n')
            project.write("main.sh", textwrap.dedent("""\
                deps=(./unused.sh ./deps/feature.sh)
                source "${deps[1]}"
                echo "main"
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_non_source_array_words_match_bash(self):
        with ScriptProject() as project:
            project.write("main.sh", textwrap.dedent("""\
                tokens=(source ./dep.sh)
                printf '%s:%s\n' "${tokens[0]}" "${tokens[1]}"
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_exact_literal_for_loop_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("a.sh", 'echo "dep:a:$dep"\n')
            project.write("b.sh", 'echo "dep:b:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dep in ./a.sh ./b.sh; do
                  echo "before:$dep"
                  source "$dep"
                  echo "after:$dep"
                done
                echo "final:$dep"
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_exact_array_for_loop_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("deps/a.sh", 'echo "array:a"\n')
            project.write("deps/b.sh", 'echo "array:b"\n')
            project.write("main.sh", textwrap.dedent("""\
                deps=(./deps/a.sh ./deps/b.sh)
                for dep in "${deps[@]}"; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_exact_newline_do_for_loop_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("a.sh", 'echo "newline:a"\n')
            project.write("b.sh", 'echo "newline:b"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dep in ./a.sh ./b.sh
                do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_exact_scalar_for_loop_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("deps/a.sh", 'echo "scalar:a"\n')
            project.write("deps/b.sh", 'echo "scalar:b"\n')
            project.write("main.sh", textwrap.dedent("""\
                FIRST=./deps/a.sh
                SECOND=./deps/b.sh
                for dep in "$FIRST" "$SECOND"; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("deps/a.sh", 'echo "scalar wordlist:a:$dep"\n')
            project.write("deps/b.sh", 'echo "scalar wordlist:b:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                DEPS="./deps/a.sh   ./deps/b.sh"
                for dep in $DEPS; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("deps dir#tag/a dep.sh", 'echo "quoted scalar special:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                DEP="./deps dir#tag/a dep.sh"
                for dep in "$DEP"; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("plugins/b.sh", 'echo "scalar glob:b:$dep"\n')
            project.write("plugins/a.sh", 'echo "scalar glob:a:$dep"\n')
            project.write("plugins/readme.txt", 'echo "not sourced"\n')
            project.write("main.sh", textwrap.dedent("""\
                DEPS="./plugins/*.sh"
                for dep in $DEPS; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_empty_scalar_for_loop_sources_match_bash_without_live_source(self):
        with ScriptProject() as project:
            project.write("a.sh", 'echo "should not run"\n')
            project.write("main.sh", textwrap.dedent("""\
                dep=./a.sh
                DEPS=""
                for dep in $DEPS; do source "$dep"; done
                echo "done:$dep"
                """))

            output = project.compile("main.sh", mode="executable")
            expected = project.run("main.sh")
            actual = project.run(output)
            compiled_content = output.read_text()

        self.assertEqual(actual.returncode, expected.returncode, actual.stdout)
        self.assertEqual(actual.stdout, expected.stdout)
        self.assertNotIn('source "$dep"', compiled_content)

    def test_exact_for_loop_repeated_same_line_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("a.sh", 'echo "repeat:a"\n')
            project.write("b.sh", 'echo "repeat:b"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dep in ./a.sh ./b.sh; do
                  source "$dep"; source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_exact_for_loop_special_paths_match_bash(self):
        with ScriptProject() as project:
            project.write("deps dir#tag/a dep.sh", 'echo "special:a:$dep"\n')
            project.write("deps dir#tag/b dep.sh", 'echo "special:b:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dep in "./deps dir#tag/a dep.sh" "./deps dir#tag/b dep.sh"; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_exact_for_loop_absolute_paths_match_bash(self):
        with ScriptProject() as project:
            first = project.write("deps/a.sh", 'echo "absolute:a"\n')
            second = project.write("deps/b.sh", 'echo "absolute:b"\n')
            project.write("main.sh", textwrap.dedent(f"""\
                for dep in "{first}" "{second}"; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_exact_for_loop_cwd_sensitive_source_expression_matches_bash(self):
        with ScriptProject() as project:
            project.write("one dir/dep.sh", 'echo "cwd:one:$PWD"\n')
            project.write("two#dir/dep.sh", 'echo "cwd:two:$PWD"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dir in "one dir" two#dir; do
                  cd "$dir"
                  source ./dep.sh
                  cd ..
                done
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_glob_for_loop_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("plugins/b.sh", 'echo "plugin:b:$dep"\n')
            project.write("plugins/a.sh", 'echo "plugin:a:$dep"\n')
            project.write("plugins/readme.txt", 'echo "not sourced"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dep in ./plugins/*.sh; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

    def test_glob_for_loop_special_paths_match_bash(self):
        with ScriptProject() as project:
            project.write("plugin {dir}#tag/b dep.sh", 'echo "special:b:$dep"\n')
            project.write("plugin {dir}#tag/a dep.sh", 'echo "special:a:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dep in "./plugin {dir}#tag"/*.sh; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

    def test_glob_for_loop_after_cd_matches_bash(self):
        with ScriptProject() as project:
            project.write("plugins/b.sh", 'echo "cd:b:$PWD:$dep"\n')
            project.write("plugins/a.sh", 'echo "cd:a:$PWD:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                cd plugins
                for dep in ./*.sh; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

    def test_glob_option_for_loop_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("plugins/.hidden.sh", 'echo "dotglob:hidden:$dep"\n')
            project.write("plugins/a.sh", 'echo "dotglob:a:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                shopt -s dotglob
                for dep in ./plugins/*.sh; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

        with ScriptProject() as project:
            project.write("plugins/a.sh", 'echo "globstar:a:$dep"\n')
            project.write("plugins/nested/b.sh", 'echo "globstar:b:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                shopt -s globstar
                for dep in ./plugins/**/*.sh; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

        with ScriptProject() as project:
            project.write("plugins/one/a.sh", 'echo "no globstar one-level:$dep"\n')
            project.write("plugins/one/deep/b.sh", 'echo "no globstar deep:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dep in ./plugins/**/*.sh; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

        with ScriptProject() as project:
            project.write("plugins/a.sh", 'echo "nocase:a:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                shopt -s nocaseglob
                for dep in ./plugins/*.SH; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

    def test_brace_and_nullglob_for_loop_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("plugins/a.sh", 'echo "brace:a:$dep"\n')
            project.write("plugins/b.sh", 'echo "brace:b:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dep in ./plugins/{a,b}.sh; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

        with ScriptProject() as project:
            project.write("main.sh", textwrap.dedent("""\
                shopt -s nullglob
                for dep in ./missing/*.sh; do
                  source "$dep"
                done
                echo done
                """))

            output = project.compile("main.sh", mode="executable")
            expected = project.run("main.sh")
            actual = project.run(output)
            compiled_content = output.read_text()

        self.assertEqual(actual.returncode, expected.returncode, actual.stdout)
        self.assertEqual(actual.stdout, expected.stdout)
        self.assertNotIn('source "$dep"', compiled_content)

    def test_globignore_for_loop_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("plugins/.hidden.sh", 'echo "globignore:hidden:$dep"\n')
            project.write("plugins/a.sh", 'echo "globignore:a:$dep"\n')
            project.write("plugins/b.sh", 'echo "globignore:b:$dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                GLOBIGNORE=./plugins/b.sh
                for dep in ./plugins/*.sh; do
                  source "$dep"
                done
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

    def test_direct_source_glob_with_single_match_matches_bash(self):
        with ScriptProject() as project:
            project.write("plugins/only.sh", 'echo "single glob"\n')
            project.write("main.sh", 'source ./plugins/*.sh\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

    def test_direct_source_glob_with_quoted_literal_path_chars_matches_bash(self):
        with ScriptProject() as project:
            project.write("plugin {dir}#tag/only dep.sh", 'echo "special single glob"\n')
            project.write("main.sh", 'source "./plugin {dir}#tag"/*.sh\necho "main"\n')

            project.assert_compiled_matches(self, "main.sh", env={"LC_ALL": "C"})

    def test_if_block_source_matches_bash(self):
        with ScriptProject() as project:
            project.write("optional.sh", 'echo "optional:$LOAD_OPTIONAL"\n')
            project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$LOAD_OPTIONAL" ]]; then
                  source ./optional.sh
                fi
                echo "main"
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LOAD_OPTIONAL": "1"})
            project.assert_compiled_matches(self, "main.sh", env={"LOAD_OPTIONAL": ""})

    def test_if_else_branch_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("prod.sh", 'echo "prod:$MODE"\n')
            project.write("dev.sh", 'echo "dev:$MODE"\n')
            project.write("main.sh", textwrap.dedent("""\
                if [[ "$MODE" == prod ]]; then
                  source ./prod.sh
                else
                  source ./dev.sh
                fi
                echo "main"
                """))

            project.assert_compiled_matches(self, "main.sh", env={"MODE": "prod"})
            project.assert_compiled_matches(self, "main.sh", env={"MODE": "dev"})

    def test_if_elif_branch_sources_match_bash(self):
        with ScriptProject() as project:
            project.write("prod.sh", 'echo "prod:$MODE"\n')
            project.write("stage.sh", 'echo "stage:$MODE"\n')
            project.write("dev.sh", 'echo "dev:$MODE"\n')
            project.write("main.sh", textwrap.dedent("""\
                if [[ "$MODE" == prod ]]; then
                  source ./prod.sh
                elif [[ "$MODE" == stage ]]; then
                  source ./stage.sh
                else
                  source ./dev.sh
                fi
                echo "main"
                """))

            project.assert_compiled_matches(self, "main.sh", env={"MODE": "prod"})
            project.assert_compiled_matches(self, "main.sh", env={"MODE": "stage"})
            project.assert_compiled_matches(self, "main.sh", env={"MODE": "dev"})

    def test_if_bracket_and_test_predicates_match_bash(self):
        with ScriptProject() as project:
            project.write("bracket.sh", 'echo "bracket"\n')
            project.write("testdep.sh", 'echo "test predicate"\n')
            project.write("main.sh", textwrap.dedent("""\
                if [ -f ./bracket.sh ]; then
                  source ./bracket.sh
                fi
                if test -f ./testdep.sh; then
                  source ./testdep.sh
                fi
                echo "main"
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_compound_if_predicates_match_bash(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "compound dep"\n')
            project.write("fallback.sh", 'echo "fallback dep"\n')
            project.write("mismatch.sh", 'echo "should not be inlined"\n')
            project.write("variable-pattern.sh", 'echo "variable pattern dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                LOAD_DEP=1
                MODE=prod-eu
                PATTERN=prod*
                if [[ -f ./dep.sh && -n "$LOAD_DEP" ]]; then
                  source ./dep.sh
                fi
                if [[ -f ./missing.sh || "$LOAD_DEP" == 1 ]]; then
                  source ./fallback.sh
                fi
                if [[ "$MODE" != prod* ]]; then
                  source ./mismatch.sh
                fi
                if [[ "$MODE" == $PATTERN ]]; then
                  source ./variable-pattern.sh
                fi
                echo "main"
                """))

            output = project.compile("main.sh", mode="executable")
            expected = project.run("main.sh")
            actual = project.run(output)
            compiled_content = output.read_text()

        self.assertEqual(actual.returncode, expected.returncode, actual.stdout)
        self.assertEqual(actual.stdout, expected.stdout)
        self.assertNotIn("should not be inlined", compiled_content)

    def test_arithmetic_regex_and_grep_if_predicates_match_bash(self):
        with ScriptProject() as project:
            project.write("arithmetic.sh", 'echo "arithmetic:$COUNT"\n')
            project.write("numeric.sh", 'echo "numeric:$COUNT"\n')
            project.write("regex.sh", 'echo "regex:$MODE"\n')
            project.write("pattern.sh", 'echo "pattern:$MODE"\n')
            project.write("grep.sh", 'echo "grep"\n')
            project.write("grep-regex.sh", 'echo "grep regex"\n')
            project.write("config", "enabled=true\n")
            project.write("main.sh", textwrap.dedent("""\
                COUNT=2
                MODE=prod-eu
                if (( COUNT > 1 )); then
                  source ./arithmetic.sh
                fi
                if [[ "$COUNT" -gt 1 ]]; then
                  source ./numeric.sh
                fi
                if [[ "$MODE" =~ ^prod ]]; then
                  source ./regex.sh
                fi
                if [[ "$MODE" == prod* ]]; then
                  source ./pattern.sh
                fi
                if grep -q enabled config; then
                  source ./grep.sh
                fi
                if grep -Eq '^enabled=true$' config; then
                  source ./grep-regex.sh
                fi
                echo "main"
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_exact_if_unreachable_sources_match_bash(self):
        cases = {
            "unreachable else source": textwrap.dedent("""\
                MODE=prod
                if [[ "$MODE" == prod ]]; then
                  source ./prod.sh
                else
                  source ./missing.sh
                fi
                echo "main"
                """),
            "unreachable then source": textwrap.dedent("""\
                MODE=dev
                if [[ "$MODE" == prod ]]; then
                  source ./missing.sh
                else
                  source ./dev.sh
                fi
                echo "main"
                """),
            "missing optional file guard": textwrap.dedent("""\
                if [[ -f ./missing-optional.sh ]]; then
                  source ./missing-optional.sh
                fi
                echo "main"
                """),
            "inline unreachable source": textwrap.dedent("""\
                MODE=prod
                if [[ "$MODE" == prod ]]; then source ./prod.sh; else source ./missing.sh; fi
                echo "main"
                """),
            "unreachable command source": textwrap.dedent("""\
                MODE=prod
                if [[ "$MODE" == prod ]]; then
                  echo "prod"
                else
                  eval "source ./missing.sh"
                fi
                echo "main"
                """),
            "unreachable command dot source": textwrap.dedent("""\
                MODE=prod
                if [[ "$MODE" == prod ]]; then
                  echo "prod"
                else
                  eval ". ./missing.sh"
                fi
                echo "main"
                """),
        }

        for name, content in cases.items():
            with self.subTest(name=name), ScriptProject() as project:
                project.write("prod.sh", 'echo "prod"\n')
                project.write("dev.sh", 'echo "dev"\n')
                project.write("main.sh", content)

                project.assert_compiled_matches(self, "main.sh")

    def test_case_block_sources_match_bash(self):
        cases = {
            "assigned subject": (
                textwrap.dedent("""\
                    ENV=prod
                    case "$ENV" in
                      prod) source ./prod.sh ;;
                      dev) source ./missing-dev.sh ;;
                    esac
                    echo "main"
                    """),
                None,
            ),
            "environment subject": (
                textwrap.dedent("""\
                    case "$ENV" in
                      prod) source ./prod.sh ;;
                      dev) source ./dev.sh ;;
                    esac
                    echo "main"
                    """),
                {"ENV": "dev"},
            ),
            "default arm": (
                textwrap.dedent("""\
                    ENV=qa
                    case "$ENV" in
                      prod) source ./missing-prod.sh ;;
                      *) source ./default.sh ;;
                    esac
                    echo "main"
                    """),
                None,
            ),
            "alternate patterns": (
                textwrap.dedent("""\
                    ENV=stage
                    case "$ENV" in
                      prod|stage) source ./prod.sh ;;
                      dev) source ./missing-dev.sh ;;
                    esac
                    echo "main"
                    """),
                None,
            ),
            "glob pattern": (
                textwrap.dedent("""\
                    ENV=prod-eu
                    case "$ENV" in
                      prod-*) source ./prod.sh ;;
                      dev) source ./missing-dev.sh ;;
                    esac
                    echo "main"
                    """),
                None,
            ),
            "quoted literal pattern": (
                textwrap.dedent("""\
                    ENV='prod-*'
                    case "$ENV" in
                      "prod-*") source ./prod.sh ;;
                      *) source ./missing-default.sh ;;
                    esac
                    echo "main"
                    """),
                None,
            ),
            "no matching arm": (
                textwrap.dedent("""\
                    ENV=qa
                    case "$ENV" in
                      prod) source ./missing-prod.sh ;;
                      dev) source ./missing-dev.sh ;;
                    esac
                    echo "main"
                    """),
                None,
            ),
            "inline arms": (
                textwrap.dedent("""\
                    ENV=prod
                    case "$ENV" in prod) source ./prod.sh ;; dev) source ./missing-dev.sh ;; esac
                    echo "main"
                    """),
                None,
            ),
            "quoted subject containing in": (
                textwrap.dedent("""\
                    case "value in prod" in
                      *prod) source ./prod.sh ;;
                      *) source ./missing-default.sh ;;
                    esac
                    echo "main"
                    """),
                None,
            ),
            "unknown source-free case": (
                textwrap.dedent("""\
                    case "$ENV" in
                      prod) echo "prod mode" ;;
                      *) echo "other mode" ;;
                    esac
                    source ./prod.sh
                    echo "main"
                    """),
                None,
            ),
        }

        for name, (content, env) in cases.items():
            with self.subTest(name=name), ScriptProject() as project:
                project.write("prod.sh", 'echo "prod:$ENV"\n')
                project.write("dev.sh", 'echo "dev:$ENV"\n')
                project.write("default.sh", 'echo "default:$ENV"\n')
                project.write("main.sh", content)

                project.assert_compiled_matches(self, "main.sh", env=env)

    def test_case_block_state_after_arm_matches_bash(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "after:$DEP"\n')
            project.write("main.sh", textwrap.dedent("""\
                ENV=prod
                case "$ENV" in
                  prod) DEP=./dep.sh ;;
                  dev) DEP=./missing.sh ;;
                esac
                source "$DEP"
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_if_branch_local_state_matches_bash(self):
        with ScriptProject() as project:
            project.write("a.sh", 'echo "branch:a:$DEP"\n')
            project.write("b.sh", 'echo "branch:b:$DEP"\n')
            project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$USE_A" ]]; then
                  DEP=./a.sh
                  source "$DEP"
                else
                  DEP=./b.sh
                  source "$DEP"
                fi
                echo "main"
                """))

            project.assert_compiled_matches(self, "main.sh", env={"USE_A": "1"})
            project.assert_compiled_matches(self, "main.sh", env={"USE_A": ""})

    def test_if_branch_local_cd_matches_bash(self):
        with ScriptProject() as project:
            project.write("enabled/dep.sh", 'echo "enabled:$PWD"\n')
            project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$LOAD_ENABLED" ]]; then
                  cd enabled
                  source ./dep.sh
                fi
                echo "main"
                """))

            project.assert_compiled_matches(self, "main.sh", env={"LOAD_ENABLED": "1"})
            project.assert_compiled_matches(self, "main.sh", env={"LOAD_ENABLED": ""})

    def test_if_converged_state_after_branch_matches_bash(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "after:$DEP"\n')
            project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$FLAG" ]]; then
                  DEP=./dep.sh
                else
                  DEP=./dep.sh
                fi
                source "$DEP"
                """))

            project.assert_compiled_matches(self, "main.sh", env={"FLAG": "1"})
            project.assert_compiled_matches(self, "main.sh", env={"FLAG": ""})

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

    def test_runtime_source_reference_before_source_on_same_line_matches_bash(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep after bash source"\n')
            project.write("main.sh", 'echo "$BASH_SOURCE"; source ./dep.sh\n')

            project.assert_compiled_matches(self, "main.sh")

    def test_loop_heredoc_source_text_is_not_treated_as_dependency(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "loop dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                for dep in ./dep.sh; do
                  cat <<EOF
                source "$dep"
                EOF
                  source "$dep"
                done
                """))

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

    def test_source_inside_compact_function_matches_bash(self):
        with ScriptProject() as project:
            project.write("runtime.sh", 'echo "runtime"\n')
            project.write("main.sh", 'helper(){ echo "before"; source ./runtime.sh; echo "after"; }\nhelper\n')

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("runtime.sh", 'echo "runtime keyword"\n')
            project.write("main.sh", 'function helper { source ./runtime.sh; }\nhelper\n')

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("runtime.sh", 'echo "runtime split brace"\n')
            project.write("main.sh", textwrap.dedent("""\
                helper()
                {
                  source ./runtime.sh
                }
                helper
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_function_source_argument_matches_bash(self):
        with ScriptProject() as project:
            project.write("a.sh", 'echo "a:$1"\n')
            project.write("b.sh", 'echo "b:$1"\n')
            project.write("main.sh", textwrap.dedent("""\
                load_dep() {
                  source "$1"
                }

                load_dep ./a.sh
                load_dep ./b.sh
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("deps dir#tag/a dep.sh", 'echo "special function arg:$1"\n')
            project.write("main.sh", textwrap.dedent("""\
                load_dep() {
                  source "$1"
                }

                load_dep "./deps dir#tag/a dep.sh"
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_function_defined_by_sourced_file_matches_bash(self):
        with ScriptProject() as project:
            project.write("lib.sh", textwrap.dedent("""\
                load_dep() {
                  source "$1"
                }
                """))
            project.write("dep.sh", 'echo "dep from sourced function"\n')
            project.write("main.sh", textwrap.dedent("""\
                source ./lib.sh
                load_dep ./dep.sh
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_function_source_state_matches_bash(self):
        with ScriptProject() as project:
            project.write("deps/inside.sh", 'echo "inside:$DEP:$PWD"\n')
            project.write("outside.sh", 'echo "outside:$DEP:$PWD"\n')
            project.write("main.sh", textwrap.dedent("""\
                DEP=./outside.sh
                load_inside() {
                  local DEP=./inside.sh
                  cd deps
                  source "$DEP"
                }

                load_inside
                cd ..
                source "$DEP"
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("deps/inside.sh", 'echo "expanded local:$DEP"\n')
            project.write("main.sh", textwrap.dedent("""\
                ROOT=./deps
                load_inside() {
                  local DEP="${ROOT}/inside.sh"
                  source "$DEP"
                }

                load_inside
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("deps/inside.sh", 'echo "inside prefix:$DEP"\n')
            project.write("outside.sh", 'echo "outside restored:$DEP"\n')
            project.write("main.sh", textwrap.dedent("""\
                DEP=./outside.sh
                load_dep() {
                  source "$DEP"
                }

                DEP="./deps/inside.sh" load_dep
                source "$DEP"
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("outer.sh", 'echo "outer arg:$DEP"\n')
            project.write("inner.sh", 'echo "inner prefix:$DEP"\n')
            project.write("main.sh", textwrap.dedent("""\
                DEP=./outer.sh
                load_dep() {
                  source "$1"
                  source "$DEP"
                }

                DEP=./inner.sh load_dep "$DEP"
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("outer.sh", 'echo "outer redirected:$DEP"\n')
            project.write("inner.sh", 'echo "inner redirected:$DEP"\n')
            project.write("main.sh", textwrap.dedent("""\
                DEP=./outer.sh
                load_dep() {
                  local DEP=./inner.sh
                  source "$DEP"
                } > out.txt

                load_dep
                cat out.txt
                source "$DEP"
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_function_control_flow_matches_bash(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "shifted:$1"\n')
            project.write("main.sh", textwrap.dedent("""\
                load_dep() {
                  shift
                  source "$1"
                }

                load_dep ignored ./dep.sh
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("missing.sh", 'echo "should not run"\n')
            project.write("main.sh", textwrap.dedent("""\
                load_dep() {
                  return 0
                  source ./missing.sh
                }

                load_dep
                echo done
                """))

            output = project.compile("main.sh", mode="executable")
            expected = project.run("main.sh")
            actual = project.run(output)
            compiled_content = output.read_text()

        self.assertEqual(actual.returncode, expected.returncode, actual.stdout)
        self.assertEqual(actual.stdout, expected.stdout)
        self.assertNotIn("should not run", compiled_content)

        with ScriptProject() as project:
            project.write("after.sh", 'echo "after should not run"\n')
            project.write("fallback.sh", 'echo "fallback runs"\n')
            project.write("main.sh", textwrap.dedent("""\
                load_dep() {
                  return 1
                }

                load_dep && source ./after.sh
                load_dep || source ./fallback.sh
                """))

            output = project.compile("main.sh", mode="executable")
            expected = project.run("main.sh")
            actual = project.run(output)
            compiled_content = output.read_text()

        self.assertEqual(actual.returncode, expected.returncode, actual.stdout)
        self.assertEqual(actual.stdout, expected.stdout)
        self.assertNotIn("after should not run", compiled_content)

        with ScriptProject() as project:
            project.write("after.sh", 'echo "after shift should not run"\n')
            project.write("fallback.sh", 'echo "fallback shift runs"\n')
            project.write("main.sh", textwrap.dedent("""\
                shift_too_far() {
                  shift 9
                }

                shift_too_far ignored && source ./after.sh
                shift_too_far ignored || source ./fallback.sh
                """))

            output = project.compile("main.sh", mode="executable")
            expected = project.run("main.sh")
            actual = project.run(output)
            compiled_content = output.read_text()

        self.assertEqual(actual.returncode, expected.returncode, actual.stdout)
        self.assertEqual(actual.stdout, expected.stdout)
        self.assertNotIn("after shift should not run", compiled_content)

    def test_nested_function_control_flow_matches_bash(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "nested function dep"\n')
            project.write("missing.sh", 'echo "missing"\n')
            project.write("main.sh", textwrap.dedent("""\
                load_dep() {
                  if [[ -f ./dep.sh ]]; then
                    source ./dep.sh
                  else
                    source ./missing.sh
                  fi
                }

                load_dep
                """))

            project.assert_compiled_matches(self, "main.sh")

    def test_dynamic_function_dispatch_and_same_line_tail_match_bash(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dynamic dispatch"\n')
            project.write("main.sh", textwrap.dedent("""\
                load_dep() { source "$1"; }; FN=load_dep
                "$FN" ./dep.sh
                """))

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("dep.sh", 'echo "same line tail"\n')
            project.write("main.sh", 'load_dep() { source ./dep.sh; }; load_dep\n')

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("dep.sh", 'echo "same line function body"\n')
            project.write("tail.sh", 'echo "same line tail source"\n')
            project.write(
                "main.sh",
                'load_dep() { source ./dep.sh; }; load_dep; source ./tail.sh\n',
            )

            project.assert_compiled_matches(self, "main.sh")

        with ScriptProject() as project:
            project.write("dep.sh", 'echo "same line chained body"\n')
            project.write("tail.sh", 'echo "same line chained tail"\n')
            project.write(
                "main.sh",
                'load_dep() { source ./dep.sh; }; load_dep && source ./tail.sh\n',
            )

            project.assert_compiled_matches(self, "main.sh")

    def test_branch_dependent_function_definitions_match_bash_when_equivalent(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "branch function dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$USE_ALT" ]]; then
                  load_dep() { source ./dep.sh; }
                else
                  load_dep() { source ./dep.sh; }
                fi

                load_dep
                """))

            project.assert_compiled_matches(self, "main.sh")
            project.assert_compiled_matches(self, "main.sh", env={"USE_ALT": "1"})

    def test_branch_dependent_function_definitions_reject_when_different(self):
        with ScriptProject() as project:
            project.write("a.sh", 'echo "a"\n')
            project.write("b.sh", 'echo "b"\n')
            project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$USE_A" ]]; then
                  load_dep() { source ./a.sh; }
                else
                  load_dep() { source ./b.sh; }
                fi

                load_dep
                """))
            output = project.path("compiled.sh")

            with self.assertRaisesRegex(NotImplementedError, "branch-dependent function"):
                project.compile("main.sh", output=output, mode="executable")

            self.assertFalse(output.exists())

    def test_unresolved_dynamic_function_dispatch_rejects_before_output(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            project.write("main.sh", textwrap.dedent("""\
                load_dep() {
                  source ./dep.sh
                }
                "$FN"
                """))
            output = project.path("compiled.sh")

            with self.assertRaisesRegex(NotImplementedError, "dynamic function dispatch"):
                project.compile("main.sh", output=output, mode="executable")

            self.assertFalse(output.exists())

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
            "nondefault ifs scalar word-list loop": (
                'IFS=:\nDEPS="./plugins/a.sh:./plugins/b.sh"\nfor file in $DEPS; do source "$file"; done\n',
                'for file in $DEPS; do source "$file"; done',
            ),
            "unmatched glob loop": (
                'for file in ./missing/*.sh; do source "$file"; done\n',
                'for file in ./missing/*.sh; do source "$file"; done',
            ),
            "quoted glob loop": (
                'for file in "./plugins/*.sh"; do source "$file"; done\n',
                'for file in "./plugins/*.sh"; do source "$file"; done',
            ),
            "failglob unmatched loop": (
                'shopt -s failglob\nfor file in ./missing/*.sh; do source "$file"; done\n',
                'for file in ./missing/*.sh; do source "$file"; done',
            ),
            "extglob loop": (
                'shopt -s extglob\nfor file in ./plugins/@(a|b).sh; do source "$file"; done\n',
                'for file in ./plugins/@(a|b).sh; do source "$file"; done',
            ),
            "noglob loop": (
                'set -f\nfor file in ./plugins/*.sh; do source "$file"; done\n',
                'for file in ./plugins/*.sh; do source "$file"; done',
            ),
            "globignore removes all loop matches": (
                'GLOBIGNORE=./plugins/a.sh:./plugins/b.sh\nfor file in ./plugins/*.sh; do source "$file"; done\n',
                'for file in ./plugins/*.sh; do source "$file"; done',
            ),
            "direct source glob multiple matches": (
                'source ./plugins/*.sh\n',
                'source ./plugins/*.sh',
            ),
            "unsupported if predicate": (
                "if awk 'BEGIN { exit 0 }'; then\n  source ./dep.sh\nfi\n",
                "awk 'BEGIN { exit 0 }'",
            ),
            "unsupported if glob predicate": (
                'if [ -f ./plugins/*.sh ]; then\n  source ./dep.sh\nfi\n',
                '[ -f ./plugins/*.sh ]',
            ),
            "unsupported bracket string glob predicate": (
                'MODE=prod\nif [ "$MODE" = prod* ]; then\n  source ./dep.sh\nfi\n',
                '[ "$MODE" = prod* ]',
            ),
            "unsupported grep basic regex predicate": (
                'if grep -q "enabled.*" config; then\n  source ./dep.sh\nfi\n',
                'grep -q "enabled.*" config',
            ),
            "unsupported POSIX regex predicate": (
                'MODE=5\nif [[ "$MODE" =~ [[:digit:]] ]]; then\n  source ./dep.sh\nfi\n',
                '[[ "$MODE" =~ [[:digit:]] ]]',
            ),
            "unsupported Python regex predicate": (
                'MODE=5\nif [[ "$MODE" =~ \\d+ ]]; then\n  source ./dep.sh\nfi\n',
                '[[ "$MODE" =~ \\d+ ]]',
            ),
            "unsupported grep Python regex predicate": (
                'if grep -Eq "\\d+" config; then\n  source ./dep.sh\nfi\n',
                'grep -Eq "\\d+" config',
            ),
            "divergent if branch state": (
                'if [[ -n "$USE_A" ]]; then\n  DEP=./a.sh\nelse\n  DEP=./b.sh\nfi\nsource "$DEP"\n',
                'source "$DEP"',
            ),
            "case block": (
                'case "$ENV" in\n  prod) source ./prod.sh ;;\nesac\n',
                'case "$ENV" in',
            ),
            "case fallthrough": (
                'ENV=prod\ncase "$ENV" in\n  prod) source ./prod.sh ;&\n  *) source ./dev.sh ;;\nesac\n',
                'case "$ENV" in',
            ),
            "case dynamic subject": (
                'case "$(cat env.txt)" in\n  prod) source ./prod.sh ;;\nesac\n',
                'case "$(cat env.txt)" in',
            ),
            "case variable pattern": (
                'ENV=prod\nPATTERN=prod\ncase "$ENV" in\n  "$PATTERN") source ./prod.sh ;;\nesac\n',
                'case "$ENV" in',
            ),
            "case divergent state": (
                'case "$ENV" in\n  prod) DEP=./a.sh ;;\n  dev) DEP=./b.sh ;;\nesac\nsource "$DEP"\n',
                'source "$DEP"',
            ),
            "case hidden eval source": (
                'case "$ENV" in\n  prod) COMMAND="source ./prod.sh"; eval "$COMMAND" ;;\nesac\n',
                'case "$ENV" in',
            ),
            "case escaped pattern": (
                'ENV="prod*"\ncase "$ENV" in\n  prod\\*) source ./prod.sh ;;\n  *) source ./b.sh ;;\nesac\n',
                'case "$ENV" in',
            ),
            "case mixed-quoted pattern": (
                'ENV="prod-eu"\ncase "$ENV" in\n  prod"-"*) source ./prod.sh ;;\nesac\n',
                'case "$ENV" in',
            ),
            "case POSIX class pattern": (
                'ENV=5\ncase "$ENV" in\n  [[:digit:]]) source ./prod.sh ;;\nesac\n',
                'case "$ENV" in',
            ),
            "subshell source": (
                '(source ./dep.sh)\n',
                '(source ./dep.sh)',
            ),
            "subshell dot source": (
                '(. ./dep.sh)\n',
                '(. ./dep.sh)',
            ),
            "separated subshell source": (
                'echo before; ( source ./dep.sh ); echo after\n',
                '( source ./dep.sh )',
            ),
            "command substitution source": (
                'echo "$(source ./dep.sh)"\n',
                'echo "$(source ./dep.sh)"',
            ),
            "process substitution source": (
                'cat <(source ./dep.sh)\n',
                'cat <(source ./dep.sh)',
            ),
            "backtick substitution source": (
                'echo `source ./dep.sh`\n',
                'echo `source ./dep.sh`',
            ),
            "arithmetic nested source": (
                'echo $(( $(source ./dep.sh) + 1 ))\n',
                'echo $(( $(source ./dep.sh) + 1 ))',
            ),
            "command substitution if source": (
                'echo "$(if true; then source ./dep.sh; fi)"\n',
                'echo "$(if true; then source ./dep.sh; fi)"',
            ),
            "process substitution loop source": (
                'cat <(for f in ./dep.sh; do source "$f"; done)\n',
                'cat <(for f in ./dep.sh; do source "$f"; done)',
            ),
            "backtick case dot source": (
                'echo `case "$ENV" in prod) . ./dep.sh ;; esac`\n',
                'echo `case "$ENV" in prod) . ./dep.sh ;; esac`',
            ),
            "branch-dependent function return": (
                'load_dep() {\n  if [[ -n "$SKIP" ]]; then return 0; fi\n  source ./dep.sh\n}\nload_dep\n',
                'if [[ -n "$SKIP" ]]',
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
        }

        for name, (content, expected_fragment) in cases.items():
            with self.subTest(name=name), ScriptProject() as project:
                project.write("dep.sh", 'echo "dep"\n')
                project.write("prod.sh", 'echo "prod"\n')
                project.write("a.sh", 'echo "a"\n')
                project.write("b.sh", 'echo "b"\n')
                project.write("config", "enabled=true\n")
                project.write("plugins/a.sh", 'echo "plugin"\n')
                project.write("plugins/b.sh", 'echo "plugin b"\n')
                project.write("main.sh", content)
                output = project.write("compiled.sh", "existing output\n")

                with self.assertRaisesRegex((ValueError, NotImplementedError), "unsupported|unresolved|control flow") as cm:
                    project.compile("main.sh", output=output, mode="executable")

                self.assertIn(expected_fragment, str(cm.exception))
                self.assertIsNotNone(cm.exception.diagnostic)
                self.assertEqual(cm.exception.diagnostic.severity, DiagnosticSeverity.ERROR)
                self.assertEqual(cm.exception.diagnostic.location.path, project.path("main.sh"))
                self.assertGreater(cm.exception.diagnostic.location.line, 0)
                self.assertIn(expected_fragment, cm.exception.diagnostic.fragment)
                self.assertTrue(cm.exception.diagnostic.code.startswith("unsupported.source."))
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
                self.assertIsNotNone(cm.exception.diagnostic)
                self.assertEqual(cm.exception.diagnostic.severity, DiagnosticSeverity.ERROR)
                self.assertEqual(cm.exception.diagnostic.location.path, project.path("main.sh"))
                self.assertGreater(cm.exception.diagnostic.location.line, 0)
                self.assertIn(expected_fragment, cm.exception.diagnostic.fragment)
                self.assertTrue(cm.exception.diagnostic.code.startswith("unsupported.source."))
                self.assertFalse(output.exists())

    def test_bash_c_source_is_rejected_for_executable_mode(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            project.write("main.sh", 'bash -c "source ./dep.sh"\n')

            with self.assertRaisesRegex(NotImplementedError, "child-shell|unsupported") as cm:
                project.compile("main.sh", mode="executable")

        self.assertIsNotNone(cm.exception.diagnostic)
        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.command-resolution")
        self.assertEqual(cm.exception.diagnostic.fragment, 'bash -c "source ./dep.sh"')


if __name__ == "__main__":
    unittest.main()
