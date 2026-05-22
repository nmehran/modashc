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
from methods.source_diagnostics import unsupported_source_error, with_source_diagnostic
from methods.source_resolver import (
    SourceResolver,
    UnsupportedSourceError,
    contains_source_command,
    ends_unsupported_control_block,
    extract_heredoc_delimiters,
    is_heredoc_end,
    is_unsupported_control_flow_source,
    is_unsupported_dynamic_source,
    starts_unsupported_control_block,
)
from methods.shell_line import get_commands

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


def resolve_shell_path_commands(path_command: str, base_dir=None):
    """Resolve shell functions like $(dirname ...) and $(basename ...)"""

    def resolve_realpath(path):
        path = strip_quotes(path)
        if base_dir and not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        return os.path.abspath(path)

    commands = {
        'dirname': (os.path.dirname, DIRNAME_PATTERN),
        'basename': (os.path.basename, BASENAME_PATTERN),
        'realpath': (resolve_realpath, REALPATH_PATTERN)
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


def get_valid_path(command, base_dir=None):
    if len(command) >= 1:
        unquoted_command = strip_quotes(strip_matching_quotes(command.strip()))
        expanded_command = os.path.expanduser(os.path.expandvars(unquoted_command))

        candidates = []
        if os.path.isabs(expanded_command):
            candidates.append(expanded_command)
        elif base_dir:
            candidates.append(os.path.join(base_dir, expanded_command))
        else:
            candidates.append(expanded_command)

        for candidate in candidates:
            resolved = os.path.abspath(candidate)
            if os.path.exists(resolved):
                return resolved
    return ""


def resolve_variable_references(command, context):
    command_len = len(command)

    search_start = 0
    while search_start < command_len:
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
    command = resolve_shell_path_commands(command, context.get('current_directory'))

    # If path, normalize and convert to absolute path
    is_valid_path = False
    if path := get_valid_path(command, context.get('current_directory')):
        is_valid_path = True
        command = path
    elif not command:
        command = ""

    return command, is_valid_path


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
    # Strip matching single and double quotes from the start and end of the path
    stripped_path = strip_matching_quotes(path)
    return bool(stripped_path) and not os.path.isabs(stripped_path)


def resolve_path(source_path: str, context: dict):
    stripped_path = strip_quotes(source_path.strip())
    resolved_command, is_valid_path = resolve_command(stripped_path, context)
    resolved_path = strip_quotes(resolved_command)
    if is_valid_path:
        if is_relative_path(resolved_path):
            current_dir = context['current_directory']
            resolved_path = os.path.join(current_dir, resolved_path)
        if resolved_path:
            return os.path.abspath(resolved_path)
    return None


SOURCE_RESOLVER = SourceResolver(resolve_path, resolve_variable_references, get_commands)


def extract_sources_and_variables(script_path, context, sources, seen_sources: dict, references=None, mode="executable"):
    """Extract source statements and global variables from a shell script."""

    if not validate_path(script_path):
        raise FileNotFoundError(f"Error: File does not exist - {script_path}")

    if script_path not in context['source_declarations']:
        context['source_declarations'][script_path] = defaultdict(list)

    if script_path not in seen_sources:
        seen_sources[script_path] = defaultdict(int)

    if references is None:
        references = (script_path,)
    else:
        enforce_recursion_limit(seen_sources, script_path, references)
        references = (*references, script_path)

    previous_bash_source = context['vars'].get('BASH_SOURCE')
    context['vars']['BASH_SOURCE'] = os.path.abspath(script_path)

    try:
        control_depth = 0
        active_heredocs = []
        with open(script_path, 'r') as file:
            for num, line in enumerate(file):
                if active_heredocs:
                    if is_heredoc_end(line, active_heredocs[0]):
                        active_heredocs.pop(0)
                    continue

                for command in get_commands(line):
                    # Skip commands that are quoted strings rather than shell commands.
                    if not command or re.match(r'\s*["\']', command):
                        continue

                    command_control_depth = control_depth
                    context['vars']['BASH_SOURCE'] = os.path.abspath(script_path)
                    resolved_command = resolve_command(command, context)[0]

                    cd_match = extract_bash_commands('cd', resolved_command, CD_PATTERN, strip=False)
                    if cd_match:
                        cd_path = resolve_cd_path(cd_match).strip()
                        change_directory(cd_path, context)

                    # Match variable definitions
                    var_match = VARIABLE_ASSIGNMENT_PATTERN.match(command)
                    if var_match:
                        var_name, var_value = define_variable(var_match, context)
                        resolved_command, _ = resolve_command(var_value, context)
                        context['vars'][var_name] = resolved_command

                    resolved_sources = []

                    # Match source statements
                    source_matches = SOURCE_PATTERN.findall(command)
                    command_contains_source = bool(source_matches) or contains_source_command(command)
                    if command_contains_source and mode == "executable" and is_unsupported_control_flow_source(
                        command,
                        command_control_depth,
                    ):
                        raise unsupported_source_error(
                            script_path,
                            num,
                            line,
                            command,
                            "unsupported.source.control-flow",
                            "unsupported source in control flow",
                            "Move source resolution outside unsupported control flow or wait for IR evaluation support.",
                        )

                    for _, source_command, source_path in source_matches:
                        source_site = f"{source_command} {source_path.strip()}"
                        try:
                            resolved_source = SOURCE_RESOLVER.resolve_source_expression(source_path, source_site, context)
                        except UnsupportedSourceError as exc:
                            raise with_source_diagnostic(
                                exc,
                                script_path,
                                num,
                                line,
                                source_site,
                                "unsupported.source.resolution",
                            ) from exc
                        if resolved_source:
                            resolved_sources.append(resolved_source)
                        elif mode == "executable":
                            raise unsupported_source_error(
                                script_path,
                                num,
                                line,
                                source_site,
                                "unsupported.source.unresolved",
                                "unsupported unresolved source",
                                "Use a statically resolvable source path or context mode.",
                            )

                    try:
                        resolved_sources.extend(SOURCE_RESOLVER.resolve_command_level_sources(command, context, mode))
                    except UnsupportedSourceError as exc:
                        raise with_source_diagnostic(
                            exc,
                            script_path,
                            num,
                            line,
                            command,
                            "unsupported.source.command-resolution",
                        ) from exc

                    if command_contains_source and not source_matches and not resolved_sources and mode == "executable":
                        raise unsupported_source_error(
                            script_path,
                            num,
                            line,
                            command,
                            "unsupported.source.command-unresolved",
                            "unsupported unresolved source command",
                            "Use a direct source command or a supported dynamic source expression.",
                        )

                    if not resolved_sources and not source_matches and is_unsupported_dynamic_source(command):
                        raise unsupported_source_error(
                            script_path,
                            num,
                            line,
                            command,
                            "unsupported.source.dynamic",
                            "unsupported dynamic source command",
                            "Keep dynamic source discovery inside the documented safe subset.",
                        )

                    for resolved_source in resolved_sources:
                        context['source_declarations'][script_path][num].append(resolved_source)
                        extract_sources_and_variables(
                            resolved_source.path, context, sources, seen_sources, references, mode=mode
                        )
                        context['vars']['BASH_SOURCE'] = os.path.abspath(script_path)
                        if seen_sources[resolved_source.path][script_path] == 1:
                            sources.append(resolved_source.path)

                    if starts_unsupported_control_block(command):
                        control_depth += 1
                    elif ends_unsupported_control_block(command):
                        control_depth = max(0, control_depth - 1)

                active_heredocs.extend(extract_heredoc_delimiters(line))
    finally:
        if previous_bash_source is None:
            context['vars'].pop('BASH_SOURCE', None)
        else:
            context['vars']['BASH_SOURCE'] = previous_bash_source

    return sources


def get_sources(entrypoint, mode="executable"):
    sources = []

    # Initialize context with the entry point
    current_directory = os.path.abspath(os.path.dirname(entrypoint))
    context = {
        'vars': {'0': os.path.abspath(entrypoint)},
        'current_directory': current_directory,
        'source_declarations': {}}
    change_directory(current_directory, context)

    extract_sources_and_variables(entrypoint, context, sources, seen_sources={}, mode=mode)
    sources.append(entrypoint)
    return sources, context
