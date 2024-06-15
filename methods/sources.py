import os
import re

from methods.patterns import (
    BASENAME_PATTERN,
    DIRNAME_PATTERN,
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


def define_variable(var_match, context):
    var_name = var_match.group(3)
    var_value = var_match.group(4)
    if "$" in var_value:
        # substitute known variables from context
        for var, value in context.items():
            var_value = var_value.replace(f"${{{var}}}", value).replace(f"${var}", value)

    return var_name, var_value


def extract_sources_and_variables(script_path, context):
    """Extract source statements and global variables from a shell script."""
    sources = []
    variables = {}

    if not validate_path(script_path):
        raise FileExistsError(f"Error: File does not exist - {script_path}")

    with open(script_path, 'r') as file:
        for line in file:
            # Skip lines that are commented or start with a quote
            if re.match(r'\s*#', line) or re.match(r'\s*["\']', line):
                continue

            # Match source statements
            source_matches = SOURCE_PATTERN.findall(line)
            for _, _, source_path in source_matches:
                # Strip quotes which might be used to enclose paths with spaces
                stripped_path = source_path.strip('"').strip("'")
                sources.append(stripped_path)

            # Match variable definitions
            var_match = VARIABLE_PATTERN.match(line)
            if var_match:
                var_name, var_value = define_variable(var_match, context)
                variables[var_name] = var_value

    return sources, variables


def resolve_shell_functions(path):
    """Resolve shell functions like $(dirname ...) and $(basename ...)"""

    # Match patterns like $(dirname <path>) or $(basename <path>)
    while True:
        dirname_match = DIRNAME_PATTERN.search(path)
        basename_match = BASENAME_PATTERN.search(path)

        # If a $(dirname ...) is found, replace it with the Python dirname result
        if dirname_match:
            full_match = dirname_match.group(0)
            inner_path = dirname_match.group(1)
            # Compute the directory name using os.path.dirname
            dirname_result = os.path.dirname(inner_path)
            path = path.replace(full_match, dirname_result)
        # If a $(basename ...) is found, replace it with the Python basename result
        elif basename_match:
            full_match = basename_match.group(0)
            inner_path = basename_match.group(1)
            # Compute the base name using os.path.basename
            basename_result = os.path.basename(inner_path)
            path = path.replace(full_match, basename_result)
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


def resolve_path(path, context):
    """Resolve a path using dynamic context, supporting shell operations."""

    # First, substitute known variables from context
    for var, value in context.items():
        path = path.replace(f"${{{var}}}", value).replace(f"${var}", value)

    # Expand environment variables
    path = os.path.expandvars(path)

    # Handle shell functions like $(dirname ...) and $(basename ...)
    path = resolve_shell_functions(path)

    # Normalize and convert to absolute path
    path = os.path.normpath(strip_quotes(path))
    return os.path.abspath(path)


def get_sources(entrypoint):
    context = {'0': entrypoint}  # Initialize context with the entry point
    file_sources = {}
    to_process = [entrypoint]
    call_stack = set()  # Stack to track the call chain and detect circular references

    while to_process:
        current_file = to_process.pop(0)

        # Check for circular references
        if current_file in call_stack:
            raise Exception(f"Circular reference detected: {current_file} is already being processed.")

        # Add the file to the call stack
        call_stack.add(current_file)

        # Process the file if it has not been processed yet
        if current_file not in file_sources:
            sources, variables = extract_sources_and_variables(current_file, context)

            # Update context in the order variables appear
            for var, value in variables.items():
                # Resolve any variables in the value itself
                resolved_value = resolve_path(value, context)
                context[var] = resolved_value  # Update or add the new value to context

            resolved_sources = []
            for src in sources:
                if src:  # Ensure non-empty strings are processed
                    resolved_path = resolve_path(src, context)
                    resolved_sources.append(resolved_path)
                    to_process.append(resolved_path)  # Prepare for recursive resolution

            file_sources[current_file] = resolved_sources

        # Remove the file from the call stack after processing
        call_stack.remove(current_file)

    return file_sources


def depth_first_sort_sources(sources, entry_point):
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


# TODO: support`allowed functions`, such as `cd`
