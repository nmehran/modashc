import re


# A regex pattern with a 'command' placeholder to be formatted dynamically at runtime.
# Matches a $() command substitution block, including nested parentheses
COMMAND_TEMPLATE_PATTERN = (
    r'''\\"|"(?:\\"|[^"$])*"|\'(?:\\\'|[^\'])*\''''  # Search unquoted commands and command separators
    r'|(^|[|;&()\n{{}}]*?\s*)'  # Captures the start of the input or delimiters followed by optional whitespace
    r'(\b{command}\b)'  # Captures the 'command' specified
    r'((?:\s+'  # Matches leading whitespace before arguments
    r'(?:'  # Starts grouping for different argument types
    r'"(?:\\.|[^"\\])*"'  # Matches double-quoted strings with escaped characters
    r"|'(?:\\.|[^'\\])*'"  # Matches single-quoted strings with escaped characters
    r"|\$\((?:[^()]*|\((?:[^()]*|\([^()]*\))*\))*\)"  # Accurately matches complex nested command substitutions
    r'|[^"\'\s;|&|(?:\)\")]+?'  # Matches unquoted arguments excluding specific characters
    r')+)*'  # Repeats to capture multiple arguments
    r')'  # Captures all following arguments as a group
)

PATH_COMMAND_TEMPLATE_PATTERN = (
    r'\$\(\s*\b{command}\b\s+(".*?"|\'.*?\'|[^)]+)\s*\)'
)


def create_command_pattern(command, template=None):
    if template is None:
        template = COMMAND_TEMPLATE_PATTERN

    # Escape the command to handle any special characters it might contain
    escaped_command = re.escape(command)

    # Create a regex pattern dynamically based on the command
    pattern = re.compile(
        template.format(command=escaped_command), re.DOTALL
    )

    return pattern


# Regular expression to match source statements and global variable definitions
# Example: source /path/to/file or . /path/to/file
SOURCE_PATTERN = re.compile(r'(^|;\s*|\s*&{2}\s*|\$\(\s*)(source|\.)\s+([^\n#;]*)')
# SOURCE_PATTERN = create_command_pattern(command='source')

# Regex to match dirname command usage, handling nested and mismatched quotes
# Example: $(dirname "/path/to/dir")
DIRNAME_PATTERN = create_command_pattern(command='dirname', template=PATH_COMMAND_TEMPLATE_PATTERN)

# Regex to match basename command usage, handling nested and mismatched quotes
# Example: $(basename "/path/to/file")
BASENAME_PATTERN = create_command_pattern(command='basename', template=PATH_COMMAND_TEMPLATE_PATTERN)

# Regex to match realpath command usage, handling nested and mismatched quotes
# Example: $(realpath "/path/to/dir")
REALPATH_PATTERN = create_command_pattern(command='realpath', template=PATH_COMMAND_TEMPLATE_PATTERN)

# Regex to capture set commands, ensuring they're not part of a comment or a string
# Example: set -e or set +x
SET_PATTERN = re.compile(r'^\s*set\s+([-\w\s]+)', re.MULTILINE)
# SET_PATTERN = create_command_pattern(command='set')

# Regex for cd commands, accommodating paths with optional quotes and surrounding whitespace
# Example: cd /path/to/dir or cd "/path with spaces"
CD_PATTERN = create_command_pattern(command='cd')

# Regex to match bash variable declarations which can be used to define paths
# Example: export VAR=value or VAR=value
VARIABLE_ASSIGNMENT_PATTERN = re.compile(r'''
    (?:                                         # Non-capturing group for matching quoted strings or any character except '#' or newline
        "(?:\\.|[^"\\])*?"                      # Double-quoted strings
        |'[^']*?'                               # Single-quoted strings
        |[^"'#\n]                               # Any non-quote, non-#, non-newline characters
    )*?                                         # End of non-capturing group
    \s*                                         
        (?:^|(?<=[;&|\n({])                     # Ensure the assignment is at the start or follows a command separator 
        |(?<=\b(?:then|else|elif)\b)            # Or control structure
        |".*\$\()                               # Or command substitution
    \s*
    (
        (?:export|declare(?:\s+-\w+)*|local)?   # Optionally match 'export', 'declare' with flags, or 'local'
        \s*                                     # Followed by any whitespace
    )
    (?<![^\s(])                                 # Negative lookbehind for anything except whitespace or '('
    ([a-zA-Z_]\w*)                              # Variable name: start with a letter/underscore, followed by any word characters
    (\s*[-+]?=\s*)                              # Match '=', optionally preceded by '+' or '-', surrounded by optional whitespace
    (
    (?:                                         # Non-capturing group for different value types:
            "(?:\\.|[^"\\]|\$\{?[\w}]+)*"       # Double-quoted string with variables
            |'[^']*'                            # Single-quoted string (simplified)
            |\$?\((?:\(?[^()]*\)?)*             # Command substitution '$(command)' or '(command)'
            |[^"';#\n\s]+                       # OR any character sequence excluding specific chars
        )+                                      # One or more of above value types
    )
    (?=\s*[;#\n]|\s*$|\s*[)|&])                 # Lookahead for end of assignment
''', re.VERBOSE | re.MULTILINE)


VARIABLE_REFERENCE_PATTERN = re.compile(r'''
        (?<![\\])                            # Negative lookbehind for a single backslash
        (?:\\\\)*                            # Even number of backslashes (not captured)
        (                                    # Start capture group
        \$                                   # Literal $
        (?:                                  # Non-capturing group for either:
            \w+                              # Word characters (for simple variables like $VAR)
            |                                # OR
            \{                               # Opening curly brace
            (?:                              # Non-capturing group for the variable name and possible nested structure
                [^{}$]+                      # Any characters except braces and $
                |                            # OR
                (\$(?:\w+|\{[^}]+\}))        # Nested variable without or with braces
                |                            # OR
                \{(?:[^{}]+|\{[^}]+\})+\}    # Nested braced content
            )+                               # One or more of the above
            \}                               # Closing curly brace
        )
        (?=                                  # Positive lookahead to ensure we're not in single quotes:
            [^']*                            # Any number of non-single-quote characters
            (?:'[^']*'[^']*)*                # Followed by any number of 'quoted' sections
            $                                # Until the end of the string
        ))
        ''', re.VERBOSE)

# Regex to capture bash function definitions
# Example: function my_func or my_func() {
FUNCTION_PATTERN = re.compile(r'function\s+\w+|\w+\(\)\s*{', re.MULTILINE)

# Description: Regex to strip matching outer quotes from a string and unescape any escaped quotes inside
# Example: "'This \'escaped\' example!'" becomes "This 'escaped' example!"
QUOTE_STRIP_PATTERN = re.compile(r'^([\'"]+)(.*?)(\1)$')
