import os
import re
from collections import defaultdict

RECURSION_LIMIT = 2


from methods.patterns import (
    BASENAME_PATTERN,
    CD_PATTERN,
    DIRNAME_PATTERN,
    REALPATH_PATTERN,
    SOURCE_PATTERN,
    VARIABLE_PATTERN,
)


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
        for var, value in context.items():
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
    for var, value in context.items():
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


def change_directory(cd_match, current_dir, context):
    """Change the current directory based on a cd command."""
    cd_path = strip_quotes(cd_match.group(3))  # Remove potential quotes
    new_path = ""
    try:
        new_path = os.path.abspath(resolve_command(os.path.expandvars(cd_path), context))
        os.chdir(new_path)
        return new_path
    except FileNotFoundError:
        print(f"Warning: Directory not found {new_path}")
    return current_dir


def assert_recursion_limit(seen_sources, script_path, referrer):
    seen_sources[script_path][referrer] += 1

    if seen_sources[script_path][referrer] >= RECURSION_LIMIT:
        error_message = (f"Maximum recursion limit of {RECURSION_LIMIT} reached.  "
                         f"Ensure there are no circular dependencies and try again.")
        raise RecursionError(error_message)
    return


def is_relative_path(path: str):
    return path.startswith('.')


def extract_sources_and_variables(script_path, context, sources, seen_sources: dict, current_dir=None):
    """Extract source statements and global variables from a shell script."""

    if not validate_path(script_path):
        raise FileExistsError(f"Error: File does not exist - {script_path}")

    if current_dir is None:
        current_dir = os.path.abspath(os.path.dirname(script_path))
        os.chdir(current_dir)

    if script_path not in seen_sources:
        seen_sources[script_path] = defaultdict(int)

    referrer = context.get('BASH_SOURCE', script_path)
    assert_recursion_limit(seen_sources, script_path, referrer)

    context['BASH_SOURCE'] = os.path.abspath(script_path)

    with open(script_path, 'r') as file:
        for line in file:
            for command in get_commands(line):
                # Skip lines that are commented or start with a quote
                if not command or re.match(r'\s*["\']', line):
                    continue

                command = resolve_command(command, context)

                cd_match = CD_PATTERN.search(command)
                if cd_match:
                    current_dir = change_directory(cd_match, current_dir, context)

                # Match variable definitions
                var_match = VARIABLE_PATTERN.match(line)
                if var_match:
                    var_name, var_value = define_variable(var_match, context)
                    context[var_name] = resolve_command(var_value, context)

                # Match source statements
                source_matches = SOURCE_PATTERN.findall(line)
                for _, _, source_path in source_matches:
                    # Strip quotes which might be used to enclose paths with spaces
                    stripped_path = strip_quotes(source_path)
                    if stripped_path:
                        resolved_path = strip_quotes(resolve_command(stripped_path, context))
                        extract_sources_and_variables(resolved_path, context, sources, seen_sources, current_dir)
                        if seen_sources[script_path][referrer] == 1:
                            if is_relative_path(resolved_path):
                                resolved_path = os.path.join(current_dir, resolved_path)

                            sources.append(resolved_path)

    return sources


def get_sources(entrypoint):
    context = {'0': os.path.abspath(entrypoint)}  # Initialize context with the entry point
    sources = []
    extract_sources_and_variables(entrypoint, context, sources, seen_sources={})

    sources.append(entrypoint)
    return sources
