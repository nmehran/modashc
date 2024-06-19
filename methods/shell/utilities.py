import re
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
            command, argument = groups
            matches.append((command, argument.strip()))

    return matches
