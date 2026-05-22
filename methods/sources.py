import os
import re
import shlex
from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatch

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
    create_command_pattern,
)

RECURSION_LIMIT = 2


class UnsupportedSourceError(NotImplementedError):
    pass


@dataclass(frozen=True)
class ResolvedSource:
    path: str
    source_expression: str
    source_site: str
    execution_model: str = "parent-source"
    confidence: str = "exact"
    replacement_kind: str = "source"


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


def get_commands(line: str):
    commands = []
    current = []
    in_single_quote = False
    in_double_quote = False
    escaped = False
    index = 0

    def append_current_command():
        command = ''.join(current).strip()
        if command:
            commands.append(command)
        current.clear()

    while index < len(line):
        char = line[index]
        if escaped:
            current.append(char)
            escaped = False
            index += 1
            continue

        if char == '\\' and not in_single_quote:
            current.append(char)
            escaped = True
            index += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(char)
            index += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(char)
            index += 1
            continue

        if char == '#' and not in_single_quote and not in_double_quote:
            if not current or current[-1].isspace():
                break

        if char == ';' and not in_single_quote and not in_double_quote:
            append_current_command()
            index += 1
            continue

        if (
            not in_single_quote
            and not in_double_quote
            and (line.startswith('&&', index) or line.startswith('||', index))
        ):
            append_current_command()
            index += 2
            continue

        current.append(char)
        index += 1

    append_current_command()

    return commands


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


def is_unsupported_dynamic_source(command: str, source_path: str | None = None):
    stripped_command = command.strip()
    source_path = source_path or ""

    if "`" in source_path:
        return True

    if re.search(r'\$\(\s*(?!dirname\b|basename\b|realpath\b)', source_path):
        return True

    if re.match(r'^(eval|bash\s+-c)\b', stripped_command) and re.search(r'\bsource\b|\.\s+', stripped_command):
        return True

    return False


def parse_shell_words(command: str):
    try:
        return shlex.split(command, posix=True)
    except ValueError as exc:
        raise UnsupportedSourceError(f"unsupported source command syntax: {command.strip()} ({exc})") from exc


def has_unsupported_shell_operator(command: str):
    return bool(re.search(r'(?<!\\)(?:[|;&<>]|\n)', command))


def extract_exact_command_substitution(source_expression: str):
    expression = strip_matching_quotes(source_expression.strip())
    if not expression.startswith('$(') or not expression.endswith(')'):
        return None

    inner_command = expression[2:-1].strip()
    if not inner_command:
        raise UnsupportedSourceError(f"unsupported empty source command substitution: {source_expression.strip()}")

    if '$(' in inner_command or '`' in inner_command:
        raise UnsupportedSourceError(f"unsupported nested source command substitution: {source_expression.strip()}")

    return inner_command


def resolve_safe_cat_source(inner_command: str, source_expression: str, source_site: str, context: dict,
                            execution_model: str, replacement_kind: str):
    if has_unsupported_shell_operator(inner_command):
        raise UnsupportedSourceError(f"unsupported cat source command syntax: {source_site.strip()}")

    words = parse_shell_words(inner_command)
    if len(words) != 2 or words[0] != 'cat' or words[1].startswith('-'):
        raise UnsupportedSourceError(f"unsupported cat source command: {source_site.strip()}")

    path_file = resolve_path(words[1], context)
    if not path_file or not os.path.isfile(path_file):
        raise UnsupportedSourceError(f"unsupported cat source path file: {words[1]}")

    with open(path_file, 'r') as file:
        lines = file.read().splitlines()

    if len(lines) != 1 or not lines[0].strip():
        raise UnsupportedSourceError(f"ambiguous cat source output: {source_site.strip()}")

    resolved_path = resolve_path(lines[0].strip(), context)
    if not resolved_path:
        raise UnsupportedSourceError(f"unsupported cat-resolved source path: {lines[0].strip()}")

    return ResolvedSource(
        path=resolved_path,
        source_expression=source_expression.strip(),
        source_site=source_site.strip(),
        execution_model=execution_model,
        replacement_kind=replacement_kind,
    )


def parse_find_command(words: list[str], context: dict):
    if not words or words[0] != 'find':
        return None

    roots = []
    index = 1
    while index < len(words) and not words[index].startswith('-'):
        roots.append(words[index])
        index += 1

    if not roots:
        roots = ['.']

    resolved_roots = []
    for root in roots:
        resolved_root = resolve_path(root, context)
        if not resolved_root or not os.path.isdir(resolved_root):
            raise UnsupportedSourceError(f"unsupported find source root: {root}")
        resolved_roots.append(resolved_root)

    filters = {
        'name': [],
        'path': [],
        'maxdepth': None,
        'mindepth': 0,
        'has_print': False,
    }

    while index < len(words):
        token = words[index]
        if token == '-name':
            index += 1
            if index >= len(words):
                raise UnsupportedSourceError("unsupported find source command: missing -name pattern")
            filters['name'].append(words[index])
        elif token == '-path':
            index += 1
            if index >= len(words):
                raise UnsupportedSourceError("unsupported find source command: missing -path pattern")
            filters['path'].append(words[index])
        elif token == '-type':
            index += 1
            if index >= len(words) or words[index] != 'f':
                raise UnsupportedSourceError("unsupported find source command: only -type f is supported")
        elif token == '-maxdepth':
            index += 1
            if index >= len(words) or not words[index].isdigit():
                raise UnsupportedSourceError("unsupported find source command: invalid -maxdepth")
            filters['maxdepth'] = int(words[index])
        elif token == '-mindepth':
            index += 1
            if index >= len(words) or not words[index].isdigit():
                raise UnsupportedSourceError("unsupported find source command: invalid -mindepth")
            filters['mindepth'] = int(words[index])
        elif token == '-print':
            filters['has_print'] = True
        elif token == '-quit':
            if not filters['has_print']:
                raise UnsupportedSourceError("unsupported find source command: -quit requires earlier -print")
        else:
            raise UnsupportedSourceError(f"unsupported find source predicate: {token}")
        index += 1

    return resolved_roots, filters


def find_candidate_matches(roots: list[str], filters: dict, context: dict):
    matches = set()
    current_directory = context['current_directory']

    for root in roots:
        for directory, dirnames, filenames in os.walk(root):
            dirnames.sort()
            filenames.sort()

            relative_directory = os.path.relpath(directory, root)
            directory_depth = 0 if relative_directory == os.curdir else len(relative_directory.split(os.sep))
            maxdepth = filters['maxdepth']
            if maxdepth is not None and directory_depth >= maxdepth:
                dirnames[:] = []

            for filename in filenames:
                candidate = os.path.join(directory, filename)
                candidate_depth = directory_depth + 1
                if candidate_depth < filters['mindepth']:
                    continue
                if maxdepth is not None and candidate_depth > maxdepth:
                    continue
                if not os.path.isfile(candidate):
                    continue
                if filters['name'] and not any(fnmatch(filename, pattern) for pattern in filters['name']):
                    continue

                relative_to_current = os.path.relpath(candidate, current_directory)
                path_variants = {
                    candidate,
                    relative_to_current,
                    f"./{relative_to_current}" if not relative_to_current.startswith(os.pardir) else relative_to_current,
                }
                if filters['path'] and not any(
                    fnmatch(path_variant, pattern)
                    for pattern in filters['path']
                    for path_variant in path_variants
                ):
                    continue

                matches.add(os.path.abspath(candidate))
                if len(matches) > 1:
                    return sorted(matches)

    return sorted(matches)


def resolve_safe_find_source(inner_command: str, source_expression: str, source_site: str, context: dict,
                             execution_model: str, replacement_kind: str):
    if has_unsupported_shell_operator(inner_command):
        raise UnsupportedSourceError(f"unsupported find source command syntax: {source_site.strip()}")

    words = parse_shell_words(inner_command)
    parsed_find = parse_find_command(words, context)
    if not parsed_find:
        return None

    roots, filters = parsed_find
    matches = find_candidate_matches(roots, filters, context)
    if len(matches) != 1:
        raise UnsupportedSourceError(f"ambiguous find source output: {source_site.strip()}")

    return ResolvedSource(
        path=matches[0],
        source_expression=source_expression.strip(),
        source_site=source_site.strip(),
        execution_model=execution_model,
        replacement_kind=replacement_kind,
    )


def resolve_source_expression(source_expression: str, source_site: str, context: dict,
                              execution_model: str = "parent-source", replacement_kind: str = "source"):
    if '`' in source_expression:
        raise UnsupportedSourceError(f"unsupported backtick source command: {source_site.strip()}")

    if resolved_path := resolve_path(source_expression, context):
        return ResolvedSource(
            path=resolved_path,
            source_expression=source_expression.strip(),
            source_site=source_site.strip(),
            execution_model=execution_model,
            replacement_kind=replacement_kind,
        )

    inner_command = extract_exact_command_substitution(source_expression)
    if inner_command:
        words = parse_shell_words(inner_command)
        if not words:
            raise UnsupportedSourceError(f"unsupported empty source command substitution: {source_site.strip()}")

        resolver = SOURCE_COMMAND_SUBSTITUTION_RESOLVERS.get(words[0])
        if resolver:
            return resolver(
                inner_command, source_expression, source_site, context, execution_model, replacement_kind
            )
        raise UnsupportedSourceError(f"unsupported source command substitution: {source_site.strip()}")

    if is_unsupported_dynamic_source(source_site, source_expression):
        raise UnsupportedSourceError(f"unsupported dynamic source command: {source_site.strip()}")

    return None


def resolve_single_source_payload(payload: str, source_site: str, context: dict,
                                  execution_model: str, replacement_kind: str):
    if '$(' in payload or '`' in payload:
        raise UnsupportedSourceError(f"unsupported nested dynamic source command: {source_site.strip()}")
    if has_unsupported_shell_operator(payload):
        raise UnsupportedSourceError(f"unsupported source command syntax: {source_site.strip()}")

    payload_commands = get_commands(payload)
    if len(payload_commands) != 1:
        raise UnsupportedSourceError(f"unsupported multi-command source payload: {source_site.strip()}")

    source_matches = SOURCE_PATTERN.findall(payload_commands[0])
    if len(source_matches) != 1:
        raise UnsupportedSourceError(f"unsupported source payload: {source_site.strip()}")

    _, _, nested_source_expression = source_matches[0]
    return resolve_source_expression(
        nested_source_expression,
        source_site,
        context,
        execution_model=execution_model,
        replacement_kind=replacement_kind,
    )


def has_source_command(payload: str):
    return bool(SOURCE_PATTERN.findall(payload))


SOURCE_COMMAND_SUBSTITUTION_RESOLVERS = {
    'cat': resolve_safe_cat_source,
    'find': resolve_safe_find_source,
}

BASH_COMMAND_PATTERN = create_command_pattern(r'bash|/bin/bash|/usr/bin/bash', regex=True)
COMMAND_LEVEL_SOURCE_PATTERNS = (
    ('eval', None),
    (r'bash|/bin/bash|/usr/bin/bash', BASH_COMMAND_PATTERN),
)


def resolve_eval_source_command(command: str, context: dict, _mode: str):
    stripped_command = command.strip()
    if not re.match(r'^eval\b', stripped_command):
        return None

    words = parse_shell_words(stripped_command)
    if len(words) != 2 or words[0] != 'eval':
        raise UnsupportedSourceError(f"unsupported eval source command: {stripped_command}")

    payload = os.path.expandvars(resolve_variable_references(words[1], context))
    if not has_source_command(payload):
        return None

    return resolve_single_source_payload(
        payload,
        stripped_command,
        context,
        execution_model="parent-source",
        replacement_kind="command",
    )


def resolve_bash_c_source_command(command: str, context: dict, mode: str):
    stripped_command = command.strip()
    if not re.match(r'^(?:bash|/bin/bash|/usr/bin/bash)\b', stripped_command):
        return None

    words = parse_shell_words(stripped_command)
    if len(words) != 3 or words[1] != '-c':
        return None

    payload = os.path.expandvars(resolve_variable_references(words[2], context))
    if not has_source_command(payload):
        return None

    if mode != "context":
        raise UnsupportedSourceError(f"unsupported child-shell source command in executable mode: {stripped_command}")

    return resolve_single_source_payload(
        payload,
        stripped_command,
        context,
        execution_model="child-shell",
        replacement_kind="context",
    )


def resolve_command_level_source(command: str, context: dict, mode: str):
    for resolver in COMMAND_LEVEL_SOURCE_RESOLVERS:
        resolved_source = resolver(command, context, mode)
        if resolved_source:
            return resolved_source

    return None


def resolve_command_level_sources(command: str, context: dict, mode: str):
    resolved_sources = []
    seen_commands = set()

    for command_name, pattern in COMMAND_LEVEL_SOURCE_PATTERNS:
        matches = extract_bash_commands(
            command_name,
            command,
            pattern=pattern,
            include_separator=True,
            strip=True,
        )
        for _, matched_command, arguments in matches:
            source_command = f"{matched_command} {arguments}".strip()
            if source_command in seen_commands:
                continue
            seen_commands.add(source_command)

            resolved_source = resolve_command_level_source(source_command, context, mode)
            if resolved_source:
                resolved_sources.append(resolved_source)

    return resolved_sources


COMMAND_LEVEL_SOURCE_RESOLVERS = (
    resolve_eval_source_command,
    resolve_bash_c_source_command,
)


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
        with open(script_path, 'r') as file:
            for num, line in enumerate(file):
                for command in get_commands(line):
                    # Skip commands that are quoted strings rather than shell commands.
                    if not command or re.match(r'\s*["\']', command):
                        continue

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
                    for _, source_command, source_path in source_matches:
                        source_site = f"{source_command} {source_path.strip()}"
                        resolved_source = resolve_source_expression(source_path, source_site, context)
                        if resolved_source:
                            resolved_sources.append(resolved_source)

                    resolved_sources.extend(resolve_command_level_sources(command, context, mode))

                    if not resolved_sources and not source_matches and is_unsupported_dynamic_source(command):
                        raise UnsupportedSourceError(f"unsupported dynamic source command: {command.strip()}")

                    for resolved_source in resolved_sources:
                        context['source_declarations'][script_path][num].append(resolved_source)
                        extract_sources_and_variables(
                            resolved_source.path, context, sources, seen_sources, references, mode=mode
                        )
                        context['vars']['BASH_SOURCE'] = os.path.abspath(script_path)
                        if seen_sources[resolved_source.path][script_path] == 1:
                            sources.append(resolved_source.path)
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
