def get_commands(line: str):
    """Split one physical shell line into top-level command fragments.

    This is a quote-aware splitter for compiler frontends and resolvers, not a
    full Bash parser.
    """
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
