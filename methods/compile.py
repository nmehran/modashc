import os
import re

from methods.regex.patterns import SOURCE_PATTERN
from methods.sources import UnsupportedSourceError, contains_source_command, get_sources, validate_path

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


def replace_source_sites(line: str, source_paths: list[str], render_source):
    if not source_paths:
        return line

    updated_parts = []
    last_end = 0
    source_index = 0

    for match in SOURCE_PATTERN.finditer(line):
        if source_index >= len(source_paths):
            break

        separator = match.group(1) or ''
        indent = re.match(r'\s*', separator).group(0) if separator else ''
        rendered_source = indent_block(render_source(source_paths[source_index]), indent)
        replacement = f"{separator}{{\n{rendered_source}\n{indent}}}"

        updated_parts.append(line[last_end:match.start()])
        updated_parts.append(replacement)
        last_end = match.end()
        source_index += 1

    updated_parts.append(line[last_end:])
    return ''.join(updated_parts)


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
        replacement = render_source_block(source_declaration.path, render_source, indent)
        line = line[:source_index] + replacement + line[source_index + len(source_site):]
        search_start = source_index + len(replacement)

    return line


def assert_no_unresolved_source_sites(content: str):
    for line in content.splitlines():
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        if SOURCE_PATTERN.findall(line) or contains_source_command(line):
            raise UnsupportedSourceError(f"unresolved source remained in executable output: {stripped_line}")


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
                    if source_declaration.replacement_kind == "command"
                ]
                line = replace_command_source_sites(line, command_sources, render_file)
                source_paths = [
                    source_declaration.path for source_declaration in source_declarations
                    if source_declaration.replacement_kind == "source"
                ]
                line = replace_source_sites(line, source_paths, render_file)
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
            for source_declaration in source_context.get(num, []):
                output.append(construct_context_source_comment(source_declaration, entry_point))
            output.append(line)

        output.append('')

    return output


def compile_sources(entry_point: str, output_file: str, mode: str = "context"):
    if mode not in {"context", "executable"}:
        raise ValueError(f"Unsupported compile mode: {mode}")

    if not validate_path(entry_point):
        raise FileNotFoundError(f"Error: Could not resolve the path to the entry point - {entry_point}")

    if not os.path.isfile(entry_point):
        raise OSError(f"Error: entry point must be a file - {entry_point}")

    sources, context = get_sources(os.path.abspath(entry_point), mode=mode)
    if mode == "executable":
        output = render_executable_script(entry_point, context)
    else:
        output = render_context_files(sources, entry_point, context)
    content = '\n'.join(output)
    write_output(output_file, content)
