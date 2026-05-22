import textwrap
import unittest

from methods.source_effects import ExecutionModel, OccurrenceModel
from methods.source_evaluator import SourceEvaluator
from test.support import ScriptProject


class SourceEvaluatorTestCase(unittest.TestCase):
    def test_static_source_event_includes_state_before_source(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep:$FOO"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                FOO=bar
                source ./dep.sh
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.path, dep)
        self.assertEqual(event.execution_model, ExecutionModel.PARENT_SOURCE)
        self.assertEqual(event.state_before.variables["FOO"], "bar")
        self.assertEqual(event.state_before.cwd, entry.parent)
        self.assertEqual(event.state_before.bash_source_stack, (entry,))

    def test_cd_updates_state_for_relative_source_resolution(self):
        with ScriptProject() as project:
            dep = project.write("subdir/dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                cd subdir
                source ./dep.sh
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.path, dep)
        self.assertEqual(event.state_before.cwd, dep.parent)

    def test_set_options_are_captured_before_source(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                set -eu
                set +e
                set -o pipefail
                source ./dep.sh
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual(result.events[0].state_before.shell_options, frozenset({"nounset", "pipefail"}))

    def test_exact_array_index_source_is_resolved(self):
        with ScriptProject() as project:
            dep = project.write("deps/feature.sh", 'echo "feature"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                deps=(./base.sh ./deps/feature.sh)
                source "${deps[1]}"
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.path, dep)
        self.assertEqual(event.source_expression, '"${deps[1]}"')
        self.assertEqual(event.state_before.arrays["deps"], ("./base.sh", "./deps/feature.sh"))

    def test_duplicate_source_events_are_marked_repeated(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", "source ./dep.sh\nsource ./dep.sh\n")

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep, dep])
        self.assertEqual({event.occurrence_model for event in result.events}, {OccurrenceModel.REPEATED})

    def test_command_level_eval_source_is_resolved(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", 'COMMAND="source ./dep.sh"\neval "$COMMAND"\n')

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].path, dep)
        self.assertEqual(result.events[0].source_site, 'eval "$COMMAND"')

    def test_function_call_resolves_positional_source_argument(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                load_dep() {
                  source "$1"
                }
                load_dep ./dep.sh
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep])
        self.assertEqual(result.events[0].source_expression, '"$1"')
        self.assertEqual(result.events[0].source_value, "./dep.sh")
        self.assertEqual(result.events[0].location.line, 2)

    def test_function_call_mutates_parent_state(self):
        with ScriptProject() as project:
            dep = project.write("deps/dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                select_dep() {
                  cd deps
                  DEP=./dep.sh
                }
                select_dep
                source "$DEP"
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep])
        self.assertEqual(result.events[0].state_before.cwd, dep.parent)

    def test_function_local_assignment_does_not_leak(self):
        with ScriptProject() as project:
            dep = project.write("inside.sh", 'echo "inside"\n')
            outside = project.write("outside.sh", 'echo "outside"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                DEP=./outside.sh
                load_dep() {
                  local DEP=./inside.sh
                  source "$DEP"
                }
                load_dep
                source "$DEP"
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep, outside])

    def test_function_assignment_prefix_is_temporary(self):
        with ScriptProject() as project:
            dep = project.write("inside.sh", 'echo "inside"\n')
            outside = project.write("outside.sh", 'echo "outside"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                DEP=./outside.sh
                load_dep() {
                  source "$DEP"
                }
                DEP=./inside.sh load_dep
                source "$DEP"
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep, outside])

    def test_function_arguments_expand_before_assignment_prefixes(self):
        with ScriptProject() as project:
            outer = project.write("outer.sh", 'echo "outer"\n')
            inner = project.write("inner.sh", 'echo "inner"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                DEP=./outer.sh
                load_dep() {
                  source "$1"
                  source "$DEP"
                }
                DEP=./inner.sh load_dep "$DEP"
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [outer, inner])

    def test_recursive_function_source_raises_structured_diagnostic(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                load_dep() {
                  load_dep
                  source ./dep.sh
                }
                load_dep
                """))

            with self.assertRaisesRegex(NotImplementedError, "recursive function") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.function-recursion")
        self.assertEqual(cm.exception.diagnostic.location.line, 2)

    def test_unknown_array_source_raises_structured_diagnostic(self):
        with ScriptProject() as project:
            entry = project.write("main.sh", 'source "${deps[0]}"\n')

            with self.assertRaisesRegex(NotImplementedError, "array source") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.array-index")
        self.assertEqual(cm.exception.diagnostic.location.line, 1)
        self.assertEqual(cm.exception.diagnostic.fragment, 'source "${deps[0]}"')

    def test_if_block_source_is_evaluated_as_conditional(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                if [[ -f ./dep.sh ]]; then
                  source ./dep.sh
                fi
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep])
        self.assertEqual(result.events[0].occurrence_model, OccurrenceModel.CONDITIONAL)
        self.assertEqual(result.events[0].condition, "[[ -f ./dep.sh ]]")

    def test_if_block_unreachable_sources_are_disabled(self):
        with ScriptProject() as project:
            prod = project.write("prod.sh", 'echo "prod"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                MODE=prod
                if [[ "$MODE" == prod ]]; then
                  source ./prod.sh
                else
                  source ./missing.sh
                fi
                if [[ -f ./missing-optional.sh ]]; then
                  source ./missing-optional.sh
                fi
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [prod])
        self.assertEqual(
            [disabled.source_site for disabled in result.disabled_sources],
            ["source ./missing.sh", "source ./missing-optional.sh"],
        )

    def test_if_block_unsupported_condition_raises_structured_diagnostic(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                if grep -q enabled config; then
                  source ./dep.sh
                fi
                """))

            with self.assertRaisesRegex(NotImplementedError, "if condition") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.if-condition")
        self.assertEqual(cm.exception.diagnostic.location.line, 1)

    def test_case_block_exact_subject_selects_matching_arm(self):
        with ScriptProject() as project:
            prod = project.write("prod.sh", 'echo "prod"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                ENV=prod
                case "$ENV" in
                  prod) source ./prod.sh ;;
                  dev) source ./missing-dev.sh ;;
                esac
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [prod])
        self.assertEqual(result.events[0].occurrence_model, OccurrenceModel.MUTUALLY_EXCLUSIVE)
        self.assertEqual(result.events[0].condition, 'case "$ENV" in prod')
        self.assertEqual([disabled.source_site for disabled in result.disabled_sources], ["source ./missing-dev.sh"])

    def test_case_block_default_arm_is_selected_when_no_pattern_matches(self):
        with ScriptProject() as project:
            default = project.write("default.sh", 'echo "default"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                ENV=qa
                case "$ENV" in
                  prod) source ./missing-prod.sh ;;
                  *) source ./default.sh ;;
                esac
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [default])
        self.assertEqual(result.events[0].condition, 'case "$ENV" in *')
        self.assertEqual([disabled.source_site for disabled in result.disabled_sources], ["source ./missing-prod.sh"])

    def test_case_block_converged_arm_state_is_available_after_merge(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                ENV=prod
                case "$ENV" in
                  prod) DEP=./dep.sh ;;
                  dev) DEP=./missing.sh ;;
                esac
                source "$DEP"
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep])
        self.assertIsNone(result.events[0].condition)

    def test_case_block_unknown_subject_raises_structured_diagnostic(self):
        with ScriptProject() as project:
            project.write("prod.sh", 'echo "prod"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                case "$ENV" in
                  prod) source ./prod.sh ;;
                esac
                """))

            with self.assertRaisesRegex(NotImplementedError, "case subject") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.case-subject")
        self.assertEqual(cm.exception.diagnostic.location.line, 1)

    def test_case_block_unknown_subject_rejects_state_expanded_eval_source(self):
        with ScriptProject() as project:
            project.write("prod.sh", 'echo "prod"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                case "$ENV" in
                  prod) COMMAND="source ./prod.sh"; eval "$COMMAND" ;;
                esac
                """))

            with self.assertRaisesRegex(NotImplementedError, "case subject") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.case-subject")
        self.assertEqual(cm.exception.diagnostic.location.line, 1)

    def test_case_block_unknown_subject_rejects_positional_eval_payload(self):
        with ScriptProject() as project:
            entry = project.write("main.sh", textwrap.dedent("""\
                case "$ENV" in
                  prod) eval "$1" ;;
                esac
                """))

            with self.assertRaisesRegex(NotImplementedError, "case subject") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.case-subject")
        self.assertEqual(cm.exception.diagnostic.location.line, 1)

    def test_case_block_fallthrough_terminator_raises_structured_diagnostic(self):
        with ScriptProject() as project:
            project.write("prod.sh", 'echo "prod"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                ENV=prod
                case "$ENV" in
                  prod) source ./prod.sh ;&
                  *) echo done ;;
                esac
                """))

            with self.assertRaisesRegex(NotImplementedError, "case terminator") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.case-terminator")
        self.assertEqual(cm.exception.diagnostic.location.line, 2)

    def test_context_control_flow_source_is_conditional_and_does_not_leak_state(self):
        with ScriptProject() as project:
            optional = project.write("optional.sh", 'NEXT=./next.sh\nsource ./nested.sh\n')
            nested = project.write("nested.sh", 'echo "nested"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$LOAD_OPTIONAL" ]]; then
                  source ./optional.sh
                fi
                source "$NEXT"
                """))

            result = SourceEvaluator(mode="context").evaluate(entry)

        self.assertEqual([event.path for event in result.events], [optional, nested])
        self.assertEqual([event.occurrence_model for event in result.events], [
            OccurrenceModel.CONDITIONAL,
            OccurrenceModel.CONDITIONAL,
        ])
        self.assertEqual([event.condition for event in result.events], ['[[ -n "$LOAD_OPTIONAL" ]]', '[[ -n "$LOAD_OPTIONAL" ]]'])
        self.assertNotIn("NEXT", result.final_state.variables)

    def test_if_block_converged_branch_state_is_available_after_merge(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$USE_A" ]]; then
                  DEP=./dep.sh
                else
                  DEP=./dep.sh
                fi
                source "$DEP"
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep])
        self.assertEqual(result.events[0].occurrence_model, OccurrenceModel.ONCE)
        self.assertIsNone(result.events[0].condition)

    def test_if_block_divergent_branch_state_rejects_later_source(self):
        with ScriptProject() as project:
            project.write("a.sh", 'echo "a"\n')
            project.write("b.sh", 'echo "b"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$USE_A" ]]; then
                  DEP=./a.sh
                else
                  DEP=./b.sh
                fi
                source "$DEP"
                """))

            with self.assertRaisesRegex(NotImplementedError, "branch-dependent variable") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.branch-state")
        self.assertEqual(cm.exception.diagnostic.location.line, 6)

    def test_if_block_divergent_cwd_rejects_later_relative_cd(self):
        with ScriptProject() as project:
            project.mkdir("subdir")
            project.mkdir("relative")
            entry = project.write("main.sh", textwrap.dedent("""\
                if [[ -n "$USE_SUBDIR" ]]; then
                  cd subdir
                fi
                cd relative
                """))

            with self.assertRaisesRegex(NotImplementedError, "relative cd after branch-dependent cwd") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.branch-state")
        self.assertEqual(cm.exception.diagnostic.location.line, 4)

    def test_exact_literal_for_loop_sources_are_evaluated_in_order(self):
        with ScriptProject() as project:
            first = project.write("a.sh", 'echo "a"\n')
            second = project.write("b.sh", 'echo "b"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                for dep in ./a.sh ./b.sh; do
                  source "$dep"
                done
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [first, second])
        self.assertEqual([event.source_value for event in result.events], ["./a.sh", "./b.sh"])
        self.assertEqual(result.final_state.variables["dep"], "./b.sh")

    def test_exact_array_for_loop_sources_are_evaluated(self):
        with ScriptProject() as project:
            first = project.write("a.sh", 'echo "a"\n')
            second = project.write("b.sh", 'echo "b"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                deps=(./a.sh ./b.sh)
                for dep in "${deps[@]}"; do
                  source "$dep"
                done
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [first, second])

    def test_exact_scalar_for_loop_sources_are_evaluated(self):
        with ScriptProject() as project:
            first = project.write("a.sh", 'echo "a"\n')
            second = project.write("b.sh", 'echo "b"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                A=./a.sh
                B=./b.sh
                for dep in "$A" "$B"; do
                  source "$dep"
                done
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [first, second])

        with ScriptProject() as project:
            first = project.write("a.sh", 'echo "a"\n')
            second = project.write("b.sh", 'echo "b"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                DEPS="./a.sh   ./b.sh"
                for dep in $DEPS; do
                  source "$dep"
                done
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [first, second])
        self.assertEqual([event.source_value for event in result.events], ["./a.sh", "./b.sh"])

    def test_scalar_for_loop_glob_sources_are_evaluated(self):
        with ScriptProject() as project:
            second = project.write("plugins/b.sh", 'echo "b"\n')
            first = project.write("plugins/a.sh", 'echo "a"\n')
            project.write("plugins/readme.txt", 'echo "not sourced"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                DEPS="./plugins/*.sh"
                for dep in $DEPS; do
                  source "$dep"
                done
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [first, second])
        self.assertEqual([event.source_value for event in result.events], ["./plugins/a.sh", "./plugins/b.sh"])

    def test_quoted_scalar_for_loop_preserves_single_word(self):
        with ScriptProject() as project:
            dep = project.write("deps dir#tag/a dep.sh", 'echo "special"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                DEP="./deps dir#tag/a dep.sh"
                for dep in "$DEP"; do
                  source "$dep"
                done
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep])
        self.assertEqual([event.source_value for event in result.events], ["./deps dir#tag/a dep.sh"])

    def test_empty_scalar_for_loop_sources_are_disabled(self):
        with ScriptProject() as project:
            entry = project.write("main.sh", textwrap.dedent("""\
                DEPS=""
                for dep in $DEPS; do source "$dep"; done
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual(result.events, ())
        self.assertEqual([disabled.source_site for disabled in result.disabled_sources], ['source "$dep"'])
        self.assertEqual(result.disabled_sources[0].condition, "for dep in $DEPS")

    def test_exact_glob_for_loop_sources_are_evaluated(self):
        with ScriptProject() as project:
            second = project.write("plugins/b.sh", 'echo "b"\n')
            first = project.write("plugins/a.sh", 'echo "a"\n')
            project.write("plugins/readme.txt", 'echo "not sourced"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                for dep in ./plugins/*.sh; do
                  source "$dep"
                done
                """))

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [first, second])
        self.assertEqual([event.source_value for event in result.events], ["./plugins/a.sh", "./plugins/b.sh"])

    def test_direct_glob_source_event_uses_matched_runtime_word(self):
        with ScriptProject() as project:
            dep = project.write("plugins/only.sh", 'echo "only"\n')
            entry = project.write("main.sh", 'source ./plugins/*.sh\n')

            result = SourceEvaluator().evaluate(entry)

        self.assertEqual([event.path for event in result.events], [dep])
        self.assertEqual([event.source_value for event in result.events], ["./plugins/only.sh"])

    def test_unsupported_for_loop_words_raise_structured_diagnostic(self):
        cases = {
            "command substitution": 'for dep in $(cat deps.txt); do source "$dep"; done\n',
            "unknown scalar": 'for dep in "$DEP"; do source "$dep"; done\n',
            "nondefault ifs scalar word list": 'IFS=:\nDEPS="./a.sh:./b.sh"\nfor dep in $DEPS; do source "$dep"; done\n',
            "unknown array": 'for dep in "${deps[@]}"; do source "$dep"; done\n',
            "unmatched glob": 'for dep in ./plugins/*.sh; do source "$dep"; done\n',
            "quoted glob": 'for dep in "./plugins/*.sh"; do source "$dep"; done\n',
            "globstar": 'for dep in ./plugins/**/*.sh; do source "$dep"; done\n',
            "brace": 'for dep in ./plugins/{a,b}.sh; do source "$dep"; done\n',
            "nullglob": 'shopt -s nullglob\nfor dep in ./plugins/*.sh; do source "$dep"; done\n',
        }

        for name, content in cases.items():
            with self.subTest(name=name), ScriptProject() as project:
                entry = project.write("main.sh", content)

                with self.assertRaisesRegex(NotImplementedError, "loop word") as cm:
                    SourceEvaluator().evaluate(entry)

            self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.loop-word-list")
            expected_line = 3 if name == "nondefault ifs scalar word list" else 2 if name == "nullglob" else 1
            self.assertEqual(cm.exception.diagnostic.location.line, expected_line)

    def test_circular_source_raises_recursion_error(self):
        with ScriptProject() as project:
            entry = project.write("a.sh", "source ./b.sh\n")
            project.write("b.sh", "source ./a.sh\n")

            with self.assertRaises(RecursionError):
                SourceEvaluator().evaluate(entry)


if __name__ == "__main__":
    unittest.main()
