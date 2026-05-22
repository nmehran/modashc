import textwrap
import unittest

from methods.source_effects import ExecutionModel, OccurrenceModel
from methods.source_evaluator import SourceEvaluator
from methods.source_events import evaluate_sources
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
        self.assertEqual(event.source_expression, '"./deps/feature.sh"')
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

    def test_evaluator_matches_current_event_bridge_for_supported_subset(self):
        with ScriptProject() as project:
            project.write("nested/dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                ROOT=./nested
                cd "$ROOT"
                source ./dep.sh
                COMMAND="source ./dep.sh"
                eval "$COMMAND"
                """))

            current = evaluate_sources(entry)
            evaluated = SourceEvaluator().evaluate(entry)

        self.assertEqual(
            [(event.path, event.source_site) for event in evaluated.events],
            [(event.path, event.source_site) for event in current.events],
        )

    def test_unknown_array_source_raises_structured_diagnostic(self):
        with ScriptProject() as project:
            entry = project.write("main.sh", 'source "${deps[0]}"\n')

            with self.assertRaisesRegex(NotImplementedError, "array source") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.array-index")
        self.assertEqual(cm.exception.diagnostic.location.line, 1)
        self.assertEqual(cm.exception.diagnostic.fragment, 'source "${deps[0]}"')

    def test_control_flow_source_rejects_even_when_path_is_static(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                if [[ -f ./dep.sh ]]; then
                  source ./dep.sh
                fi
                """))

            with self.assertRaisesRegex(NotImplementedError, "control flow") as cm:
                SourceEvaluator().evaluate(entry)

        self.assertEqual(cm.exception.diagnostic.code, "unsupported.source.control-flow")
        self.assertEqual(cm.exception.diagnostic.location.line, 2)
        self.assertEqual(cm.exception.diagnostic.fragment, "source ./dep.sh")

    def test_circular_source_raises_recursion_error(self):
        with ScriptProject() as project:
            entry = project.write("a.sh", "source ./b.sh\n")
            project.write("b.sh", "source ./a.sh\n")

            with self.assertRaises(RecursionError):
                SourceEvaluator().evaluate(entry)


if __name__ == "__main__":
    unittest.main()
