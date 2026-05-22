import textwrap
import unittest

from methods.source_effects import ExecutionModel, OccurrenceModel
from methods.source_events import evaluate_sources
from test.support import ScriptProject


class SourceEventsTestCase(unittest.TestCase):
    def test_static_source_event_has_location_and_execution_model(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", 'source ./dep.sh\necho "main"\n')

            result = evaluate_sources(entry)

        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.path, dep)
        self.assertEqual(event.location.line, 1)
        self.assertEqual(event.location.column, 1)
        self.assertEqual(event.source_expression, "./dep.sh")
        self.assertEqual(event.source_site, "source ./dep.sh")
        self.assertEqual(event.execution_model, ExecutionModel.PARENT_SOURCE)
        self.assertEqual(event.occurrence_model, OccurrenceModel.ONCE)

    def test_duplicate_source_events_are_marked_repeated(self):
        with ScriptProject() as project:
            project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                source ./dep.sh
                source ./dep.sh
                """))

            result = evaluate_sources(entry)

        self.assertEqual(len(result.events), 2)
        self.assertEqual([event.location.line for event in result.events], [1, 2])
        self.assertEqual({event.occurrence_model for event in result.events}, {OccurrenceModel.REPEATED})

    def test_nested_source_events_are_emitted_in_execution_order(self):
        with ScriptProject() as project:
            a = project.write("a.sh", 'source ./b.sh\necho "a"\n')
            b = project.write("b.sh", 'echo "b"\n')
            entry = project.write("main.sh", 'source ./a.sh\necho "main"\n')

            result = evaluate_sources(entry)

        self.assertEqual([event.path for event in result.events], [a, b])
        self.assertEqual([event.source_site for event in result.events], ["source ./a.sh", "source ./b.sh"])

    def test_function_scoped_source_event_preserves_indented_location(self):
        with ScriptProject() as project:
            runtime = project.write("runtime.sh", 'echo "runtime"\n')
            entry = project.write("main.sh", textwrap.dedent("""\
                helper() {
                  source ./runtime.sh
                }
                helper
                """))

            result = evaluate_sources(entry)

        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.path, runtime)
        self.assertEqual(event.location.line, 2)
        self.assertEqual(event.location.column, 3)

    def test_eval_source_event_uses_command_site_and_resolved_source_expression(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", 'COMMAND="source ./dep.sh"\neval "$COMMAND"\n')

            result = evaluate_sources(entry)

        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.path, dep)
        self.assertEqual(event.location.line, 2)
        self.assertEqual(event.location.column, 1)
        self.assertEqual(event.source_site, 'eval "$COMMAND"')
        self.assertEqual(event.source_expression, "./dep.sh")

    def test_child_shell_source_event_is_context_only_model(self):
        with ScriptProject() as project:
            dep = project.write("dep.sh", 'echo "dep"\n')
            entry = project.write("main.sh", 'bash -c "source ./dep.sh"\necho "main"\n')

            result = evaluate_sources(entry, mode="context")

        self.assertEqual(len(result.events), 1)
        event = result.events[0]
        self.assertEqual(event.path, dep)
        self.assertEqual(event.execution_model, ExecutionModel.CHILD_SHELL)
        self.assertEqual(event.source_site, 'bash -c "source ./dep.sh"')


if __name__ == "__main__":
    unittest.main()
