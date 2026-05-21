import os
import re

from methods.regex.patterns import (
    CD_PATTERN,
    FUNCTION_PATTERN,
    SET_PATTERN,
    SOURCE_PATTERN,
    VARIABLE_ASSIGNMENT_PATTERN,
)

from methods.sources import get_sources, validate_path, is_within_subtree, is_relative_path, change_directory, strip_quotes, extract_bash_commands
from methods.regex.utilities import replace_bash_command

SET_SHEBANG = "#!/bin/bash"
SET_DECLARATIVE = "set -eEuo pipefail"


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


def extract_desired_content_including_functions(filepath, content, context, entry_directory: str, strip_comments=True):
    output = []
    bracket_depth = 0  # Track the depth of curly braces to handle nested function blocks
    lines = content.splitlines()

    # Patterns to skip
    set_pattern = SET_PATTERN
    source_pattern = SOURCE_PATTERN
    path_context = context['path_declarations'].get(filepath, {})

    for num, line in enumerate(lines):
        stripped_line = line.strip()

        # Skip empty lines and comments if strip_comments is True
        if not stripped_line or (strip_comments and stripped_line.startswith("#")):
            continue

        # Check for entering or exiting function definitions based on braces
        if '{' in stripped_line:
            bracket_depth += stripped_line.count('{')
        if '}' in stripped_line:
            bracket_depth -= stripped_line.count('}')

        if path_declarations := path_context.get(num):
            for (cmd_type, path, match_groups, current_directory) in path_declarations:
                if cmd_type == 'cd':
                    if is_within_subtree(path, entry_directory):
                        line = replace_bash_command(cmd_type, ':', line, CD_PATTERN)
                    elif is_relative_path(path):
                        line = replace_bash_command(cmd_type, f'cd "{path}"', line, CD_PATTERN)
                    change_directory(path, context)

                else:  # else path-type is `var`
                    scope, var_name, sign, var_value = match_groups
                    value = strip_quotes(var_value)
                    if value.endswith('.sh') and is_within_subtree(path, entry_directory):
                        if os.path.isfile(path):
                            # The current file is included in the compiled script
                            line = VARIABLE_ASSIGNMENT_PATTERN.sub(f'{var_name}{sign}"$BASH_SOURCE"', line, count=1)
                    elif is_relative_path(value):
                        line = VARIABLE_ASSIGNMENT_PATTERN.sub(f'{var_name}{sign}"{path}"', line, count=1)

        # Include lines based on current state
        if bracket_depth > 0:
            # We're inside a function
            output.append(line)
        elif not set_pattern.match(stripped_line) and not source_pattern.match(stripped_line):
            # We're not inside a function, only add line if it's not a set/source command
            output.append(line)

        # Manage bracket depth after processing the line
        if bracket_depth < 0:
            bracket_depth = 0  # Reset depth in case of malformed input

    return '\n'.join(output)


def extract_bash_functions(content):

    def inside_string_or_comment(_line):
        in_single_quote = False
        in_double_quote = False
        escaped = False
        in_comment = False

        for _char in _line:
            if in_comment:
                continue
            if _char == '\\' and not escaped:
                escaped = True
                continue
            if _char == '\'' and not in_double_quote and not escaped:
                in_single_quote = not in_single_quote
            if _char == '"' and not in_single_quote and not escaped:
                in_double_quote = not in_double_quote
            if _char == '#' and not in_single_quote and not in_double_quote:
                in_comment = True
            escaped = False

        return in_single_quote or in_double_quote

    functions = []
    in_function = False
    brace_stack = []
    current_function = []

    lines = content.split('\n')
    for line in lines:
        stripped_line = line.strip()

        # Check if line is possibly starting a function
        if FUNCTION_PATTERN.match(stripped_line):
            in_function = True

        if in_function:
            current_function.append(line)
            # Count braces, ignoring comments and strings
            for i, char in enumerate(line):
                if char == '{' and not inside_string_or_comment(line[:i]):
                    brace_stack.append('{')
                elif char == '}' and not inside_string_or_comment(line[:i]):
                    if brace_stack:
                        brace_stack.pop()
                    if not brace_stack:
                        # Function is complete
                        functions.append('\n'.join(current_function))
                        current_function = []
                        in_function = False
                        break
    return functions


def extract_globals(content):

    def handle_multiline_assignment(_lines, initial_value):
        """
        Handles multi-line assignments by concatenating lines until the assignment is complete.
        """
        _value = initial_value.strip()
        if _value.endswith('\\'):
            _value = _value[:-1].strip()
            while True:
                next_line = next(_lines).strip()
                _value += ' ' + next_line
                if not next_line.endswith('\\'):
                    break
                _value = _value[:-1].strip()
        return _value

    # Regex to capture global and exported variables, ensuring they're not part of a comment or inside a function
    global_pattern = VARIABLE_ASSIGNMENT_PATTERN

    extracted_globals = {}
    inside_function = False
    lines = iter(content.splitlines())
    for line in lines:
        line = line.strip()
        if line.endswith('}'):
            inside_function = False
        if line.endswith('() {'):
            inside_function = True
        if not inside_function and not line.startswith('#'):
            # Split by semicolons and process each part
            parts = re.split(r';\s*', line)
            for part in parts:
                part = part.strip()
                match = global_pattern.match(part)
                if match:
                    var_name = match.group(2).strip()
                    value = match.group(4).strip()
                    value = handle_multiline_assignment(lines, value)
                    extracted_globals[var_name] = value

    return extracted_globals


def extract_sources(content):
    sources = set()
    inside_function = False
    lines = content.splitlines()
    for line in lines:
        stripped_line = line.strip()

        # Ignore lines that are comments
        if stripped_line.startswith("#"):
            continue

        # Check if we are entering or exiting a function
        if stripped_line.endswith('}'):
            inside_function = False
        if stripped_line.endswith('() {'):
            inside_function = True

        # Process line if it's not inside a function
        if not inside_function:
            for match in re.finditer(SOURCE_PATTERN, line):
                # Extract path, removing any leading/trailing whitespace and quotes
                path: str = match.group(3).strip().strip('\'"')
                if path:  # Only add non-empty paths
                    sources.add(path)

    return list(sources)


def sanitize_sources(content: str):
    def replacement_func(match):
        if source_match := match.group(1):
            return f"{source_match}:"
        return match.group(0)
    return SOURCE_PATTERN.sub(replacement_func, content)


def extract_set_declarations(content):
    sets = set()
    inside_function = False
    lines = iter(content.splitlines())
    for line in lines:
        line = line.strip()
        if line.endswith('}'):
            inside_function = False
        if line.endswith('() {'):
            inside_function = True
        if not inside_function and not line.startswith('#'):
            # Split by semicolons and process each part
            parts = re.split(r';\s*', line)
            for part in parts:
                part = part.strip()
                match = SET_PATTERN.match(part)
                if match:
                    set_options = match.group(1).strip().split()
                    for opt in set_options:
                        if opt.startswith('-'):
                            sets.update(opt[1:])
                        else:
                            sets.add(opt)

    # Combine set declarations intelligently
    sets.discard('o')  # Remove 'o' if it exists
    return sets


def construct_set_declaration(all_sets):
    combined_set = set()
    for s in all_sets:
        combined_set.update(s)

    # Build the set command with options in the correct order
    options = []
    if 'o' in combined_set:
        combined_set.remove('o')
        options.append('-o')

    if 'pipefail' in combined_set:
        combined_set.remove('pipefail')
        options.append('-o pipefail')

    # Add remaining options, sorted for consistency
    sorted_options = sorted(combined_set)
    options = ['-{}'.format(opt) for opt in sorted_options] + options

    return 'set ' + ' '.join(options) if options else ''


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


def construct_context_source_comment(source_expression: str, resolved_path: str, entry_point: str):
    return f"# modashc: source {source_expression.strip()} -> {format_context_path(resolved_path, entry_point)}"


def read_file(filepath):
    with open(filepath, 'r') as file:
        return file.read()


def write_output(filename, content):
    with open(filename, 'w') as file:
        file.write(content)


def merge_files(_ordered_dependencies: list[str], entry_point, context):
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

                line = replace_runtime_source_references(line, filepath, entry_point)
                source_paths = [source_path for source_path, _ in source_context.get(num, [])]
                line = replace_source_sites(line, source_paths, render_file)
                output.append(line)

            return '\n'.join(output)
        finally:
            render_stack.pop()

    # Build from the entry point so sourced files execute at their source sites.
    output = [SET_SHEBANG, '']
    output.append(construct_file_separator(entry_point, entry_point))
    output.append(render_file(os.path.abspath(entry_point)))
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
            for resolved_path, source_expression in source_context.get(num, []):
                output.append(construct_context_source_comment(source_expression, resolved_path, entry_point))
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

    sources, context = get_sources(os.path.abspath(entry_point))
    if mode == "executable":
        output = merge_files(sources, entry_point, context)
    else:
        output = render_context_files(sources, entry_point, context)
    content = '\n'.join(output)
    write_output(output_file, content)
