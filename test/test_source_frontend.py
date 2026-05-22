import textwrap
import unittest
from pathlib import Path

from methods.source_effects import ArrayAssignment, Assignment, CdCommand, ForLoop, RawCommand, SetCommand, SourceSite
from methods.source_frontend import LineParserFrontend


class LineParserFrontendTestCase(unittest.TestCase):
    def parse(self, content: str):
        return LineParserFrontend().parse(Path("main.sh"), textwrap.dedent(content))

    def test_parses_static_source_sites_with_locations(self):
        ir = self.parse("""\
            source ./dep.sh
            . ./dot.sh
            source "./dir with spaces/dep.sh"
            source ./dir#tag/dep.sh
            source ./config
            echo done
            """)

        source_sites = ir.source_sites

        self.assertEqual([site.source_expression for site in source_sites], [
            "./dep.sh",
            "./dot.sh",
            '"./dir with spaces/dep.sh"',
            "./dir#tag/dep.sh",
            "./config",
        ])
        self.assertEqual([site.command_name for site in source_sites], ["source", ".", "source", "source", "source"])
        self.assertEqual([site.location.line for site in source_sites], [1, 2, 3, 4, 5])
        self.assertEqual([site.location.column for site in source_sites], [1, 1, 1, 1, 1])
        self.assertEqual([site.is_control_flow for site in source_sites], [False, False, False, False, False])

        raw_commands = [node for node in ir.nodes if isinstance(node, RawCommand)]
        self.assertEqual([node.text for node in raw_commands], ["echo done"])

    def test_preserves_multiple_source_sites_on_one_line(self):
        ir = self.parse('source ./a.sh && source "$NEXT" || echo missing\n')

        self.assertEqual([site.text for site in ir.source_sites], [
            "source ./a.sh",
            '&& source "$NEXT"',
        ])
        self.assertEqual([site.separator for site in ir.source_sites], ["", "&&"])
        self.assertEqual([site.source_expression for site in ir.source_sites], ["./a.sh", '"$NEXT"'])

    def test_ignores_source_text_inside_comments_quotes_and_heredocs(self):
        ir = self.parse("""\
            echo "source ./quoted.sh"
            # source ./commented.sh
            cat <<EOF
            source ./heredoc.sh
            EOF
            source ./real.sh
            """)

        self.assertEqual([site.source_expression for site in ir.source_sites], ["./real.sh"])

    def test_keeps_indented_function_body_source_location(self):
        ir = self.parse("""\
            helper() {
              source ./runtime.sh
            }
            """)

        self.assertEqual(len(ir.source_sites), 1)
        site = ir.source_sites[0]
        self.assertEqual(site.source_expression, "./runtime.sh")
        self.assertEqual(site.location.line, 2)
        self.assertEqual(site.location.column, 3)

    def test_emits_raw_commands_for_non_source_fragments(self):
        ir = self.parse('cd subdir && echo ready && source ./dep.sh\n')

        raw_commands = [node for node in ir.nodes if isinstance(node, RawCommand)]
        cd_commands = [node for node in ir.nodes if isinstance(node, CdCommand)]
        source_sites = [node for node in ir.nodes if isinstance(node, SourceSite)]

        self.assertEqual([node.path_expression for node in cd_commands], ["subdir"])
        self.assertEqual([node.text for node in raw_commands], ["echo ready"])
        self.assertEqual([node.source_expression for node in source_sites], ["./dep.sh"])
        self.assertEqual([type(node) for node in ir.nodes], [CdCommand, RawCommand, SourceSite])

    def test_emits_stateful_nodes_for_current_evaluator_inputs(self):
        ir = self.parse("""\
            ROOT="./dir with spaces"
            cd "$ROOT"
            set +u -e
            export DEP=./dep.sh
            deps=(./base.sh "./feature path.sh")
            echo done
            """)

        self.assertEqual([type(node) for node in ir.nodes], [
            Assignment,
            CdCommand,
            SetCommand,
            Assignment,
            ArrayAssignment,
            RawCommand,
        ])

        first_assignment = ir.nodes[0]
        self.assertEqual(first_assignment.name, "ROOT")
        self.assertEqual(first_assignment.value, '"./dir with spaces"')

        set_command = ir.nodes[2]
        self.assertEqual(set_command.arguments, ("+u", "-e"))

        export_assignment = ir.nodes[3]
        self.assertEqual(export_assignment.prefix, "export")
        self.assertEqual(export_assignment.name, "DEP")
        self.assertEqual(export_assignment.value, "./dep.sh")

        array_assignment = ir.nodes[4]
        self.assertEqual(array_assignment.name, "deps")
        self.assertEqual(array_assignment.values, ("./base.sh", "./feature path.sh"))
        self.assertTrue(array_assignment.is_exact)

    def test_marks_unparseable_array_assignment_as_not_exact(self):
        ir = self.parse('deps=("./unterminated)\n')

        self.assertEqual(len(ir.nodes), 1)
        array_assignment = ir.nodes[0]
        self.assertIsInstance(array_assignment, ArrayAssignment)
        self.assertEqual(array_assignment.name, "deps")
        self.assertEqual(array_assignment.values, ())
        self.assertFalse(array_assignment.is_exact)

    def test_finds_source_sites_inside_future_control_flow_fixtures(self):
        ir = self.parse("""\
            for file in ./plugins/*.sh; do source "$file"; done
            if [[ -f ./local.sh ]]; then
              source ./local.sh
            fi
            case "$ENV" in
              prod) source ./prod.sh ;;
              dev) source ./dev.sh ;;
            esac
            deps=(./base.sh ./feature.sh)
            source "${deps[0]}"
            """)

        self.assertEqual([site.source_expression for site in ir.source_sites], [
            '"$file"',
            "./local.sh",
            "./prod.sh",
            "./dev.sh",
            '"${deps[0]}"',
        ])
        self.assertEqual([site.location.line for site in ir.source_sites], [1, 3, 6, 7, 10])
        self.assertEqual([site.is_control_flow for site in ir.source_sites], [False, True, True, True, False])

    def test_control_flow_marking_is_source_site_specific_on_mixed_lines(self):
        ir = self.parse('source ./always.sh; if true; then source ./branch.sh; fi\n')

        self.assertEqual([site.source_expression for site in ir.source_sites], ["./always.sh", "./branch.sh"])
        self.assertEqual([site.is_control_flow for site in ir.source_sites], [False, True])

    def test_parses_simple_multiline_for_loop_node(self):
        ir = self.parse("""\
            for dep in ./a.sh "./b path.sh"; do
              echo "$dep"
              source "$dep"
            done
            """)

        self.assertEqual(len(ir.nodes), 1)
        loop = ir.nodes[0]
        self.assertIsInstance(loop, ForLoop)
        self.assertEqual(loop.variable, "dep")
        self.assertEqual(loop.words, ("./a.sh", "./b path.sh"))
        self.assertTrue(loop.is_exact)
        self.assertEqual([type(node) for node in loop.body], [RawCommand, SourceSite])
        self.assertEqual(loop.body[1].location.line, 3)
        self.assertEqual(loop.body[1].source_expression, '"$dep"')
        self.assertFalse(loop.body[1].is_control_flow)

    def test_parses_newline_do_for_loop_node(self):
        ir = self.parse("""\
            for dep in ./a.sh ./b.sh
            do
              source "$dep"
            done
            """)

        self.assertEqual(len(ir.nodes), 1)
        loop = ir.nodes[0]
        self.assertIsInstance(loop, ForLoop)
        self.assertEqual(loop.variable, "dep")
        self.assertEqual(loop.words, ("./a.sh", "./b.sh"))
        self.assertEqual(loop.body[0].location.line, 3)
        self.assertEqual(loop.body[0].source_expression, '"$dep"')

    def test_loop_body_ignores_source_text_inside_heredoc(self):
        ir = self.parse("""\
            for dep in ./a.sh; do
              cat <<EOF
              source "$dep"
            EOF
              source "$dep"
            done
            """)

        self.assertEqual([site.location.line for site in ir.source_sites], [5])
        self.assertEqual([site.source_expression for site in ir.source_sites], ['"$dep"'])

    def test_parses_simple_inline_for_loop_node(self):
        ir = self.parse('for dep in ./a.sh ./b.sh; do source "$dep"; done\n')

        self.assertEqual(len(ir.nodes), 1)
        loop = ir.nodes[0]
        self.assertIsInstance(loop, ForLoop)
        self.assertEqual(loop.variable, "dep")
        self.assertEqual(loop.words, ("./a.sh", "./b.sh"))
        self.assertEqual([site.source_expression for site in loop.body if isinstance(site, SourceSite)], ['"$dep"'])

    def test_marks_unparseable_for_loop_words_as_not_exact(self):
        ir = self.parse('for dep in "./unterminated; do source "$dep"; done\n')

        self.assertEqual(len(ir.nodes), 1)
        loop = ir.nodes[0]
        self.assertIsInstance(loop, ForLoop)
        self.assertEqual(loop.words, ())
        self.assertFalse(loop.is_exact)


if __name__ == "__main__":
    unittest.main()
