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

# Deprecated helper function used by 'old' `replace_bash_command`
# def replacement_function(match, replacement: str, position: int):
#     # Only replace the command if the match occurs at the specified 'position'
#     if match.start(2) == position:
#         return f'{match.group(1)}{replacement}'
#     else:
#         # If the position does not match, return the original string
#         return match.group(0)


# Deprecated version:
# def replace_bash_command(command: str, replacement: str, input_string: str, pattern=None):
#     if pattern is None:
#         escaped_command = re.escape(command)
#         pattern = create_command_pattern(escaped_command)
#
#     start_pos = 0
#     match = pattern.search(input_string, pos=start_pos)
#     if match:
#         start_pos = match.start()
#
#     while match:
#         command_replace = partial(replacement_function, replacement=replacement, position=start_pos)
#         input_string = pattern.sub(command_replace, input_string)
#         start_pos = match.end()
#         match = pattern.search(input_string, pos=start_pos)
#
#     return input_string


# Streamlined version:
def replace_bash_command(command: str, replacement: str, input_string: str, pattern=None):
    if pattern is None:
        escaped_command = re.escape(command)
        pattern = create_command_pattern(escaped_command)

    updated_string_parts = []
    last_end = 0

    # Iterate over all matches using finditer for single-pass processing.
    for match in pattern.finditer(input_string):
        # Append the text before the match.
        updated_string_parts.append(input_string[last_end:match.start()])

        # Group 1 is the command separator, if any, followed by the replacement substitution
        updated_string_parts.append(match.group(1))
        updated_string_parts.append(replacement)

        # Update the last processed end.
        last_end = match.end()

    # Append the remaining part of the string after the last match.
    updated_string_parts.append(input_string[last_end:])

    return ''.join(updated_string_parts)
