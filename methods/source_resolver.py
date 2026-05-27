import glob
import os
import re
from dataclasses import dataclass
from fnmatch import fnmatch, fnmatchcase

from methods.regex.patterns import SOURCE_PATTERN, create_command_pattern
from methods.regex.utilities import extract_bash_commands, strip_matching_quotes
from methods.shell_line import get_commands

ASSIGNMENT_WORD_PATTERN = re.compile(r'^[a-zA-Z_]\w*(?:\+)?=.*$')
BASH_COMMAND_PATTERN = create_command_pattern(r'bash|/bin/bash|/usr/bin/bash', regex=True)
UNSUPPORTED_GLOB_OPTIONS = frozenset({
    'extglob',
})
COMMAND_LEVEL_SOURCE_PATTERNS = (
    ('eval', None),
    (r'bash|/bin/bash|/usr/bin/bash', BASH_COMMAND_PATTERN),
)


class UnsupportedSourceError(NotImplementedError):
    def __init__(self, message: str | None = None, *, diagnostic=None, code: str | None = None,
                 hint: str | None = None, details: dict | None = None):
        if diagnostic is not None and message is None:
            message = f"{diagnostic.message}: {diagnostic.fragment}"
        super().__init__(message or "unsupported source")
        self.diagnostic = diagnostic
        self.code = diagnostic.code if diagnostic is not None else code
        self.hint = diagnostic.hint if diagnostic is not None else hint
        self.details = diagnostic.details if diagnostic is not None else (details or {})

    def with_diagnostic(self, diagnostic):
        if self.diagnostic is not None:
            return self
        return UnsupportedSourceError(str(self), diagnostic=diagnostic, code=self.code, hint=self.hint)


@dataclass(frozen=True)
class ResolvedSource:
    path: str
    source_expression: str
    source_site: str
    execution_model: str = "parent-source"
    confidence: str = "exact"
    replacement_kind: str = "source"
    source_value: str | None = None
    source_arguments: tuple[str, ...] | None = None
    source_column: int | None = None
    occurrence_model: str | None = None
    condition: str | None = None
    positional_assignment_generation: int | None = None


@dataclass(frozen=True)
class GlobMatch:
    word: str
    path: str


@dataclass(frozen=True)
class HeredocDelimiter:
    value: str
    strip_tabs: bool = False


def extract_heredoc_delimiters(line: str):
    delimiters = []
    in_single_quote = False
    in_double_quote = False
    escaped = False
    arithmetic_depth = 0
    index = 0

    while index < len(line):
        char = line[index]

        if escaped:
            escaped = False
            index += 1
            continue

        if char == '\\' and not in_single_quote:
            escaped = True
            index += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            index += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            index += 1
            continue

        if in_single_quote or in_double_quote:
            index += 1
            continue

        if arithmetic_depth:
            if line.startswith('))', index):
                arithmetic_depth -= 1
                index += 2
            else:
                index += 1
            continue

        if line.startswith('$((', index):
            arithmetic_depth += 1
            index += 3
            continue

        if line.startswith('((', index) and (index == 0 or line[index - 1].isspace() or line[index - 1] in ';|&'):
            arithmetic_depth += 1
            index += 2
            continue

        if line.startswith('<<', index) and not line.startswith('<<<', index):
            delimiter_start = index + 2
            strip_tabs = False
            if delimiter_start < len(line) and line[delimiter_start] == '-':
                strip_tabs = True
                delimiter_start += 1

            while delimiter_start < len(line) and line[delimiter_start].isspace():
                delimiter_start += 1

            if delimiter_start >= len(line):
                break

            quote = line[delimiter_start] if line[delimiter_start] in {'"', "'"} else ''
            if quote:
                delimiter_end = line.find(quote, delimiter_start + 1)
                if delimiter_end < 0:
                    break
                delimiter = line[delimiter_start + 1:delimiter_end]
                index = delimiter_end + 1
            else:
                delimiter_end = delimiter_start
                while delimiter_end < len(line) and not line[delimiter_end].isspace() and line[delimiter_end] not in ';|&<>':
                    delimiter_end += 1
                delimiter = line[delimiter_start:delimiter_end]
                index = delimiter_end

            if delimiter:
                delimiters.append(HeredocDelimiter(delimiter, strip_tabs))
            continue

        index += 1

    return delimiters


def is_heredoc_end(line: str, heredoc: HeredocDelimiter):
    candidate = line.rstrip('\n')
    if heredoc.strip_tabs:
        candidate = candidate.lstrip('\t')
    return candidate == heredoc.value


def parse_shell_words(command: str):
    return [strip_shell_word_quotes(word) for word in parse_shell_words_preserving_quotes(command)]


def strip_shell_word_quotes(word: str):
    output = []
    in_single_quote = False
    in_double_quote = False
    escaped = False

    for char in word:
        if escaped:
            output.append(char)
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

        output.append(char)

    return ''.join(output)


def parse_shell_words_preserving_quotes(command: str):
    words = []
    current = []
    in_single_quote = False
    in_double_quote = False
    escaped = False
    index = 0
    current_started = False

    while index < len(command):
        char = command[index]
        if escaped:
            current.append(char)
            escaped = False
            current_started = True
            index += 1
            continue

        if char == '\\' and not in_single_quote:
            current.append(char)
            escaped = True
            current_started = True
            index += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(char)
            current_started = True
            index += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(char)
            current_started = True
            index += 1
            continue

        if not in_single_quote and command.startswith('$(', index):
            body, end_index = _read_balanced_body(command, index + 2)
            if end_index is None:
                raise UnsupportedSourceError(
                    f"unsupported source command syntax: {command.strip()} (unterminated command substitution)"
                )
            current.append(f"$({body})")
            current_started = True
            index = end_index + 1
            continue

        if not in_single_quote and char == '`':
            body, end_index = _read_backtick_body(command, index + 1)
            if body is None:
                raise UnsupportedSourceError(
                    f"unsupported source command syntax: {command.strip()} (unterminated backtick substitution)"
                )
            current.append(f"`{body}`")
            current_started = True
            index = end_index + 1
            continue

        if char.isspace() and not in_single_quote and not in_double_quote:
            word = ''.join(current).strip()
            if current_started:
                words.append(word)
            current = []
            current_started = False
            index += 1
            continue

        current.append(char)
        current_started = True
        index += 1

    if escaped or in_single_quote or in_double_quote:
        raise UnsupportedSourceError(f"unsupported source command syntax: {command.strip()} (unterminated quote)")

    word = ''.join(current).strip()
    if current_started:
        words.append(word)

    return words


def contains_unquoted_token(text: str, token: str):
    in_single_quote = False
    in_double_quote = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue

        if char == '\\' and not in_single_quote:
            escaped = True
            index += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            index += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            index += 1
            continue

        if not in_single_quote and not in_double_quote and text.startswith(token, index):
            return True

        index += 1

    return False


def has_unquoted_glob(text: str):
    in_single_quote = False
    in_double_quote = False
    escaped = False

    for char in text:
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

        if not in_single_quote and not in_double_quote and char in {'*', '?', '['}:
            return True

    return False


def has_unquoted_extglob(text: str):
    return any(contains_unquoted_token(text, token) for token in {"@(", "?(", "*(", "+(", "!("})


def has_unquoted_brace_expansion(text: str):
    return contains_unquoted_token(text, "{") and contains_unquoted_token(text, "}")


def _brace_expand(pattern: str, raw_pattern: str, source_site: str):
    if not has_unquoted_brace_expansion(raw_pattern):
        return [pattern]
    return _brace_expand_pattern(pattern, source_site)


def _brace_expand_pattern(pattern: str, source_site: str):
    start = pattern.find("{")
    if start < 0:
        return [pattern]

    depth = 0
    end = -1
    for index in range(start, len(pattern)):
        char = pattern[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break

    if end < 0:
        raise UnsupportedSourceError(f"unsupported brace source pattern: {source_site.strip()}")

    body = pattern[start + 1:end]
    if "{" in body or "}" in body:
        raise UnsupportedSourceError(f"unsupported nested brace source pattern: {source_site.strip()}")
    sequence_options = _brace_sequence_options(body)
    if sequence_options is not None:
        options = sequence_options
    elif "," in body:
        options = body.split(",")
    else:
        return [pattern]

    expanded = []
    for option in options:
        expanded.extend(_brace_expand_pattern(f"{pattern[:start]}{option}{pattern[end + 1:]}", source_site))
    return expanded


def _brace_sequence_options(body: str):
    match = re.fullmatch(r'(-?\d+)\.\.(-?\d+)(?:\.\.(-?\d+))?', body)
    if match:
        start_text, end_text, step_text = match.groups()
        start = int(start_text)
        end = int(end_text)
        if step_text is None:
            step = 1 if start <= end else -1
        else:
            step = abs(int(step_text))
            if step == 0:
                return None
            if start > end:
                step = -step
        width = max(len(start_text.lstrip("-")), len(end_text.lstrip("-")))
        zero_padded = (
            len(start_text.lstrip("-")) > 1 and start_text.lstrip("-").startswith("0")
        ) or (
            len(end_text.lstrip("-")) > 1 and end_text.lstrip("-").startswith("0")
        )
        stop = end + (1 if step > 0 else -1)
        values = []
        for value in range(start, stop, step):
            if zero_padded:
                sign = "-" if value < 0 else ""
                values.append(f"{sign}{abs(value):0{width}d}")
            else:
                values.append(str(value))
        return values

    match = re.fullmatch(r'([A-Za-z])\.\.([A-Za-z])(?:\.\.(-?\d+))?', body)
    if match:
        start_text, end_text, step_text = match.groups()
        start = ord(start_text)
        end = ord(end_text)
        if step_text is None:
            step = 1 if start <= end else -1
        else:
            step = abs(int(step_text))
            if step == 0:
                return None
            if start > end:
                step = -step
        stop = end + (1 if step > 0 else -1)
        return [chr(value) for value in range(start, stop, step)]

    return None


def _glob_matches(pattern: str, current_directory: str, glob_options: set[str], include_hidden: bool):
    if include_hidden or 'nocaseglob' in glob_options:
        return _manual_glob_matches(pattern, current_directory, glob_options, include_hidden)

    recursive = 'globstar' in glob_options
    if os.path.isabs(pattern):
        return sorted(glob.glob(pattern, recursive=recursive))
    return sorted(glob.glob(
        pattern,
        root_dir=current_directory,
        recursive=recursive,
    ))


def _manual_glob_matches(pattern: str, current_directory: str, glob_options: set[str], include_hidden: bool):
    absolute_pattern = pattern if os.path.isabs(pattern) else os.path.join(current_directory, pattern)
    absolute_pattern = os.path.normpath(absolute_pattern)
    root, pattern_parts = _glob_static_root(absolute_pattern)
    if not os.path.isdir(root):
        return []

    recursive = 'globstar' in glob_options and '**' in pattern_parts
    max_depth = None if recursive else len(pattern_parts)
    matches = []

    for directory, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        relative_directory = os.path.relpath(directory, root)
        directory_parts = [] if relative_directory == os.curdir else relative_directory.split(os.sep)

        if max_depth is not None and len(directory_parts) >= max_depth:
            dirnames[:] = []

        for name in [*dirnames, *filenames]:
            candidate_parts = [*directory_parts, name]
            if max_depth is not None and len(candidate_parts) > max_depth:
                continue
            if not _glob_parts_match(pattern_parts, candidate_parts, glob_options, include_hidden):
                continue
            candidate = os.path.join(root, *candidate_parts)
            matches.append(candidate if os.path.isabs(pattern) else _relative_glob_word(candidate, current_directory, pattern))

    return sorted(matches)


def _glob_static_root(absolute_pattern: str):
    drive, tail = os.path.splitdrive(absolute_pattern)
    parts = [part for part in tail.split(os.sep) if part]
    root_parts = []
    while parts and not _glob_segment_has_magic(parts[0]):
        root_parts.append(parts.pop(0))

    root = drive + os.sep + os.path.join(*root_parts) if root_parts else drive + os.sep
    return os.path.normpath(root), parts


def _glob_segment_has_magic(segment: str):
    return any(char in segment for char in "*?[")


def _glob_parts_match(pattern_parts: list[str], candidate_parts: list[str], glob_options: set[str],
                      include_hidden: bool):
    if not pattern_parts:
        return not candidate_parts

    pattern = pattern_parts[0]
    if pattern == "**" and "globstar" in glob_options:
        if _glob_parts_match(pattern_parts[1:], candidate_parts, glob_options, include_hidden):
            return True
        if not candidate_parts:
            return False
        if _hidden_glob_segment_blocked(pattern, candidate_parts[0], include_hidden):
            return False
        return _glob_parts_match(pattern_parts, candidate_parts[1:], glob_options, include_hidden)

    if not candidate_parts:
        return False
    if _hidden_glob_segment_blocked(pattern, candidate_parts[0], include_hidden):
        return False
    if not _glob_segment_matches(pattern, candidate_parts[0], glob_options):
        return False
    return _glob_parts_match(pattern_parts[1:], candidate_parts[1:], glob_options, include_hidden)


def _hidden_glob_segment_blocked(pattern: str, candidate: str, include_hidden: bool):
    return candidate.startswith(".") and not include_hidden and not pattern.startswith(".")


def _glob_segment_matches(pattern: str, candidate: str, glob_options: set[str]):
    if 'nocaseglob' in glob_options:
        return fnmatchcase(candidate.lower(), pattern.lower())
    return fnmatchcase(candidate, pattern)


def _relative_glob_word(path: str, current_directory: str, pattern: str):
    relative = os.path.relpath(path, current_directory)
    if pattern.startswith("./") and not relative.startswith(os.pardir):
        return f"./{relative}"
    return relative


def _globignore_patterns(context: dict):
    globignore = context.get('runtime_vars', context.get('vars', {})).get('GLOBIGNORE', '')
    if not globignore:
        return []
    return [pattern for pattern in globignore.split(":") if pattern]


def _apply_globignore(matches: list[str], patterns: list[str]):
    if not patterns:
        return matches
    return [
        match
        for match in matches
        if not any(fnmatchcase(match, pattern) for pattern in patterns)
    ]


def expand_glob_word(pattern: str, context: dict, source_site: str, raw_pattern: str | None = None):
    raw_pattern = raw_pattern if raw_pattern is not None else pattern

    glob_options = set(context.get('glob_options', set()))
    enabled_unsupported_options = sorted(glob_options & UNSUPPORTED_GLOB_OPTIONS)
    if enabled_unsupported_options:
        option_list = ', '.join(enabled_unsupported_options)
        raise UnsupportedSourceError(f"unsupported glob shell option {option_list}: {source_site.strip()}")

    if 'noglob' in context.get('shell_options', set()):
        raise UnsupportedSourceError(f"unsupported noglob source pattern: {source_site.strip()}")

    current_directory = context['current_directory']
    globignore_patterns = _globignore_patterns(context)
    include_hidden = 'dotglob' in glob_options or bool(globignore_patterns)
    matches = []
    for expanded_pattern in _brace_expand(pattern, raw_pattern, source_site):
        pattern_matches = _glob_matches(expanded_pattern, current_directory, glob_options, include_hidden)
        filtered_matches = _apply_globignore(pattern_matches, globignore_patterns)
        if not filtered_matches and pattern_matches and 'nullglob' not in glob_options:
            raise UnsupportedSourceError(f"unsupported GLOBIGNORE source pattern: {source_site.strip()}")
        matches.extend(filtered_matches)

    if not matches:
        if 'nullglob' in glob_options:
            return ()
        raise UnsupportedSourceError(f"unsupported unmatched source glob: {source_site.strip()}")

    glob_matches = []
    for match in matches:
        path = match if os.path.isabs(match) else os.path.join(current_directory, match)
        resolved_path = os.path.abspath(path)
        if not os.path.isfile(resolved_path):
            raise UnsupportedSourceError(f"unsupported non-file source glob match: {source_site.strip()}")
        glob_matches.append(GlobMatch(word=match, path=resolved_path))

    return tuple(glob_matches)


def source_command_index(command: str):
    try:
        words = parse_shell_words(command)
    except UnsupportedSourceError:
        return 0 if SOURCE_PATTERN.findall(command) else None

    command_start = 0
    while command_start < len(words) and ASSIGNMENT_WORD_PATTERN.match(words[command_start]):
        command_start += 1
    while command_start < len(words) and words[command_start] == "!":
        command_start += 1

    for index, word in enumerate(words):
        if word not in {'source', '.'}:
            continue

        if index == command_start:
            return index

        first_word = words[command_start] if command_start < len(words) else ''
        previous_word = words[index - 1]
        if first_word == 'builtin' and index == command_start + 1:
            return index
        if first_word == 'command':
            command_index = command_start + 1
            while command_index < len(words) and words[command_index].startswith('-'):
                option = words[command_index]
                if option == '--':
                    command_index += 1
                    break
                if 'v' in option[1:] or 'V' in option[1:]:
                    return None
                if set(option[1:]) != {'p'}:
                    return None
                command_index += 1
            if index == command_index:
                return index
        if first_word in {'if', 'while', 'until', 'then', 'elif', 'else', 'do'}:
            branch_index = command_start + 1
            while branch_index < len(words) and ASSIGNMENT_WORD_PATTERN.match(words[branch_index]):
                branch_index += 1
            while branch_index < len(words) and words[branch_index] == "!":
                branch_index += 1
            if index == branch_index:
                return index
        if previous_word == '{' or previous_word.endswith('{'):
            return index
        if any(candidate.endswith(')') for candidate in words[command_start:index]):
            return index

    return None


def contains_source_command(command: str):
    return source_command_index(command) is not None


def contains_nested_source_command(command: str):
    """Detect live source commands inside shell constructs we do not lower.

    This intentionally does not treat quoted text as shell code, but it does
    inspect command substitutions, process substitutions, and parenthesized
    subshells because those run nested shell code at runtime.
    """
    return _contains_nested_source_command(command, depth=0)


def _contains_nested_source_command(text: str, depth: int):
    if depth > 8:
        return True

    in_single_quote = False
    in_double_quote = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue

        if char == '\\' and not in_single_quote:
            escaped = True
            index += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            index += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            index += 1
            continue

        if in_single_quote:
            index += 1
            continue

        if char == '`':
            body, end_index = _read_backtick_body(text, index + 1)
            if body is None:
                return True
            if _shell_body_contains_source(body, depth + 1):
                return True
            index = end_index + 1
            continue

        if text.startswith('$((', index):
            body, end_index = _read_balanced_body(text, index + 3)
            if end_index is None:
                return True
            if _contains_nested_source_command(body, depth + 1):
                return True
            index = end_index + 1
            continue

        if text.startswith('$(', index):
            body, end_index = _read_balanced_body(text, index + 2)
            if end_index is None:
                return True
            if _shell_body_contains_source(body, depth + 1):
                return True
            index = end_index + 1
            continue

        if not in_double_quote and (text.startswith('<(', index) or text.startswith('>(', index)):
            body, end_index = _read_balanced_body(text, index + 2)
            if end_index is None:
                return True
            if _shell_body_contains_source(body, depth + 1):
                return True
            index = end_index + 1
            continue

        if not in_double_quote and text.startswith('((', index):
            body, end_index = _read_balanced_body(text, index + 2)
            if end_index is None:
                return True
            if _contains_nested_source_command(body, depth + 1):
                return True
            index = end_index + 1
            continue

        if not in_double_quote and char == '(' and _is_array_assignment_paren(text, index):
            body, end_index = _read_balanced_body(text, index + 1)
            if end_index is None:
                return True
            index = end_index + 1
            continue

        if not in_double_quote and char == '(':
            body, end_index = _read_balanced_body(text, index + 1)
            if end_index is None:
                return True
            if _shell_body_contains_source(body, depth + 1):
                return True
            index = end_index + 1
            continue

        index += 1

    return False


def _shell_body_contains_source(body: str, depth: int):
    for line in body.splitlines() or [body]:
        if any(contains_source_command(command) for command in get_commands(line)):
            return True
    return _contains_nested_source_command(body, depth)


def _is_array_assignment_paren(text: str, paren_index: int):
    if paren_index == 0 or text[paren_index - 1] != '=':
        return False

    word_start = paren_index - 2
    while word_start >= 0 and not text[word_start].isspace() and text[word_start] not in ';&|':
        word_start -= 1

    assignment_name = text[word_start + 1:paren_index - 1]
    return bool(re.fullmatch(r'[a-zA-Z_]\w*(?:\[[^\]]+\])?\+?', assignment_name))


def _read_backtick_body(text: str, start_index: int):
    body = []
    escaped = False
    index = start_index

    while index < len(text):
        char = text[index]
        if escaped:
            body.append(char)
            escaped = False
            index += 1
            continue

        if char == '\\':
            body.append(char)
            escaped = True
            index += 1
            continue

        if char == '`':
            return ''.join(body), index

        body.append(char)
        index += 1

    return None, None


def _read_balanced_body(text: str, start_index: int):
    body = []
    in_single_quote = False
    in_double_quote = False
    escaped = False
    depth = 1
    index = start_index

    while index < len(text):
        char = text[index]
        if escaped:
            body.append(char)
            escaped = False
            index += 1
            continue

        if char == '\\' and not in_single_quote:
            body.append(char)
            escaped = True
            index += 1
            continue

        if char == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            body.append(char)
            index += 1
            continue

        if char == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            body.append(char)
            index += 1
            continue

        if not in_single_quote and not in_double_quote:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    return ''.join(body), index

        body.append(char)
        index += 1

    return None, None


def starts_unsupported_control_block(command: str):
    return bool(re.match(r'^\s*(?:if|for|while|until|case|select)\b', command))


def ends_unsupported_control_block(command: str):
    return bool(re.match(r'^\s*(?:fi|done|esac)\b', command))


def is_control_branch_command(command: str):
    stripped_command = command.strip()
    if re.match(r'^(?:then|elif|else|do)\b', stripped_command):
        return True
    return bool(re.match(r'^[^#\s;]+\)\s+', stripped_command))


def is_unsupported_control_flow_source(command: str, control_depth: int):
    return control_depth > 0 or starts_unsupported_control_block(command) or is_control_branch_command(command)


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


class SourceResolver:
    def __init__(self, resolve_path, resolve_variable_references, get_commands):
        self.resolve_path = resolve_path
        self.resolve_variable_references = resolve_variable_references
        self.get_commands = get_commands
        self.source_command_substitution_resolvers = {
            'cat': self.resolve_safe_cat_source,
            'find': self.resolve_safe_find_source,
        }
        self.command_level_source_resolvers = (
            self.resolve_eval_source_command,
            self.resolve_bash_c_source_command,
        )

    def resolve_safe_cat_source(self, inner_command: str, source_expression: str, source_site: str, context: dict,
                                execution_model: str, replacement_kind: str):
        if has_unsupported_shell_operator(inner_command):
            raise UnsupportedSourceError(f"unsupported cat source command syntax: {source_site.strip()}")

        words = parse_shell_words(inner_command)
        if len(words) != 2 or words[0] != 'cat' or words[1].startswith('-'):
            raise UnsupportedSourceError(f"unsupported cat source command: {source_site.strip()}")

        path_file = self.resolve_path(words[1], context)
        if not path_file or not os.path.isfile(path_file):
            raise UnsupportedSourceError(f"unsupported cat source path file: {source_site.strip()}")

        with open(path_file, 'r') as file:
            lines = file.read().splitlines()

        if len(lines) != 1 or not lines[0].strip():
            raise UnsupportedSourceError(f"ambiguous cat source output: {source_site.strip()}")

        resolved_path = self.resolve_path(lines[0].strip(), context)
        if not resolved_path:
            raise UnsupportedSourceError(f"unsupported cat-resolved source path: {source_site.strip()}")

        return ResolvedSource(
            path=resolved_path,
            source_expression=source_expression.strip(),
            source_site=source_site.strip(),
            execution_model=execution_model,
            replacement_kind=replacement_kind,
        )

    def parse_find_command(self, words: list[str], context: dict):
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
            resolved_root = self.resolve_path(root, context)
            if not resolved_root or not os.path.isdir(resolved_root):
                raise UnsupportedSourceError(f"unsupported find source root: {root}")
            resolved_roots.append(resolved_root)

        filters = {
            'name': [],
            'path': [],
            'maxdepth': None,
            'mindepth': 0,
            'has_print': False,
            'quit': False,
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
                filters['quit'] = True
            else:
                raise UnsupportedSourceError(f"unsupported find source predicate: {token}")
            index += 1

        return resolved_roots, filters

    @staticmethod
    def find_candidate_matches(roots: list[str], filters: dict, context: dict):
        matches = []
        current_directory = context['current_directory']

        for root in roots:
            for directory, dirnames, filenames in os.walk(root):
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

                    matches.append(os.path.abspath(candidate))
                    if filters.get('quit'):
                        return matches
                    if len(matches) > 1:
                        return matches

        return matches

    def resolve_safe_find_source(self, inner_command: str, source_expression: str, source_site: str, context: dict,
                                 execution_model: str, replacement_kind: str):
        if has_unsupported_shell_operator(inner_command):
            raise UnsupportedSourceError(f"unsupported find source command syntax: {source_site.strip()}")

        words = parse_shell_words(inner_command)
        try:
            parsed_find = self.parse_find_command(words, context)
        except UnsupportedSourceError as exc:
            raise UnsupportedSourceError(f"{exc}: {source_site.strip()}") from exc
        if not parsed_find:
            return None

        roots, filters = parsed_find
        matches = self.find_candidate_matches(roots, filters, context)
        if len(matches) != 1:
            raise UnsupportedSourceError(f"ambiguous find source output: {source_site.strip()}")

        return ResolvedSource(
            path=matches[0],
            source_expression=source_expression.strip(),
            source_site=source_site.strip(),
            execution_model=execution_model,
            replacement_kind=replacement_kind,
        )

    def resolve_source_expression(self, source_expression: str, source_site: str, context: dict,
                                  execution_model: str = "parent-source", replacement_kind: str = "source"):
        if '`' in source_expression:
            raise UnsupportedSourceError(f"unsupported backtick source command: {source_site.strip()}")

        if has_unquoted_glob(source_expression):
            words = parse_shell_words(source_expression)
            if len(words) != 1:
                raise UnsupportedSourceError(f"unsupported source glob arguments: {source_site.strip()}")

            matches = expand_glob_word(words[0], context, source_site, raw_pattern=source_expression)
            if not matches:
                raise UnsupportedSourceError(f"unsupported empty source glob output: {source_site.strip()}")
            source_arguments = tuple(match.word for match in matches[1:]) or None

            return ResolvedSource(
                path=matches[0].path,
                source_expression=source_expression.strip(),
                source_site=source_site.strip(),
                execution_model=execution_model,
                replacement_kind=replacement_kind,
                source_value=matches[0].word,
                source_arguments=source_arguments,
            )

        if resolved_path := self.resolve_path(source_expression, context):
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

            resolver = self.source_command_substitution_resolvers.get(words[0])
            if resolver:
                return resolver(
                    inner_command, source_expression, source_site, context, execution_model, replacement_kind
                )
            raise UnsupportedSourceError(f"unsupported source command substitution: {source_site.strip()}")

        if is_unsupported_dynamic_source(source_site, source_expression):
            raise UnsupportedSourceError(f"unsupported dynamic source command: {source_site.strip()}")

        return None

    def resolve_single_source_payload(self, payload: str, source_site: str, context: dict,
                                      execution_model: str, replacement_kind: str):
        if '$(' in payload or '`' in payload:
            raise UnsupportedSourceError(f"unsupported nested dynamic source command: {source_site.strip()}")
        if has_unsupported_shell_operator(payload):
            raise UnsupportedSourceError(f"unsupported source command syntax: {source_site.strip()}")

        payload_commands = self.get_commands(payload)
        if len(payload_commands) != 1:
            raise UnsupportedSourceError(f"unsupported multi-command source payload: {source_site.strip()}")

        source_matches = SOURCE_PATTERN.findall(payload_commands[0])
        if len(source_matches) != 1:
            raise UnsupportedSourceError(f"unsupported source payload: {source_site.strip()}")

        _, _, nested_source_expression = source_matches[0]
        resolved_source = self.resolve_source_expression(
            nested_source_expression,
            source_site,
            context,
            execution_model=execution_model,
            replacement_kind=replacement_kind,
        )
        if not resolved_source:
            raise UnsupportedSourceError(f"unsupported unresolved source payload: {source_site.strip()}")

        return resolved_source

    @staticmethod
    def has_source_command(payload: str):
        return bool(SOURCE_PATTERN.findall(payload))

    def resolve_eval_source_command(self, command: str, context: dict, _mode: str):
        stripped_command = command.strip()
        if not re.match(r'^eval\b', stripped_command):
            return None

        words = parse_shell_words(stripped_command)
        if len(words) != 2 or words[0] != 'eval':
            raise UnsupportedSourceError(f"unsupported eval source command: {stripped_command}")

        payload = os.path.expandvars(self.resolve_variable_references(words[1], context))
        if not self.has_source_command(payload):
            return None

        return self.resolve_single_source_payload(
            payload,
            stripped_command,
            context,
            execution_model="parent-source",
            replacement_kind="command",
        )

    def resolve_bash_c_source_command(self, command: str, context: dict, mode: str):
        stripped_command = command.strip()
        if not re.match(r'^(?:bash|/bin/bash|/usr/bin/bash)\b', stripped_command):
            return None

        words = parse_shell_words(stripped_command)
        if len(words) != 3 or words[1] != '-c':
            return None

        payload = os.path.expandvars(self.resolve_variable_references(words[2], context))
        if not self.has_source_command(payload):
            return None

        if mode != "context":
            raise UnsupportedSourceError(f"unsupported child-shell source command in executable mode: {stripped_command}")

        return self.resolve_single_source_payload(
            payload,
            stripped_command,
            context,
            execution_model="child-shell",
            replacement_kind="context",
        )

    def resolve_command_level_source(self, command: str, context: dict, mode: str):
        for resolver in self.command_level_source_resolvers:
            resolved_source = resolver(command, context, mode)
            if resolved_source:
                return resolved_source

        return None

    def resolve_command_level_sources(self, command: str, context: dict, mode: str):
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

                resolved_source = self.resolve_command_level_source(source_command, context, mode)
                if resolved_source:
                    resolved_sources.append(resolved_source)

        return resolved_sources
