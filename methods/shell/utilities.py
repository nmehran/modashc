import re
from methods.patterns import create_command_pattern


def extract_bash_commands(command, input_string, pattern=None, search_comments=False):
    # Step 1: Regex to find the command followed by its arguments
    if pattern is None:
        escaped_command = re.escape(command)
        pattern = create_command_pattern(escaped_command)

    if not search_comments:
        input_string = remove_comments(input_string, ['#'])

    # Step 2: Find all matches for the command
    matches = []
    for match in pattern.finditer(input_string):
        # Extract the full command with its arguments
        groups: tuple = match.groups()
        if groups and groups[1]:
            separator, command, argument = groups
            matches.append((command, argument.strip()))

    return matches


def replace_bash_command(command: str, replacement: str, input_string: str, pattern=None, search_comments=False):
    if pattern is None:
        escaped_command = re.escape(command)
        pattern = create_command_pattern(escaped_command)

    if not search_comments:
        input_string = remove_comments(input_string, ['#'])

    updated_string_parts = []
    last_end = 0

    # Iterate over all matches using finditer for single-pass processing.
    for match in pattern.finditer(input_string):
        # Group 1 is the command separator, if any, followed by the replacement substitution
        if match.group(2):
            # Append the text before the match.
            updated_string_parts.append(input_string[last_end:match.start()])

            separator = match.group(1)
            updated_string_parts.append(separator)
            updated_string_parts.append(replacement)

            # Update the last processed end.
            last_end = match.end()

    # Append the remaining part of the string after the last match.
    updated_string_parts.append(input_string[last_end:])

    return ''.join(updated_string_parts)


def remove_comments(text, comment_patterns, exclusion_patterns=None, escape_exclusions=True):
    """
    Removes comments from text, taking into account quoted strings and optional exclusions.

    Args:
    - text (str): The input text from which to remove comments.
    - comment_patterns (list of str): List of comment markers to remove (e.g., ['#', '//']).
    - exclusion_patterns (list of str, optional): List of patterns that, if preceding a comment marker, prevent the comment's removal.
    - escape_exclusions (bool): Whether to escape the exclusion patterns (default: True).

    Returns:
    - str: Text with comments removed as specified.
    """
    # Handling exclusions and comments in a single regex expression
    exclusion_regex = ''
    if exclusion_patterns:
        exclusion_regex = '(?:' + '|'.join(
            f"{re.escape(pattern) if escape_exclusions else pattern}" for pattern in exclusion_patterns) + ')'

    # Combine exclusions and comment markers into a single regex
    comment_regex = '|'.join([re.escape(pattern) for pattern in comment_patterns])

    # pattern = re.compile(rf"""
    #     {exclusion_regex}                         # Match exclusions
    #     |\\"|"(?:\\"|[^"$])*"|'(?:\\'|[^'])*'     # Match quoted strings, including escaped quotes
    #     |(?P<comments>{comment_regex}).*          # Match comments
    # """, re.VERBOSE)

    pattern = re.compile(rf"""
        {exclusion_regex}                         # Match exclusions
        |(\\?['"]+)(?:(?=(\\?))\2.)*?\1           # Match quoted strings
        |(?P<comments>{comment_regex}).*          # Match comments
    """, re.VERBOSE)

    # Replace matches: keep exclusions and quotes, remove comments
    def remove_or_keep(match):
        if match.group('comments'):  # If match is a comment, remove
            return ''
        return match.group(0)  # If match is an exclusion or a quote, keep

    # Apply the regex
    return re.sub(pattern, remove_or_keep, text)


