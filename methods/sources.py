import os
import re
from collections import defaultdict

from methods.regex.utilities import extract_bash_commands, strip_matching_quotes, replace_substring
from methods.regex.patterns import (
    BASENAME_PATTERN,
    CD_PATTERN,
    DIRNAME_PATTERN,
    REALPATH_PATTERN,
    SOURCE_PATTERN,
    VARIABLE_ASSIGNMENT_PATTERN,
    VARIABLE_NAME_PATTERN,
    VARIABLE_REFERENCE_PATTERN,
)

RECURSION_LIMIT = 2


def validate_path(path):
    """Check for common path errors and warn about potential issues."""
    warnings = []

    # Check for unresolved variables
    if '$' in path:
        warnings.append(f"Warning: Path may contain unresolved variables - {path}")

    # Additional checks can be added here
    # Example: overly complex expressions or deprecated syntax

    # Report all found issues regardless of file existence
    for warning in warnings:
        print(warning)

    # Finally, check if the file exists and return appropriate status
    if not os.path.exists(path):
        print(f"Error: File does not exist - {path}")
        return False

    return True


def define_variable(var_match, context):
    """Define a variable based on known context."""

    var_name = var_match.group(2).strip()
    var_value = var_match.group(4).strip()

    # substitute known variables from context
    var_value = resolve_variable_references(var_value, context)

    return var_name, strip_matching_quotes(var_value)


def resolve_shell_path_commands(path_command: str):
    """Resolve shell functions like $(dirname ...) and $(basename ...)"""

    commands = {
        'dirname': (os.path.dirname, DIRNAME_PATTERN),
        'basename': (os.path.basename, BASENAME_PATTERN),
        'realpath': (os.path.abspath, REALPATH_PATTERN)
    }

    while True:
        modified = False
        for cmd_name, (func, pattern) in commands.items():
            match = pattern.search(path_command)
            if match:
                full_match = match.group(0)
                path_match = match.group(1)
                result = func(strip_quotes(path_match))
                # Replace the matched pattern with the result wrapped in an echo statement
                path_command = path_command.replace(full_match, result)
                modified = True
                break  # Stop after the first replacement to re-evaluate from the start

        if not modified:
            break  # Exit the loop if no more commands are found

    return path_command


def strip_quotes(path):
    """Strip incorrect usage of quotes within paths."""
    # This regex will target quotes that are at the very beginning or end of the string
    # and quotes around path separators.
    path = re.sub(r'^["\']|["\']$', '', path)  # Remove quotes at the start or end
    path = re.sub(r'(?<=/)"|"(?=/)', '', path)  # Remove quotes around slashes
    return path


def get_valid_path(command):
    if len(command) >= 1:
        unquoted_command = strip_matching_quotes(command)
        command = os.path.abspath(unquoted_command)
        if os.path.exists(command):
            return command
    return ""


def resolve_variable_references(command, context):

    search_start = 0
    while True:
        variable_reference = VARIABLE_REFERENCE_PATTERN.search(command, search_start)
        if not variable_reference:
            break

        outer_reference, inner_reference = variable_reference.groups()
        start, end = variable_reference.span()

        try:
            if inner_reference:
                inner_name = VARIABLE_NAME_PATTERN.match(inner_reference).group(1)
                inner_definition = context['vars'].get(inner_name)
                command = replace_substring(command, inner_reference, inner_definition, start, end)

            outer_name = VARIABLE_NAME_PATTERN.match(outer_reference).group(1)
            outer_definition = context['vars'].get(outer_name)
            command = replace_substring(command, outer_reference, outer_definition, start, end)

            search_start = end

        except AttributeError:
            # Cases where pattern matching fails
            search_start = end

    return command


def resolve_command(command, context):
    """Resolve a path using dynamic context, supporting shell operations."""
    command = resolve_variable_references(command.strip(), context)

    # Expand environment variables
    command = os.path.expandvars(command)

    # Handle shell functions like $(dirname ...) and $(basename ...)
    command = resolve_shell_path_commands(command)

    # If path, normalize and convert to absolute path
    is_valid_path = False
    if path := get_valid_path(command):
        is_valid_path = True
        command = path
    elif not command:
        command = ""

    return command, is_valid_path


def sort_sources_depth_first(sources, entry_point):
    ordered_sources = []
    visited = set()

    def dfs(file_path):
        if file_path in visited:
            return
        visited.add(file_path)
        # First recurse for each source file listed under the current file
        for src in sources.get(file_path, []):
            dfs(src)
        # Append the current file to the ordered list after processing all its dependencies
        ordered_sources.append(file_path)

    # Start DFS from the entry point
    dfs(entry_point)
    return ordered_sources


def get_commands(line: str):
    lines = line.split('#')[0].split(';')
    return map(str.strip, lines)


def resolve_cd_path(cd_match: tuple[str, str]):
    return cd_match[0][1]


def change_directory(path: str, context: dict) -> str:
    """Change the current directory based on a cd command."""

    # Remove potential quotes and expand environment variables in the path
    path = os.path.expandvars(strip_quotes(path))

    # Resolve non-environment variables in the path given current context
    resolved_command, is_valid_path = resolve_command(path, context)
    if not is_valid_path:
        raise ValueError(f"No path could be resolved for the value: {path}")

    new_path = os.path.abspath(resolved_command)

    # If the path is a file, use its directory part
    if os.path.isfile(new_path):
        new_path = os.path.dirname(new_path)

    # Check if the new path is a directory
    if not os.path.isdir(new_path):
        raise NotADirectoryError(f"Directory not found: {new_path}")

    try:
        os.chdir(new_path)
    except Exception as e:
        raise OSError(f"Could not change to directory: {new_path}.\nError:\n{e}")

    context['current_directory'] = new_path
    return new_path


def enforce_recursion_limit(seen_sources, script_path, references):
    referrer = references[-1]
    seen_sources[script_path][referrer] += 1

    if seen_sources[script_path][referrer] >= RECURSION_LIMIT and script_path in references:
        error_message = (f"Maximum recursion limit of {RECURSION_LIMIT} reached.  "
                         f"Ensure there are no circular dependencies and try again:"
                         f"\nReferrer: {referrer}\nCurrent-Script: {script_path}")
        raise RecursionError(error_message)
    return


def is_absolute_path(path):
    # Strip matching single and double quotes from the start and end of the path
    stripped_path = strip_matching_quotes(path)
    # Use os.path.isabs to check if the path is absolute
    return os.path.isabs(stripped_path)


def is_relative_path(path: str):
    # Strip matching single and double quotes from the start and end of the path
    stripped_path = strip_matching_quotes(path)
    # If path is not absolute and exists, it is relative
    return not os.path.isabs(stripped_path) and os.path.exists(path)


def is_within_subtree(paths, directory):
    if isinstance(paths, str):
        paths = [paths]

    # Resolve all paths to their absolute forms
    resolved_paths = [os.path.abspath(path) for path in paths]
    resolved_directory = os.path.abspath(directory)

    try:
        # Get the common path of the resolved paths and the directory
        common_path = os.path.commonpath(resolved_paths + [resolved_directory])
        # Compare the common path with the resolved directory
        return common_path == resolved_directory
    except ValueError:
        # Happens when paths is empty or contains non-existent paths
        return False


def resolve_path(source_path: str, context: dict):
    stripped_path = strip_quotes(source_path)
    resolved_command, is_valid_path = resolve_command(stripped_path, context)
    resolved_path = strip_quotes(resolved_command)
    if is_valid_path:
        if is_relative_path(resolved_path):
            current_dir = context['current_directory']
            resolved_path = os.path.join(current_dir, resolved_path)
        if resolved_path:
            return os.path.abspath(resolved_path)
    return None


def extract_sources_and_variables(script_path, context, sources, seen_sources: dict, references=None):
    """Extract source statements and global variables from a shell script."""

    if not validate_path(script_path):
        raise FileNotFoundError(f"Error: File does not exist - {script_path}")

    if script_path not in context['path_declarations']:
        context['path_declarations'][script_path] = defaultdict(list)

    if script_path not in seen_sources:
        seen_sources[script_path] = defaultdict(int)

    if references is None:
        references = (script_path,)
    else:
        enforce_recursion_limit(seen_sources, script_path, references)
        references = (*references, script_path)

    context['vars']['BASH_SOURCE'] = os.path.abspath(script_path)

    with open(script_path, 'r') as file:
        for num, line in enumerate(file):
            for command in get_commands(line):
                # Skip lines that are commented or start with a quote
                if not command or re.match(r'\s*["\']', line):
                    continue

                resolved_command = resolve_command(command, context)[0]

                cd_match = extract_bash_commands('cd', resolved_command, CD_PATTERN)
                if cd_match:
                    cd_path = resolve_cd_path(cd_match)
                    current_directory = change_directory(cd_path, context)
                    context['path_declarations'][script_path][num].append(('cd', current_directory, cd_match, current_directory))

                # Match variable definitions
                var_match = VARIABLE_ASSIGNMENT_PATTERN.match(line)
                if var_match:
                    var_name, var_value = define_variable(var_match, context)
                    resolved_command, is_valid_path = resolve_command(var_value, context)
                    context['vars'][var_name] = resolved_command
                    if is_valid_path:
                        context['path_declarations'][script_path][num].append(('var', resolved_command, var_match.groups(), context['current_directory']))

                # Match source statements
                source_matches = SOURCE_PATTERN.findall(line)
                for _, _, source_path in source_matches:
                    # Strip quotes which might be used to enclose paths with spaces
                    resolved_path = resolve_path(source_path, context)
                    if resolved_path:
                        extract_sources_and_variables(resolved_path, context, sources, seen_sources, references)
                        if seen_sources[resolved_path][script_path] == 1:
                            sources.append(resolved_path)

    return sources


def get_sources(entrypoint):
    sources = []

    # Initialize context with the entry point
    current_directory = os.path.abspath(os.path.dirname(entrypoint))
    context = {
        'vars': {'0': os.path.abspath(entrypoint)},
        'current_directory': current_directory,
        'path_declarations': {}}
    change_directory(current_directory, context)

    extract_sources_and_variables(entrypoint, context, sources, seen_sources={})
    sources.append(entrypoint)
    return sources, context
