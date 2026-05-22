import textwrap
import unittest
from pathlib import Path

from methods.source_effects import RawCommand, SourceSite
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
        source_sites = [node for node in ir.nodes if isinstance(node, SourceSite)]

        self.assertEqual([node.text for node in raw_commands], ["cd subdir", "echo ready"])
        self.assertEqual([node.source_expression for node in source_sites], ["./dep.sh"])
        self.assertEqual([type(node) for node in ir.nodes], [RawCommand, RawCommand, SourceSite])


if __name__ == "__main__":
    unittest.main()
