from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from methods.regex.patterns import SOURCE_PATTERN, VARIABLE_ASSIGNMENT_PATTERN
from methods.regex.utilities import remove_comments
from methods.source_effects import (
    ArrayAssignment,
    Assignment,
    CaseArm,
    CaseBlock,
    CdCommand,
    ForLoop,
    IfBlock,
    IfBranch,
    RawCommand,
    ScriptIR,
    SetCommand,
    SourceLocation,
    SourceSite,
)
from methods.source_resolver import (
    contains_source_command,
    ends_unsupported_control_block,
    extract_heredoc_delimiters,
    is_unsupported_control_flow_source,
    is_heredoc_end,
    parse_shell_words,
    parse_shell_words_preserving_quotes,
    starts_unsupported_control_block,
    source_command_index,
    UnsupportedSourceError,
)
from methods.shell_line import get_commands

ARRAY_ASSIGNMENT_PATTERN = re.compile(r'^(?:declare\s+-a\s+)?([a-zA-Z_]\w*)=\((.*)\)$')
FOR_LOOP_PATTERN = re.compile(r'^\s*for\s+([a-zA-Z_]\w*)\s+in\s+(.+?)\s*;\s*do(?:\s*(.*))?$')
FOR_HEADER_PATTERN = re.compile(r'^\s*for\s+([a-zA-Z_]\w*)\s+in\s+(.+?)\s*$')
DO_LINE_PATTERN = re.compile(r'^\s*do\s*$')
INLINE_DONE_PATTERN = re.compile(r'^(.*?)(?:;\s*)?done\s*$')
IF_COMMAND_PATTERN = re.compile(r'^\s*if\s+(.+?)\s*$')
ELIF_COMMAND_PATTERN = re.compile(r'^\s*elif\s+(.+?)\s*$')
THEN_COMMAND_PATTERN = re.compile(r'^\s*then(?:\s+(.+?))?\s*$')
ELSE_COMMAND_PATTERN = re.compile(r'^\s*else(?:\s+(.+?))?\s*$')
FI_COMMAND_PATTERN = re.compile(r'^\s*fi\s*$')
ESAC_COMMAND_PATTERN = re.compile(r'^\s*esac\s*$')
CASE_TERMINATOR_COMMANDS = {
    "__MODASHC_CASE_TERM_END__": ";;",
    "__MODASHC_CASE_TERM_FALLTHROUGH__": ";&",
    "__MODASHC_CASE_TERM_FALLTHROUGH_TEST__": ";;&",
}


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
        control_depth = 0
        lines = content.splitlines()
        line_index = 0

        while line_index < len(lines):
            line_number = line_index + 1
            line = lines[line_index]
            if active_heredocs:
                if is_heredoc_end(line, active_heredocs[0]):
                    active_heredocs.pop(0)
                line_index += 1
                continue

            code_line = remove_comments(
                line,
                ['#'],
                exclusion_patterns=[r'\#\!.*'],
                escape_exclusions=False,
            )

            if_block, next_line_index = self._parse_if_block(script_path, line_number, code_line, lines, line_index)
            if if_block:
                nodes.append(if_block)
                line_index = next_line_index
                continue

            case_block, next_line_index = self._parse_case_block(script_path, line_number, code_line, lines, line_index)
            if case_block:
                nodes.append(case_block)
                line_index = next_line_index
                continue

            for_loop, next_line_index = self._parse_for_loop(script_path, line_number, code_line, lines, line_index)
            if for_loop:
                nodes.append(for_loop)
                line_index = next_line_index
                continue

            control_flow_source_ranges = self._control_flow_source_ranges(code_line, control_depth)
            nodes.extend(self._parse_line(script_path, line_number, code_line, control_flow_source_ranges))
            control_depth = self._next_control_depth(code_line, control_depth)
            active_heredocs.extend(extract_heredoc_delimiters(line))
            line_index += 1

        return ScriptIR(path=script_path, nodes=tuple(nodes))

    def _parse_line(self, script_path: Path, line_number: int, line: str, control_flow_source_ranges):
        nodes = []
        source_spans = []

        for match in SOURCE_PATTERN.finditer(line):
            if self._source_match_is_nested_shell(match):
                continue
            separator, command_name, arguments = match.groups()
            if not command_name:
                continue

            text = ''.join(part or '' for part in (separator, command_name, arguments)).strip()
            column = match.start(2) + 1
            is_control_flow = self._column_in_ranges(column, control_flow_source_ranges)
            nodes.append(SourceSite(
                location=SourceLocation(script_path, line_number, column),
                text=text,
                command_name=command_name.strip(),
                source_expression=(arguments or '').strip(),
                separator=(separator or '').strip(),
                is_control_flow=is_control_flow,
            ))
            source_spans.append(match.span())

        for command in get_commands(line):
            if not command:
                continue
            if any(command in line[start:end] for start, end in source_spans):
                continue
            if contains_source_command(command):
                nodes.append(self._fallback_source_site(
                    script_path,
                    line_number,
                    line,
                    command,
                    control_flow_source_ranges,
                ))
                continue
            nodes.append(self._command_node(script_path, line_number, line, command))

        return sorted(nodes, key=lambda node: node.location.column)

    @staticmethod
    def _source_match_is_nested_shell(match):
        return match.group(0).lstrip().startswith('$(')

    def _command_node(self, script_path: Path, line_number: int, line: str, command: str):
        location = SourceLocation(script_path, line_number, self._command_column(line, command))

        if array_assignment := self._array_assignment_node(location, command):
            return array_assignment

        if assignment := self._assignment_node(location, command):
            return assignment

        if cd_command := self._cd_node(location, command):
            return cd_command

        if set_command := self._set_node(location, command):
            return set_command

        return RawCommand(location=location, text=command)

    def _parse_if_block(self, script_path: Path, line_number: int, code_line: str, lines: list[str], line_index: int):
        commands = get_commands(code_line)
        if not commands or not IF_COMMAND_PATTERN.match(commands[0]):
            return None, line_index + 1

        branches = []
        current_condition = None
        current_keyword = None
        current_body = []
        saw_then = False
        nested_depth = 0
        index = line_index

        while index < len(lines):
            line = lines[index]
            code = remove_comments(
                line,
                ['#'],
                exclusion_patterns=[r'\#\!.*'],
                escape_exclusions=False,
            )

            for command in get_commands(code):
                stripped_command = command.strip()

                if nested_depth:
                    current_body.append((index + 1, command))
                    if IF_COMMAND_PATTERN.match(stripped_command):
                        nested_depth += 1
                    elif FI_COMMAND_PATTERN.match(stripped_command):
                        nested_depth -= 1
                    continue

                if match := IF_COMMAND_PATTERN.match(stripped_command):
                    if current_keyword is not None:
                        current_body.append((index + 1, command))
                        nested_depth = 1
                        continue
                    current_keyword = "if"
                    current_condition = match.group(1).strip()
                    saw_then = False
                    continue

                if match := ELIF_COMMAND_PATTERN.match(stripped_command):
                    if current_keyword is None:
                        return None, line_index + 1
                    branches.append(self._if_branch(script_path, current_keyword, current_condition, current_body))
                    current_keyword = "elif"
                    current_condition = match.group(1).strip()
                    current_body = []
                    saw_then = False
                    continue

                if match := THEN_COMMAND_PATTERN.match(stripped_command):
                    if current_keyword not in {"if", "elif"}:
                        return None, line_index + 1
                    saw_then = True
                    if match.group(1):
                        current_body.append((index + 1, match.group(1).strip()))
                    continue

                if match := ELSE_COMMAND_PATTERN.match(stripped_command):
                    if current_keyword is None:
                        return None, line_index + 1
                    branches.append(self._if_branch(script_path, current_keyword, current_condition, current_body))
                    current_keyword = "else"
                    current_condition = None
                    current_body = []
                    saw_then = True
                    if match.group(1):
                        current_body.append((index + 1, match.group(1).strip()))
                    continue

                if FI_COMMAND_PATTERN.match(stripped_command):
                    if current_keyword is None or (current_keyword in {"if", "elif"} and not saw_then):
                        return None, line_index + 1
                    branches.append(self._if_branch(script_path, current_keyword, current_condition, current_body))
                    column = self._command_column(code_line, "if")
                    return IfBlock(
                        location=SourceLocation(script_path, line_number, column),
                        text=code_line.strip(),
                        branches=tuple(branches),
                    ), index + 1

                if current_keyword is None or (current_keyword in {"if", "elif"} and not saw_then):
                    return None, line_index + 1
                current_body.append((index + 1, command))

            index += 1

        return None, line_index + 1

    def _if_branch(self, script_path: Path, keyword: str, condition: str | None, body_lines):
        return IfBranch(
            condition=condition,
            body=self._parse_loop_body(script_path, body_lines),
            keyword=keyword,
        )

    def _parse_case_block(self, script_path: Path, line_number: int, code_line: str, lines: list[str],
                          line_index: int):
        header = self._split_case_header(code_line)
        if not header:
            return None, line_index + 1

        subject, first_tail = header
        arms = []
        current_patterns = None
        current_body = []
        current_terminator = ";;"
        index = line_index

        while index < len(lines):
            if index == line_index:
                commands = self._case_commands(first_tail or "")
            else:
                code = remove_comments(
                    lines[index],
                    ['#'],
                    exclusion_patterns=[r'\#\!.*'],
                    escape_exclusions=False,
                )
                commands = self._case_commands(code)

            for command in commands:
                stripped_command = command.strip()

                if terminator := CASE_TERMINATOR_COMMANDS.get(stripped_command):
                    if current_patterns is None:
                        return None, line_index + 1
                    current_terminator = terminator
                    arms.append(self._case_arm(script_path, current_patterns, current_body, current_terminator))
                    current_patterns = None
                    current_body = []
                    current_terminator = ";;"
                    continue

                if ESAC_COMMAND_PATTERN.match(stripped_command):
                    if current_patterns is not None:
                        arms.append(self._case_arm(script_path, current_patterns, current_body, current_terminator))
                    if not arms:
                        return None, line_index + 1
                    column = self._command_column(code_line, "case")
                    return CaseBlock(
                        location=SourceLocation(script_path, line_number, column),
                        text=code_line.strip(),
                        subject=subject.strip(),
                        arms=tuple(arms),
                    ), index + 1

                arm = self._split_case_arm_header(stripped_command)
                if arm:
                    if current_patterns is not None:
                        return None, line_index + 1
                    patterns, body_command = arm
                    current_patterns = patterns
                    current_body = []
                    current_terminator = ";;"
                    if body_command:
                        current_body.append((index + 1, body_command))
                    continue

                if current_patterns is None:
                    return None, line_index + 1
                current_body.append((index + 1, command))

            index += 1

        return None, line_index + 1

    @staticmethod
    def _split_case_header(line: str):
        match = re.match(r'^\s*case(?:\s+|$)', line)
        if not match:
            return None

        rest = line[match.end():]
        for index in LineParserFrontend._unquoted_case_in_indices(rest):
            subject = rest[:index].strip()
            if not subject:
                continue

            try:
                subject_words = parse_shell_words_preserving_quotes(subject)
            except UnsupportedSourceError:
                continue
            if len(subject_words) != 1:
                continue

            return subject, rest[index + 2:].strip()

        return None

    @staticmethod
    def _unquoted_case_in_indices(text: str):
        in_single_quote = False
        in_double_quote = False
        escaped = False
        index = 0

        while index < len(text):
            char = text[index]
            if escaped:
                escaped = False
                index += 1
                continue

            if char == '\\' and not in_single_quote:
                escaped = True
                index += 1
                continue

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                index += 1
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                index += 1
                continue

            if not in_single_quote and not in_double_quote and text.startswith("in", index):
                previous_char = text[index - 1] if index > 0 else ""
                next_index = index + 2
                next_char = text[next_index] if next_index < len(text) else ""
                previous_boundary = index > 0 and previous_char.isspace()
                next_boundary = next_index == len(text) or next_char.isspace()
                if previous_boundary and next_boundary:
                    yield index

            index += 1

    def _case_arm(self, script_path: Path, patterns: tuple[str, ...], body_lines, terminator: str):
        return CaseArm(
            patterns=patterns,
            body=self._parse_loop_body(script_path, body_lines),
            terminator=terminator,
        )

    @staticmethod
    def _case_commands(line: str):
        return get_commands(LineParserFrontend._mark_case_terminators(line))

    @staticmethod
    def _mark_case_terminators(line: str):
        output = []
        in_single_quote = False
        in_double_quote = False
        escaped = False
        index = 0

        while index < len(line):
            char = line[index]
            if escaped:
                output.append(char)
                escaped = False
                index += 1
                continue

            if char == '\\' and not in_single_quote:
                output.append(char)
                escaped = True
                index += 1
                continue

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                output.append(char)
                index += 1
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                output.append(char)
                index += 1
                continue

            if not in_single_quote and not in_double_quote:
                if line.startswith(";;&", index):
                    output.append("; __MODASHC_CASE_TERM_FALLTHROUGH_TEST__ ;")
                    index += 3
                    continue
                if line.startswith(";&", index):
                    output.append("; __MODASHC_CASE_TERM_FALLTHROUGH__ ;")
                    index += 2
                    continue
                if line.startswith(";;", index):
                    output.append("; __MODASHC_CASE_TERM_END__ ;")
                    index += 2
                    continue

            output.append(char)
            index += 1

        return ''.join(output)

    @staticmethod
    def _split_case_arm_header(command: str):
        pattern_end = LineParserFrontend._unquoted_index(command, ")")
        if pattern_end <= 0:
            return None

        pattern_text = command[:pattern_end].strip()
        if pattern_text.startswith("("):
            pattern_text = pattern_text[1:].strip()
        if not pattern_text:
            return None

        patterns = tuple(part.strip() for part in LineParserFrontend._split_unquoted(pattern_text, "|") if part.strip())
        if not patterns:
            return None
        return patterns, command[pattern_end + 1:].strip()

    @staticmethod
    def _split_unquoted(text: str, separator: str):
        parts = []
        current = []
        in_single_quote = False
        in_double_quote = False
        escaped = False

        for char in text:
            if escaped:
                current.append(char)
                escaped = False
                continue

            if char == '\\' and not in_single_quote:
                current.append(char)
                escaped = True
                continue

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current.append(char)
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current.append(char)
                continue

            if char == separator and not in_single_quote and not in_double_quote:
                parts.append(''.join(current))
                current = []
                continue

            current.append(char)

        parts.append(''.join(current))
        return parts

    @staticmethod
    def _unquoted_index(text: str, needle: str):
        in_single_quote = False
        in_double_quote = False
        escaped = False

        for index, char in enumerate(text):
            if escaped:
                escaped = False
                continue

            if char == '\\' and not in_single_quote:
                escaped = True
                continue

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                continue

            if char == needle and not in_single_quote and not in_double_quote:
                return index

        return -1

    def _parse_for_loop(self, script_path: Path, line_number: int, code_line: str, lines: list[str], line_index: int):
        match = FOR_LOOP_PATTERN.match(code_line)
        do_line_index = line_index
        if match:
            variable, words_text, inline_body = match.groups()
        else:
            match = FOR_HEADER_PATTERN.match(code_line)
            if not match or line_index + 1 >= len(lines):
                return None, line_index + 1

            do_line_index = line_index + 1
            do_code_line = remove_comments(
                lines[do_line_index],
                ['#'],
                exclusion_patterns=[r'\#\!.*'],
                escape_exclusions=False,
            )
            do_match = DO_LINE_PATTERN.match(do_code_line)
            if not do_match:
                return None, line_index + 1

            variable, words_text = match.groups()
            inline_body = ""

        if inline_body is None:
            inline_body = ""

        if inline_body.strip() == "":
            body_start_index = do_line_index + 1
        else:
            body_start_index = do_line_index

        if body_start_index <= line_index:
            body_start_index = line_index + 1

        body_lines = []
        next_line_index = body_start_index

        if inline_body is not None and inline_body.strip():
            done_match = INLINE_DONE_PATTERN.match(inline_body.strip())
            if not done_match:
                return None, line_index + 1
            body_lines.append((do_line_index + 1, done_match.group(1).strip()))
            next_line_index = do_line_index + 1
        else:
            body_index = body_start_index
            active_heredocs = []
            control_depth = 0
            while body_index < len(lines):
                body_line_number = body_index + 1
                body_line = lines[body_index]

                if active_heredocs:
                    body_lines.append((body_line_number, body_line))
                    if is_heredoc_end(body_line, active_heredocs[0]):
                        active_heredocs.pop(0)
                    body_index += 1
                    continue

                body_code_line = remove_comments(
                    body_line,
                    ['#'],
                    exclusion_patterns=[r'\#\!.*'],
                    escape_exclusions=False,
                )
                stripped_body_line = body_code_line.strip()
                if stripped_body_line == "done" and control_depth == 0:
                    next_line_index = body_index + 1
                    break

                body_lines.append((body_line_number, body_code_line))
                active_heredocs.extend(extract_heredoc_delimiters(body_line))
                control_depth = self._next_control_depth(body_code_line, control_depth)
                body_index += 1
            else:
                return None, line_index + 1

        loop_words, is_exact = self._parse_loop_words(words_text)
        body = self._parse_loop_body(script_path, body_lines)
        column = self._command_column(code_line, "for")

        return ForLoop(
            location=SourceLocation(script_path, line_number, column),
            text=code_line.strip(),
            variable=variable,
            words=loop_words,
            body=body,
            words_text=words_text.strip(),
            is_exact=is_exact,
        ), next_line_index

    @staticmethod
    def _parse_loop_words(words_text: str):
        try:
            return tuple(parse_shell_words(words_text)), True
        except UnsupportedSourceError:
            return (), False

    def _parse_loop_body(self, script_path: Path, body_lines):
        nodes = []
        control_depth = 0
        active_heredocs = []

        for line_number, code_line in body_lines:
            if active_heredocs:
                if is_heredoc_end(code_line, active_heredocs[0]):
                    active_heredocs.pop(0)
                continue

            control_flow_source_ranges = self._control_flow_source_ranges(code_line, control_depth)
            nodes.extend(self._parse_line(script_path, line_number, code_line, control_flow_source_ranges))
            control_depth = self._next_control_depth(code_line, control_depth)
            active_heredocs.extend(extract_heredoc_delimiters(code_line))

        return tuple(nodes)

    @staticmethod
    def _command_column(line: str, command: str):
        column = line.find(command)
        return 1 if column < 0 else column + 1

    @staticmethod
    def _array_assignment_node(location: SourceLocation, command: str):
        match = ARRAY_ASSIGNMENT_PATTERN.match(command)
        if not match:
            return None

        name, values_text = match.groups()
        is_exact = True
        try:
            values = tuple(parse_shell_words(values_text))
        except UnsupportedSourceError:
            values = ()
            is_exact = False

        return ArrayAssignment(
            location=location,
            text=command,
            name=name,
            values=values,
            is_exact=is_exact,
        )

    @staticmethod
    def _assignment_node(location: SourceLocation, command: str):
        match = VARIABLE_ASSIGNMENT_PATTERN.match(command)
        if not match:
            return None

        prefix, name, operator, value = match.groups()
        if '(' in operator or command.strip().startswith(f"{name}=("):
            return None

        return Assignment(
            location=location,
            text=command,
            name=name,
            value=value.strip(),
            prefix=prefix.strip(),
        )

    @staticmethod
    def _cd_node(location: SourceLocation, command: str):
        if not re.match(r'^cd(?:\s|$)', command):
            return None

        return CdCommand(
            location=location,
            text=command,
            path_expression=command[2:].strip(),
        )

    @staticmethod
    def _set_node(location: SourceLocation, command: str):
        if not re.match(r'^set(?:\s|$)', command):
            return None

        try:
            words = parse_shell_words(command)
        except UnsupportedSourceError:
            words = command.split()

        return SetCommand(
            location=location,
            text=command,
            arguments=tuple(words[1:]),
        )

    @staticmethod
    def _fallback_source_site(script_path: Path, line_number: int, line: str, command: str,
                              control_flow_source_ranges):
        words = command.split()
        source_index = source_command_index(command)
        command_name = words[source_index] if source_index is not None and source_index < len(words) else "source"
        command_offset = line.find(command)
        source_offset = command.find(command_name)
        expression = command[source_offset + len(command_name):].strip() if source_offset >= 0 else ""
        column = command_offset + source_offset + 1 if command_offset >= 0 and source_offset >= 0 else 1
        is_control_flow = LineParserFrontend._column_in_ranges(max(column, 1), control_flow_source_ranges)

        return SourceSite(
            location=SourceLocation(script_path, line_number, max(column, 1)),
            text=command,
            command_name=command_name,
            source_expression=expression,
            is_control_flow=is_control_flow,
        )

    @staticmethod
    def _control_flow_source_ranges(line: str, control_depth: int):
        ranges = []
        simulated_depth = control_depth
        search_start = 0

        for command in get_commands(line):
            command_start = line.find(command, search_start)
            if command_start < 0:
                command_start = search_start
            command_end = command_start + len(command)

            if contains_source_command(command) and is_unsupported_control_flow_source(command, simulated_depth):
                ranges.append((command_start + 1, command_end + 1))

            if starts_unsupported_control_block(command):
                simulated_depth += 1
            elif ends_unsupported_control_block(command):
                simulated_depth = max(0, simulated_depth - 1)

            search_start = command_end

        return tuple(ranges)

    @staticmethod
    def _next_control_depth(line: str, control_depth: int):
        for command in get_commands(line):
            if starts_unsupported_control_block(command):
                control_depth += 1
            elif ends_unsupported_control_block(command):
                control_depth = max(0, control_depth - 1)
        return control_depth

    @staticmethod
    def _column_in_ranges(column: int, ranges):
        return any(start <= column < end for start, end in ranges)
