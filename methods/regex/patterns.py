import re


# A regex pattern with a 'command' placeholder to be formatted dynamically at runtime.
COMMAND_TEMPLATE_PATTERN = (
    r'''\\"|"(?:\\"|[^"$])*"|\'(?:\\\'|[^\'])*\''''  # Search unquoted commands and command separators
    r'|(^|[|;&()\n{{}}]*?\s*)'  # Captures the start of the input or delimiters followed by optional whitespace
    r'({command})'  # Captures the 'command' specified
    r'((?:\s+'  # Matches leading whitespace before arguments
    r'(?:'  # Starts grouping for different argument types
    r'"(?:\\.|[^"\\])*"'  # Matches double-quoted strings with escaped characters
    r"|'(?:\\.|[^'\\])*'"  # Matches single-quoted strings with escaped characters
    r"|\$\((?:[^()]*|\((?:[^()]*|\([^()]*\))*\))*\)"  # Accurately matches complex nested command substitutions
    r'|[^"\'\s;|&|(?:\)\")]+?'  # Matches unquoted arguments excluding specific characters
    r')+)*'  # Repeats to capture multiple arguments
    r')'  # Captures all following arguments as a group
)


def create_command_pattern(command):
    # Escape the command to handle any special characters it might contain
    escaped_command = re.escape(command)

    # Create a regex pattern dynamically based on the command
    pattern = re.compile(
        COMMAND_TEMPLATE_PATTERN.format(command=escaped_command), re.DOTALL
    )

    return pattern


# Regular expression to match source statements and global variable definitions
# Example: source /path/to/file or . /path/to/file
SOURCE_PATTERN = re.compile(r'(^|;\s*|\s*&{2}\s*|\$\(\s*)(source|\.)\s+([^\n#;]*)')

# Regex to match bash variable declarations which can be used to define paths
# Example: export VAR=value or VAR=value
VARIABLE_SIMPLE_PATTERN = re.compile(
    r'(^|;\s*|\s*&{2}\s*|&&\s*)(declare(?:\s+-[a-zA-Z]*)*\s+|export\s+|local\s+)?',
    re.MULTILINE
)
VARIABLE_COMPLEX_PATTERN = re.compile(
    r'^(?:export\s+|local\s+|declare\s+[\-\w]*\s*)?\s*'
    r'([a-zA-Z_][a-zA-Z0-9_]*)(?:\s*(=|\+=)\s*)'
    r'('
        r'"(?:\\["\\$]|[^"\\$]*|\$(?!\()|\$\([^)]*\))*"'  # Matches double-quoted strings with improved command substitution handling
        r"|'(?:\\.|[^'\\])*'"  # Matches single-quoted strings
        r"|\$\((?:[^()]*|\((?:[^()]*|\([^()]*\))*\))*\)"  # Improved nesting for $() with nested parentheses
        r"|[^|;#\"\'\n]+"  # Matches unquoted strings without pipe, semicolon, hash, or quotes
    r')',
    re.MULTILINE
)

# Regex for cd commands, accommodating paths with optional quotes and surrounding whitespace
# Example: cd /path/to/dir or cd "/path with spaces"
CD_PATTERN = create_command_pattern(command='cd')

# Regex to match dirname command usage, handling nested and mismatched quotes
# Example: $(dirname "/path/to/dir")
DIRNAME_PATTERN = re.compile(r'\$\(\s*dirname\s+(".*?"|\'.*?\'|[^)]+)\s*\)')

# Regex to match basename command usage, handling nested and mismatched quotes
# Example: $(basename "/path/to/file")
BASENAME_PATTERN = re.compile(r'\$\(\s*basename\s+(".*?"|\'.*?\'|[^)]+)\s*\)')

# Regex to match realpath command usage, handling nested and mismatched quotes
# Example: $(realpath "/path/to/dir")
REALPATH_PATTERN = re.compile(r'\$\(\s*realpath\s+(".*?"|\'.*?\'|[^)]+)\s*\)')

# Regex to capture set commands, ensuring they're not part of a comment or a string
# Example: set -e or set +x
SET_PATTERN = re.compile(r'^\s*set\s+([-\w\s]+)', re.MULTILINE)

# Regex to capture bash function definitions
# Example: function my_func or my_func() {
FUNCTION_PATTERN = re.compile(r'function\s+\w+|\w+\(\)\s*{', re.MULTILINE)

# Description: Regex to strip matching outer quotes from a string and unescape any escaped quotes inside
# Example: "'This \'escaped\' example!'" becomes "This 'escaped' example!"
QUOTE_STRIP_PATTERN = re.compile(r'^([\'"]+)(.*?)(\1)$')
