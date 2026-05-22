import os
import re
import shlex
from dataclasses import dataclass
from fnmatch import fnmatch

from methods.regex.patterns import SOURCE_PATTERN, create_command_pattern
from methods.regex.utilities import extract_bash_commands, strip_matching_quotes

ASSIGNMENT_WORD_PATTERN = re.compile(r'^[a-zA-Z_]\w*(?:\+)?=.*$')
BASH_COMMAND_PATTERN = create_command_pattern(r'bash|/bin/bash|/usr/bin/bash', regex=True)
COMMAND_LEVEL_SOURCE_PATTERNS = (
    ('eval', None),
    (r'bash|/bin/bash|/usr/bin/bash', BASH_COMMAND_PATTERN),
)


class UnsupportedSourceError(NotImplementedError):
    def __init__(self, message: str | None = None, *, diagnostic=None, code: str | None = None,
                 hint: str | None = None):
        if diagnostic is not None and message is None:
            message = f"{diagnostic.message}: {diagnostic.fragment}"
        super().__init__(message or "unsupported source")
        self.diagnostic = diagnostic
        self.code = diagnostic.code if diagnostic is not None else code
        self.hint = diagnostic.hint if diagnostic is not None else hint

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
    try:
        return shlex.split(command, posix=True)
    except ValueError as exc:
        raise UnsupportedSourceError(f"unsupported source command syntax: {command.strip()} ({exc})") from exc


def source_command_index(command: str):
    try:
        words = parse_shell_words(command)
    except UnsupportedSourceError:
        return 0 if SOURCE_PATTERN.findall(command) else None

    command_start = 0
    while command_start < len(words) and ASSIGNMENT_WORD_PATTERN.match(words[command_start]):
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
            if index == branch_index:
                return index
        if previous_word == '{' or previous_word.endswith('{'):
            return index
        if any(candidate.endswith(')') for candidate in words[command_start:index]):
            return index

    return None


def contains_source_command(command: str):
    return source_command_index(command) is not None


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

    @staticmethod
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
