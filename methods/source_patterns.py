import re


EXTGLOB_PREFIXES = ("@(", "?(", "*(", "+(", "!(")


class UnsupportedPatternError(ValueError):
    pass


def extglob_operator_at(text: str, index: int):
    if index + 1 >= len(text):
        return None
    if text[index] in {"@", "?", "*", "+", "!"} and text[index + 1] == "(":
        return text[index]
    return None


def shell_pattern_matches(pattern: str, value: str, *, extglob: bool = False, nocase: bool = False):
    flags = re.S | (re.I if nocase else 0)
    regex = re.compile(rf"\A{shell_pattern_regex_source(pattern, extglob=extglob)}\Z", flags)
    return bool(regex.fullmatch(value))


def shell_pattern_regex_source(pattern: str, *, extglob: bool = False):
    return _translate_pattern(pattern, extglob=extglob)


def _translate_pattern(pattern: str, *, extglob: bool):
    output = []
    index = 0

    while index < len(pattern):
        operator = extglob_operator_at(pattern, index) if extglob else None
        if operator is not None:
            body, group_end = _read_extglob_body(pattern, index + 2)
            alternatives = _split_extglob_alternatives(body)
            if not alternatives:
                raise UnsupportedPatternError(f"unsupported empty extglob pattern: {pattern}")

            alternative_sources = [
                _translate_pattern(alternative, extglob=extglob)
                for alternative in alternatives
            ]
            alternative_group = "|".join(alternative_sources)
            if operator == "@":
                output.append(f"(?:{alternative_group})")
            elif operator == "?":
                output.append(f"(?:(?:{alternative_group}))?")
            elif operator == "*":
                output.append(f"(?:(?:{alternative_group}))*")
            elif operator == "+":
                output.append(f"(?:(?:{alternative_group}))+")
            elif operator == "!":
                rest_source = _translate_pattern(pattern[group_end + 1:], extglob=extglob)
                output.append(f"(?!(?:{alternative_group}){rest_source}\\Z).*?")
            index = group_end + 1
            continue

        char = pattern[index]
        if char == "\\":
            if index + 1 >= len(pattern):
                output.append(re.escape("\\"))
                index += 1
                continue
            output.append(re.escape(pattern[index + 1]))
            index += 2
            continue

        if char == "*":
            output.append(".*")
            index += 1
            continue
        if char == "?":
            output.append(".")
            index += 1
            continue
        if char == "[":
            translated, next_index = _translate_bracket(pattern, index)
            output.append(translated)
            index = next_index
            continue

        output.append(re.escape(char))
        index += 1

    return "".join(output)


def _read_extglob_body(pattern: str, body_start: int):
    body = []
    escaped = False
    bracket_depth = 0
    depth = 1
    index = body_start

    while index < len(pattern):
        char = pattern[index]
        if escaped:
            body.append(char)
            escaped = False
            index += 1
            continue

        if char == "\\":
            body.append(char)
            escaped = True
            index += 1
            continue

        if char == "[":
            bracket_depth += 1
            body.append(char)
            index += 1
            continue
        if char == "]" and bracket_depth:
            bracket_depth -= 1
            body.append(char)
            index += 1
            continue

        if bracket_depth == 0:
            if extglob_operator_at(pattern, index) is not None:
                depth += 1
                body.append(char)
                body.append("(")
                index += 2
                continue
            if char == ")":
                depth -= 1
                if depth == 0:
                    return "".join(body), index

        body.append(char)
        index += 1

    raise UnsupportedPatternError(f"unsupported unterminated extglob pattern: {pattern}")


def _split_extglob_alternatives(body: str):
    alternatives = []
    current = []
    escaped = False
    bracket_depth = 0
    depth = 0
    index = 0

    while index < len(body):
        char = body[index]
        if escaped:
            current.append(char)
            escaped = False
            index += 1
            continue

        if char == "\\":
            current.append(char)
            escaped = True
            index += 1
            continue

        if char == "[":
            bracket_depth += 1
            current.append(char)
            index += 1
            continue
        if char == "]" and bracket_depth:
            bracket_depth -= 1
            current.append(char)
            index += 1
            continue

        if bracket_depth == 0:
            if extglob_operator_at(body, index) is not None:
                depth += 1
                current.append(char)
                current.append("(")
                index += 2
                continue
            if char == ")" and depth:
                depth -= 1
                current.append(char)
                index += 1
                continue
            if char == "|" and depth == 0:
                alternatives.append("".join(current))
                current = []
                index += 1
                continue

        current.append(char)
        index += 1

    alternatives.append("".join(current))
    return alternatives


def _translate_bracket(pattern: str, start: int):
    end = _bracket_end(pattern, start)
    if end is None:
        return re.escape("["), start + 1
    content = pattern[start + 1:end]
    return _translate_bracket_content(content, pattern), end + 1


def _bracket_end(pattern: str, start: int):
    index = start + 1
    if index < len(pattern) and pattern[index] in {"!", "^"}:
        index += 1
    if index < len(pattern) and pattern[index] == "]":
        index += 1
    while index < len(pattern):
        if pattern.startswith("[:", index):
            class_end = pattern.find(":]", index + 2)
            if class_end >= 0:
                index = class_end + 2
                continue
        if pattern[index] == "]":
            return index
        index += 1
    return None


def _translate_bracket_content(content: str, pattern: str):
    if not content:
        raise UnsupportedPatternError(f"unsupported empty bracket pattern: {pattern}")
    if "[." in content or "[=" in content:
        raise UnsupportedPatternError(f"unsupported locale-dependent bracket pattern: {pattern}")

    negated = content[0] in {"!", "^"}
    if negated:
        content = content[1:]
    translated = _translate_posix_classes(content, pattern)
    return f"[{'^' if negated else ''}{_regex_class_body(translated)}]"


def _translate_posix_classes(content: str, pattern: str):
    posix_classes = {
        "alnum": "0-9A-Za-z",
        "alpha": "A-Za-z",
        "blank": " \t",
        "cntrl": r"\x00-\x1f\x7f",
        "digit": "0-9",
        "graph": "!-~",
        "lower": "a-z",
        "print": " -~",
        "punct": r"!\"#$%&'()*+,./:;<=>?@[\\\]^_`{|}~-",
        "space": r" \t\r\n\v\f",
        "upper": "A-Z",
        "xdigit": "0-9A-Fa-f",
    }

    def replace(match):
        name = match.group(1)
        if name not in posix_classes:
            raise UnsupportedPatternError(f"unsupported POSIX class pattern: {pattern}")
        return posix_classes[name]

    return re.sub(r"\[:([a-zA-Z_]+):\]", replace, content)


def _regex_class_body(content: str):
    output = []
    for index, char in enumerate(content):
        if char == "\\":
            output.append(r"\\")
        elif char == "]":
            output.append(r"\]")
        elif char == "^" and index == 0:
            output.append(r"\^")
        else:
            output.append(char)
    return "".join(output)
