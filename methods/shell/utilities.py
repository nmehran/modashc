import re
from functools import partial
from methods.patterns import create_command_pattern


def extract_bash_commands(command, input_string, pattern=None):
    # Step 1: Regex to find the command followed by its arguments
    if pattern is None:
        escaped_command = re.escape(command)
        pattern = create_command_pattern(escaped_command)

    # Step 2: Find all matches for the command
    matches = []
    for match in pattern.finditer(input_string):
        # Extract the full command with its arguments
        groups: tuple = match.groups()
        if groups:
            separator, command, argument = groups
            matches.append((command, argument.strip()))

    return matches


def replacement_function(match, replacement: str, position: int):
    # Only replace the command if the match occurs at the specified 'position'
    if match.start() == position:
        return f'{match.group(1)}{replacement}'
    else:
        # If the position does not match, return the original string
        return match.group(0)


def replace_bash_command(command: str, replacement: str, input_string: str, pattern=None):
    if pattern is None:
        escaped_command = re.escape(command)
        pattern = create_command_pattern(escaped_command)

    start_pos = 0
    match = pattern.search(input_string, pos=start_pos)
    if match:
        start_pos = match.start()

    while match:
        command_replace = partial(replacement_function, replacement=replacement, position=start_pos)
        input_string = pattern.sub(command_replace, input_string)
        start_pos = match.end()
        match = pattern.search(input_string, pos=start_pos)

    return input_string
