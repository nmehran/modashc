import os
import re
from collections import defaultdict

from methods.regex.patterns import SOURCE_PATTERN
from methods.shell_line import get_commands
from methods.source_evaluator import SourceEvaluator
from methods.source_resolver import (
    ResolvedSource,
    UnsupportedSourceError,
    contains_source_command,
    contains_nested_source_command,
    extract_heredoc_delimiters,
    is_heredoc_end,
)
from methods.source_supplements import load_source_supplement
from methods.sources import validate_path

SET_SHEBANG = "#!/bin/bash"


def shell_quote(value: str):
    return "'" + value.replace("'", "'\"'\"'") + "'"


def replace_runtime_source_references(line: str, filepath: str, entry_point: str):
    bash_source = shell_quote(os.path.abspath(filepath))
    entry_source = shell_quote(os.path.abspath(entry_point))

    replacements = {
        '"${BASH_SOURCE[0]}"': bash_source,
        '"${BASH_SOURCE}"': bash_source,
        '"$BASH_SOURCE"': bash_source,
        '${BASH_SOURCE[0]}': bash_source,
        '${BASH_SOURCE}': bash_source,
        '$BASH_SOURCE': bash_source,
        '"${0}"': entry_source,
        '"$0"': entry_source,
        '${0}': entry_source,
    }

    for old, new in replacements.items():
        line = line.replace(old, new)

    return re.sub(r'\$0(?![0-9])', entry_source, line)


def indent_block(content: str, prefix: str):
    lines = content.splitlines()
    return '\n'.join(f"{prefix}{line}" if line else line for line in lines)


def construct_file_separator(filepath, entry_point, delimiter="-", length=120):
    # Get the basename of the file for the header
    filename = os.path.relpath(filepath, start=os.path.dirname(entry_point))

    # Create the header with the filename centered
    header_line = f"{filename}".center(length - 1, delimiter)

    # Create the full separator block
    line_block = f"#{delimiter * (length - 1)}\n"
    separator = f"{line_block}#{header_line}\n{line_block}\n"

    return separator


def unique_paths(paths: list[str]):
    unique = []
    seen = set()
    for path in paths:
        resolved = os.path.abspath(path)
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def format_context_path(filepath: str, entry_point: str):
    entry_directory = os.path.abspath(os.path.dirname(entry_point))
    filepath = os.path.abspath(filepath)

    try:
        relative_path = os.path.relpath(filepath, start=entry_directory)
    except ValueError:
        return filepath

    if relative_path == os.pardir or relative_path.startswith(os.pardir + os.sep):
        return filepath
    return relative_path


def construct_context_source_comment(source_declaration, entry_point: str):
    if source_declaration.execution_model == "parent-source":
        source_label = f"source {source_declaration.source_expression.strip()}"
        suffix = ""
    else:
        source_label = source_declaration.source_site.strip()
        suffix = f" ({source_declaration.execution_model})"

    if source_declaration.occurrence_model in {"conditional", "mutually-exclusive"}:
        condition = f": {source_declaration.condition}" if source_declaration.condition else ""
        suffix = f"{suffix} ({source_declaration.occurrence_model}{condition})"

    return f"# modashc: {source_label} -> {format_context_path(source_declaration.path, entry_point)}{suffix}"


def read_file(filepath):
    with open(filepath, 'r') as file:
        return file.read()


def write_output(filename, content):
    with open(filename, 'w') as file:
        file.write(content)


def render_source_block(filepath: str, render_source, indent: str):
    rendered_source = indent_block(render_source(filepath), indent)
    return f"{{\n{rendered_source}\n{indent}}}"


def source_values_are_path_ambiguous(source_declarations):
    paths_by_source_value = defaultdict(set)
    for source_declaration in source_declarations:
        source_value = source_declaration.source_value or source_declaration.path
        paths_by_source_value[source_value].add(source_declaration.path)

    return any(len(paths) > 1 for paths in paths_by_source_value.values())


def render_source_dispatch(source_expression: str, source_declarations, render_source, indent: str):
    use_resolved_path = source_values_are_path_ambiguous(source_declarations)
    dispatch_expression = (
        f'"$(realpath -- {source_expression.strip()})"'
        if use_resolved_path
        else source_expression.strip()
    )
    output = [f"case {dispatch_expression} in"]
    seen_patterns = set()

    for source_declaration in source_declarations:
        if use_resolved_path:
            pattern = source_declaration.path
        else:
            pattern = source_declaration.source_value or source_declaration.path
        if pattern in seen_patterns:
            continue
        seen_patterns.add(pattern)
        rendered_source = (
            f"{indent}    :"
            if source_declaration.replacement_kind == "noop-source"
            else indent_block(render_source(source_declaration.path), f"{indent}    ")
        )
        output.extend([
            f"{indent}  {shell_quote(pattern)})",
            f"{indent}    {{",
            rendered_source,
            f"{indent}    }}",
            f"{indent}    ;;",
        ])

    output.extend([
        f"{indent}  *)",
        f"{indent}    echo {shell_quote(f'modashc: unresolved source {source_expression.strip()}')} >&2",
        f"{indent}    exit 1",
        f"{indent}    ;;",
        f"{indent}esac",
    ])
    return '\n'.join(output)


def render_retained_source_dispatch(source_declarations, render_source, indent: str):
    output = ["{"]
    seen_arguments = set()
    branch_keyword = "if"

    for source_declaration in source_declarations:
        argument = source_declaration.source_value or source_declaration.path
        if argument in seen_arguments:
            continue
        seen_arguments.add(argument)

        rendered_source = indent_block(render_source(source_declaration.path), f"{indent}      ")
        if not rendered_source:
            rendered_source = f"{indent}      :"
        quoted_argument = shell_quote(argument)
        output.extend([
            (
                f"{indent}  {branch_keyword} [[ $# -eq 1 && "
                f"( ${{1-}} == {quoted_argument} || "
                f"$(realpath -- \"${{1-}}\" 2>/dev/null) == {quoted_argument} ) ]]; then"
            ),
            f"{indent}    {{",
            rendered_source,
            f"{indent}    }}",
        ])
        branch_keyword = "elif"

    output.extend([
        f"{indent}  else",
        f"{indent}    false",
        f"{indent}  fi",
        f"{indent}}}",
    ])
    return '\n'.join(output)


def find_unquoted_substring(text: str, needle: str, start: int = 0):
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

        if index >= start and not in_single_quote and not in_double_quote and text.startswith(needle, index):
            return index

    return -1


def replace_command_source_sites(line: str, source_declarations, render_source):
    search_start = 0

    for source_declaration in source_declarations:
        source_site = source_declaration.source_site.strip()
        source_index = find_unquoted_substring(line, source_site, search_start)
        if source_index < 0:
            raise ValueError(f"Could not replace resolved source command: {source_site}")

        indent = re.match(r'\s*', line[:source_index]).group(0)
        if source_declaration.replacement_kind == "noop-command":
            replacement = ":"
        else:
            replacement = render_source_block(source_declaration.path, render_source, indent)
        line = line[:source_index] + replacement + line[source_index + len(source_site):]
        search_start = source_index + len(replacement)

    return line


def source_site_for_match(match):
    _, command_name, arguments = match.groups()
    return f"{command_name.strip()} {(arguments or '').strip()}".strip()


def source_column_for_match(match):
    return match.start(2) + 1


def pop_source_declarations_for_match(match, declarations_by_column, group_fallback=True):
    grouped_declarations = declarations_by_column.pop(source_column_for_match(match), [])
    if grouped_declarations:
        return grouped_declarations

    match_source_site = source_site_for_match(match)
    for source_column, declarations in list(declarations_by_column.items()):
        if declarations and declarations[0].source_site == match_source_site:
            if not group_fallback:
                grouped_declarations = [declarations.pop(0)]
                if not declarations:
                    declarations_by_column.pop(source_column)
                return grouped_declarations
            return declarations_by_column.pop(source_column)

    return []


def group_source_declarations_by_column(source_declarations):
    declarations_by_column = defaultdict(list)
    fallback_declarations = []

    for source_declaration in source_declarations:
        if source_declaration.source_column is None:
            fallback_declarations.append(source_declaration)
        else:
            declarations_by_column[source_declaration.source_column].append(source_declaration)

    return declarations_by_column, fallback_declarations


def render_source_site_replacement(separator: str, declarations, render_source, indent: str):
    retained_declarations = [
        declaration for declaration in declarations
        if declaration.replacement_kind == "retained-source"
    ]
    if retained_declarations:
        return f"{separator}{render_retained_source_dispatch(retained_declarations, render_source, indent)}"

    declaration = declarations[0]
    if declaration.replacement_kind == "noop-source":
        return f"{separator}:"

    unique_paths = {source_declaration.path for source_declaration in declarations}
    if len(declarations) > 1 and len(unique_paths) > 1:
        return f"{separator}{render_source_dispatch(declaration.source_expression, declarations, render_source, indent)}"

    rendered_source = indent_block(render_source(declaration.path), indent)
    return f"{separator}{{\n{rendered_source}\n{indent}}}"


def replace_source_site_substrings(line: str, source_declarations, render_source):
    search_start = 0
    index = 0

    while index < len(source_declarations):
        declaration = source_declarations[index]
        source_site = declaration.source_site.strip()
        source_index = find_unquoted_substring(line, source_site, search_start)
        if source_index < 0:
            raise ValueError(f"Could not replace resolved source declaration: {source_site}")

        grouped_declarations = [declaration]
        index += 1
        while index < len(source_declarations) and source_declarations[index].source_site.strip() == source_site:
            grouped_declarations.append(source_declarations[index])
            index += 1

        indent = re.match(r'\s*', line[:source_index]).group(0)
        replacement = render_source_site_replacement("", grouped_declarations, render_source, indent)
        line = line[:source_index] + replacement + line[source_index + len(source_site):]
        search_start = source_index + len(replacement)

    return line


def source_declaration_groups(source_declarations):
    groups = []
    index = 0
    while index < len(source_declarations):
        declaration = source_declarations[index]
        source_site = declaration.source_site.strip()
        group = [declaration]
        index += 1
        while index < len(source_declarations) and source_declarations[index].source_site.strip() == source_site:
            group.append(source_declarations[index])
            index += 1
        groups.append(group)
    return groups


def remaining_source_declaration_groups(declarations_by_column, fallback_declarations):
    groups = []
    for source_column in sorted(declarations_by_column):
        groups.extend(source_declaration_groups(declarations_by_column[source_column]))
    groups.extend(source_declaration_groups(fallback_declarations))
    return groups


def spans_overlap(left, right):
    return left[0] < right[1] and right[0] < left[1]


def find_unquoted_source_site_span(line: str, source_site: str, occupied_spans):
    search_start = 0
    while search_start < len(line):
        source_index = find_unquoted_substring(line, source_site, search_start)
        if source_index < 0:
            return None
        span = (source_index, source_index + len(source_site))
        if not any(spans_overlap(span, occupied_span) for occupied_span in occupied_spans):
            return span
        search_start = span[1]
    return None


def apply_line_replacements(line: str, replacements):
    output = []
    last_end = 0
    for start, end, replacement in sorted(replacements, key=lambda item: item[0]):
        if start < last_end:
            raise ValueError(f"Overlapping source replacements in line: {line.strip()}")
        output.append(line[last_end:start])
        output.append(replacement)
        last_end = end
    output.append(line[last_end:])
    return ''.join(output)


def replace_exact_line_fragments(line: str, line_replacements):
    if not line_replacements:
        return line

    replacements = []
    occupied_spans = []
    for line_replacement in line_replacements:
        old = line_replacement.old
        start = line.find(old)
        if start < 0:
            raise ValueError(f"Could not replace resolved line fragment: {old}")
        span = (start, start + len(old))
        if any(spans_overlap(span, occupied_span) for occupied_span in occupied_spans):
            raise ValueError(f"Overlapping line replacements in line: {line.strip()}")
        replacements.append((*span, line_replacement.new))
        occupied_spans.append(span)

    return apply_line_replacements(line, replacements)


def replace_source_site_declarations(line: str, source_declarations, render_source):
    if not source_declarations:
        return line

    matches = list(SOURCE_PATTERN.finditer(line))
    if not matches:
        return replace_source_site_substrings(line, source_declarations, render_source)

    declarations_by_column, fallback_declarations = group_source_declarations_by_column(source_declarations)
    replacements = []
    occupied_spans = []

    for match in matches:
        grouped_declarations = pop_source_declarations_for_match(
            match,
            declarations_by_column,
            group_fallback=len(matches) == 1,
        )
        if not grouped_declarations and fallback_declarations:
            grouped_declarations.append(fallback_declarations.pop(0))
        if not grouped_declarations:
            continue

        separator = match.group(1) or ''
        indent = re.match(r'\s*', separator).group(0) if separator else ''
        replacement = render_source_site_replacement(separator, grouped_declarations, render_source, indent)
        span = (match.start(), match.end())
        replacements.append((*span, replacement))
        occupied_spans.append(span)

    for grouped_declarations in remaining_source_declaration_groups(declarations_by_column, fallback_declarations):
        source_site = grouped_declarations[0].source_site.strip()
        span = find_unquoted_source_site_span(line, source_site, occupied_spans)
        if span is None:
            raise ValueError(f"Could not replace resolved source declaration: {source_site}")

        indent = re.match(r'\s*', line[:span[0]]).group(0)
        replacement = render_source_site_replacement("", grouped_declarations, render_source, indent)
        replacements.append((*span, replacement))
        occupied_spans.append(span)

    return apply_line_replacements(line, replacements)


def assert_no_unresolved_source_sites(content: str):
    active_heredocs = []
    for line in content.splitlines():
        if active_heredocs:
            if is_heredoc_end(line, active_heredocs[0]):
                active_heredocs.pop(0)
            continue

        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        if line_contains_unresolved_source(line):
            raise UnsupportedSourceError(
                f"unresolved source remained in executable output: {stripped_line}",
                code="unsupported.source.unresolved-output",
                hint="Executable output cannot contain live source statements.",
            )

        active_heredocs.extend(extract_heredoc_delimiters(line))


def line_contains_unresolved_source(line: str):
    if SOURCE_PATTERN.findall(line):
        return True
    if any(contains_source_command(command) for command in get_commands(line)):
        return True
    if "source" not in line and not re.search(r'(^|[\s;&|({])\.\s+', line):
        return False
    return contains_nested_source_command(line)


def render_executable_script(entry_point: str, context: dict):
    file_contents = {}
    render_stack = []

    def get_content(filepath):
        if filepath not in file_contents:
            content = read_file(filepath)
            file_contents[filepath] = content
        return file_contents[filepath]

    def render_file(filepath):
        filepath = os.path.abspath(filepath)
        if filepath in render_stack:
            chain = " -> ".join([*render_stack, filepath])
            raise RecursionError(f"Circular source dependency while rendering: {chain}")

        render_stack.append(filepath)
        try:
            source_context = context.get('source_declarations', {}).get(filepath, {})
            output = []

            for num, line in enumerate(get_content(filepath).splitlines()):
                stripped_line = line.strip()
                if not stripped_line or stripped_line.startswith("#"):
                    continue

                line = replace_exact_line_fragments(
                    line,
                    context.get('line_replacements', {}).get(filepath, {}).get(num, []),
                )
                source_declarations = source_context.get(num, [])
                unsupported_sources = [
                    source_declaration for source_declaration in source_declarations
                    if source_declaration.execution_model != "parent-source"
                ]
                if unsupported_sources:
                    source_site = unsupported_sources[0].source_site
                    raise NotImplementedError(f"unsupported non-parent source in executable mode: {source_site}")

                line = replace_runtime_source_references(line, filepath, entry_point)
                command_sources = [
                    source_declaration for source_declaration in source_declarations
                    if source_declaration.replacement_kind in {"command", "noop-command"}
                ]
                line = replace_command_source_sites(line, command_sources, render_file)
                source_site_declarations = [
                    source_declaration for source_declaration in source_declarations
                    if source_declaration.replacement_kind in {"source", "noop-source", "retained-source"}
                ]
                if source_site_declarations:
                    line = replace_source_site_declarations(
                        line,
                        source_site_declarations,
                        render_file,
                    )
                output.append(line)

            return '\n'.join(output)
        finally:
            render_stack.pop()

    # Build from the entry point so sourced files execute at their source sites.
    output = [SET_SHEBANG, '']
    output.append(construct_file_separator(entry_point, entry_point))
    rendered_entry = render_file(os.path.abspath(entry_point))
    assert_no_unresolved_source_sites(rendered_entry)
    output.append(rendered_entry)
    output.append('')

    return output


def render_context_files(ordered_dependencies: list[str], entry_point: str, context: dict):
    output = [
        "# modashc context",
        f"# entrypoint: {format_context_path(entry_point, entry_point)}",
        "# mode: context",
        "",
    ]

    source_declarations = context.get('source_declarations', {})

    for filepath in unique_paths(ordered_dependencies):
        source_context = source_declarations.get(filepath, {})
        output.append(construct_file_separator(filepath, entry_point))

        for num, line in enumerate(read_file(filepath).splitlines()):
            line_indent = re.match(r'\s*', line).group(0)
            for source_declaration in source_context.get(num, []):
                output.append(f"{line_indent}{construct_context_source_comment(source_declaration, entry_point)}")
            output.append(line)

        output.append('')

    return output


def context_from_source_events(events, disabled_sources=(), line_replacements=()):
    source_declarations = defaultdict(lambda: defaultdict(list))
    line_replacement_context = defaultdict(lambda: defaultdict(list))

    for event in events:
        source_declarations[str(event.location.path)][event.location.line - 1].append(ResolvedSource(
            path=str(event.path),
            source_expression=event.source_expression,
            source_site=event.source_site,
            execution_model=event.execution_model.value,
            replacement_kind=event.replacement_kind,
            source_value=event.source_value,
            source_column=event.location.column,
            occurrence_model=event.occurrence_model.value,
            condition=event.condition,
        ))

    for disabled_source in disabled_sources:
        source_declarations[str(disabled_source.location.path)][disabled_source.location.line - 1].append(ResolvedSource(
            path="",
            source_expression=disabled_source.source_expression,
            source_site=disabled_source.source_site,
            execution_model="parent-source",
            replacement_kind=f"noop-{disabled_source.replacement_kind}",
            source_column=disabled_source.location.column,
            occurrence_model="once",
            condition=disabled_source.condition,
        ))

    for line_replacement in line_replacements:
        replacements = line_replacement_context[str(line_replacement.location.path)][line_replacement.location.line - 1]
        for existing in replacements:
            if existing.old == line_replacement.old and existing.new != line_replacement.new:
                raise UnsupportedSourceError(
                    f"conflicting exact line replacement for {line_replacement.old}: "
                    f"{existing.new} != {line_replacement.new}"
                )
            if existing == line_replacement:
                break
        else:
            replacements.append(line_replacement)

    return {
        'source_declarations': source_declarations,
        'line_replacements': line_replacement_context,
    }


def context_paths_from_source_events(entry_point: str, events):
    children_by_parent = defaultdict(list)
    for event in events:
        children_by_parent[os.path.abspath(event.location.path)].append(os.path.abspath(event.path))

    ordered_paths = []
    seen_paths = set()

    def visit(filepath: str):
        filepath = os.path.abspath(filepath)
        for child in children_by_parent.get(filepath, []):
            visit(child)
        if filepath not in seen_paths:
            seen_paths.add(filepath)
            ordered_paths.append(filepath)

    visit(entry_point)
    return ordered_paths


def compile_sources(entry_point: str, output_file: str, mode: str = "context", source_supplement=None):
    if mode not in {"context", "executable"}:
        raise ValueError(f"Unsupported compile mode: {mode}")

    if not validate_path(entry_point):
        raise FileNotFoundError(f"Error: Could not resolve the path to the entry point - {entry_point}")

    if not os.path.isfile(entry_point):
        raise OSError(f"Error: entry point must be a file - {entry_point}")

    entry_point = os.path.abspath(entry_point)
    supplement = load_source_supplement(source_supplement, os.path.dirname(entry_point))
    evaluation = SourceEvaluator(mode=mode, source_supplement=supplement).evaluate(entry_point)
    context = context_from_source_events(evaluation.events, evaluation.disabled_sources, evaluation.line_replacements)
    if mode == "executable":
        output = render_executable_script(entry_point, context)
    else:
        sources = context_paths_from_source_events(entry_point, evaluation.events)
        output = render_context_files(sources, entry_point, context)
    content = '\n'.join(output)
    write_output(output_file, content)
