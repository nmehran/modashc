import os
import re
import argparse
from collections import defaultdict

from methods.patterns import (
    FUNCTION_PATTERN,
    SET_PATTERN,
    SOURCE_PATTERN,
    VARIABLE_PATTERN,
)

from methods.sources import get_sources, depth_first_sort_sources

SET_SHEBANG = "#!/bin/bash"
SET_DECLARATIVE = "set -eEuo pipefail"


def extract_desired_content_including_functions(content, strip_comments=True):
    output = []
    bracket_depth = 0  # Track the depth of curly braces to handle nested function blocks
    lines = content.splitlines()

    # Patterns to skip
    set_pattern = SET_PATTERN
    source_pattern = SOURCE_PATTERN

    # Handle shebang if present in the first line
    start_index = 0
    if lines and lines[0].strip().startswith("#!"):
        start_index = 1  # Skip the first line if it's a shebang

    for line in lines[start_index:]:
        stripped_line = line.strip()

        # Skip empty lines and comments if strip_comments is True
        if not stripped_line or (strip_comments and stripped_line.startswith("#")):
            continue

        # Check for entering or exiting function definitions based on braces
        if '{' in stripped_line:
            bracket_depth += stripped_line.count('{')
        if '}' in stripped_line:
            bracket_depth -= stripped_line.count('}')

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
    global_pattern = VARIABLE_PATTERN

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
                    var_name = match.group(2)
                    value = match.group(3).strip()
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
                path = match.group(3).strip().strip('\'"')
                if path:  # Only add non-empty paths
                    sources.add(path)

    return list(sources)


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


def construct_file_separator(filepath, delimiter="-", length=120):
    # Get the basename of the file for the header
    filename = os.path.basename(filepath)

    # Create the header with the filename centered
    header_line = f"{filename}".center(length - 1, delimiter)

    # Create the full separator block
    line_block = f"#{delimiter * (length - 1)}\n"
    separator = f"{line_block}#{header_line}\n{line_block}\n"

    return separator


def read_file(filepath):
    with open(filepath, 'r') as file:
        return file.read()


def write_output(filename, content):
    with open(filename, 'w') as file:
        file.write(content)


def merge_files(ordered_dependencies: list[str]):
    all_sets = []
    file_contents = {}

    for filepath in ordered_dependencies:
        if filepath.endswith('.sh'):
            content = read_file(filepath)
            file_contents[filepath] = content

            # Extract components
            all_sets.append(extract_set_declarations(content))

    # Combine everything
    output = [SET_SHEBANG, '', SET_DECLARATIVE, '']

    for filepath in ordered_dependencies:
        separator = construct_file_separator(filepath)
        output.append('')
        output.append(separator)

        definitions = extract_desired_content_including_functions(file_contents[filepath])
        output.append(definitions)
        output.append('')

    return output


def compile_sources(entry_point: str, output_file: str):
    sources = get_sources(entry_point)
    ordered_sources = depth_first_sort_sources(sources, entry_point)
    output = merge_files(ordered_sources)
    write_output(output_file, '\n'.join(output))


def main(entry_point, output_file):
    compile_sources(entry_point, output_file)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Merge Bash scripts into a single script.')
    parser.add_argument('entrypoint', type=str, help='The entry-point Bash script that initiates the merging process.')
    parser.add_argument('output', type=str, help='The output file where the merged script will be saved.')
    args = parser.parse_args()
    main(entry_point=args.entrypoint, output_file=args.output)
