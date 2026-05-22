from __future__ import annotations

from pathlib import Path
from typing import Protocol

from methods.regex.patterns import SOURCE_PATTERN
from methods.regex.utilities import remove_comments
from methods.source_effects import RawCommand, ScriptIR, SourceLocation, SourceSite
from methods.source_resolver import extract_heredoc_delimiters, is_heredoc_end
from methods.shell_line import get_commands


class ParserFrontend(Protocol):
    def parse(self, path: Path | str, content: str) -> ScriptIR:
        ...


class LineParserFrontend:
    """Current parser frontend backed by the existing line-level splitter.

    This is a compatibility frontend, not the final Bash parser. Its output is
    the stable contract that a future real parser adapter must preserve.
    """

    def parse(self, path: Path | str, content: str) -> ScriptIR:
        script_path = Path(path)
        nodes = []
        active_heredocs = []

        for line_number, line in enumerate(content.splitlines(), start=1):
            if active_heredocs:
                if is_heredoc_end(line, active_heredocs[0]):
                    active_heredocs.pop(0)
                continue

            code_line = remove_comments(
                line,
                ['#'],
                exclusion_patterns=[r'\#\!.*'],
                escape_exclusions=False,
            )
            nodes.extend(self._parse_line(script_path, line_number, code_line))
            active_heredocs.extend(extract_heredoc_delimiters(line))

        return ScriptIR(path=script_path, nodes=tuple(nodes))

    def _parse_line(self, script_path: Path, line_number: int, line: str):
        nodes = []
        source_spans = []

        for match in SOURCE_PATTERN.finditer(line):
            separator, command_name, arguments = match.groups()
            if not command_name:
                continue

            text = ''.join(part or '' for part in (separator, command_name, arguments)).strip()
            column = match.start(2) + 1
            nodes.append(SourceSite(
                location=SourceLocation(script_path, line_number, column),
                text=text,
                command_name=command_name.strip(),
                source_expression=(arguments or '').strip(),
                separator=(separator or '').strip(),
            ))
            source_spans.append(match.span())

        for command in get_commands(line):
            if not command or any(command in line[start:end] for start, end in source_spans):
                continue
            column = line.find(command) + 1
            nodes.append(RawCommand(
                location=SourceLocation(script_path, line_number, max(column, 1)),
                text=command,
            ))

        return sorted(nodes, key=lambda node: node.location.column)
