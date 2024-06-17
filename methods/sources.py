import os
import re
from collections import defaultdict

from methods.patterns import (
    BASENAME_PATTERN,
    CD_PATTERN,
    DIRNAME_PATTERN,
    REALPATH_PATTERN,
    SOURCE_PATTERN,
    VARIABLE_PATTERN,
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


def strip_first_and_last_quotes(text):
    return re.sub(r'^[\'"]|[\'"]$', '', text)


def define_variable(var_match, context):
    """Define a variable based on known context."""
    var_name = var_match.group(3)
    var_value = var_match.group(4)
    if "$" in var_value:
        # substitute known variables from context
        for var, value in context['vars'].items():
            var_value = var_value.replace(f"${{{var}}}", value).replace(f"${var}", value)

    return var_name, strip_first_and_last_quotes(var_value)


def resolve_shell_functions(path):
    """Resolve shell functions like $(dirname ...) and $(basename ...)"""

    # Match patterns like $(dirname <path>) or $(basename <path>)
    while True:
        dirname_match = DIRNAME_PATTERN.search(path)
        basename_match = BASENAME_PATTERN.search(path)
        realpath_match = REALPATH_PATTERN.search(path)

        # If a $(dirname ...) is found, replace it with the Python dirname result
        if dirname_match:
            full_match = dirname_match.group(0)
            inner_path = dirname_match.group(1)
            # Compute the directory name using os.path.dirname
            dirname_result = os.path.dirname(strip_quotes(inner_path))
            path = path.replace(full_match, dirname_result)
        # If a $(basename ...) is found, replace it with the Python basename result
        elif basename_match:
            full_match = basename_match.group(0)
            inner_path = basename_match.group(1)
            # Compute the base name using os.path.basename
            basename_result = os.path.basename(strip_quotes(inner_path))
            path = path.replace(full_match, basename_result)
        elif realpath_match:
            full_match = realpath_match.group(0)
            inner_path = realpath_match.group(1)
            # Compute the base name using os.path.basename
            realpath_result = os.path.abspath(strip_quotes(inner_path))
            path = path.replace(full_match, realpath_result)
        else:
            # No more matches, break the loop
            break

    return path


def strip_quotes(path):
    """Strip incorrect usage of quotes within paths."""
    # This regex will target quotes that are at the very beginning or end of the string
    # and quotes around path separators.
    path = re.sub(r'^["\']|["\']$', '', path)  # Remove quotes at the start or end
    path = re.sub(r'(?<=/)"|"(?=/)', '', path)  # Remove quotes around slashes
    return path


def get_valid_path(command):
    if len(command) > 2 and command[0] == command[-1] and command.startswith(('"', '\'')):
        command = os.path.abspath(command)
        if os.path.isfile(command) or os.path.isdir(command):
            return command
    return ""


def resolve_command(command, context):
    """Resolve a path using dynamic context, supporting shell operations."""

    command = command.strip()

    # First, substitute known variables from context
    for var, value in context['vars'].items():
        command = command.replace(f"${{{var}}}", value).replace(f"${var}", value)

    # Expand environment variables
    command = os.path.expandvars(command)

    # Handle shell functions like $(dirname ...) and $(basename ...)
    command = resolve_shell_functions(command)

    if not command:
        return ""

    # If path, normalize and convert to absolute path
    if path := get_valid_path(command):
        return path

    return command


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


def resolve_cd_path(cd_match: re.Match):
    return cd_match.group(2)


def change_directory(path: str, context: dict) -> str:
    """Change the current directory based on a cd command."""

    # Remove potential quotes and expand environment variables in the path
    path = os.path.expandvars(strip_quotes(path))

    # Resolve non-environment variables in the path given current context
    new_path = os.path.abspath(resolve_command(path, context))

    # If the path is a file, use its directory part
    if os.path.isfile(new_path):
        new_path = os.path.dirname(new_path)

    # Check if the new path is a directory
    if not os.path.isdir(new_path):
        raise NotADirectoryError(f"Directory not found: {new_path}")

    try:
        os.chdir(new_path)
    except Exception as e:
        raise OSError(f"Warning: Could not change to directory: {new_path}.\nError:\n{e}")

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


def is_relative_path(path: str):
    return path.startswith('.')


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
    resolved_path = strip_quotes(resolve_command(stripped_path, context))
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

                resolved_command = resolve_command(command, context)

                cd_match = CD_PATTERN.search(resolved_command)
                if cd_match:
                    cd_path = resolve_cd_path(cd_match)
                    current_directory = change_directory(cd_path, context)
                    context['path_declarations'][script_path][num].append(current_directory)

                # Match variable definitions
                var_match = VARIABLE_PATTERN.match(line)
                if var_match:
                    var_name, var_value = define_variable(var_match, context)
                    context['vars'][var_name] = resolve_command(var_value, context)

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
