import re


# A capture pattern with a 'command' placeholder, dynamically formatted at run-time, used to capture a command and its respective argument
COMMAND_TEMPLATE_PATTERN = (
    r'((?:^|\s*(?:&&|\|\||;)\s*))'  # Match start or command separators (&&, ||, ;), consume them
    r'(?!#)'  # Ensure no '#' follows after optional spaces on this command line
    r'(?:'  # Begin group for command structure
    r'(?:"?\$\()?\s*'  # Optional command substitution at the start
    r'|[^"\';|&]?'  # Match unquoted sequences not containing spaces or separators
    r')*?'  # Non-greedy match for repeated sequences
    r'({command})'  # Capture the exact command
    r'((?:\s+'  # Whitespace before arguments
    r'(?:'  # Different argument types
    r'"(?:\\.|[^"\\])*"'  # Double-quoted strings allowing escaped characters
    r"|'(?:\\.|[^'\\])*'"  # Single-quoted strings allowing escaped characters
    r"|\$\((?:[^()]*|\((?:[^()]*|\([^()]*\))*\))*\)"  # Improved nested command substitution
    r"|\$?\w+"  # Unquoted words or variables
    r'|[^"\'\s;|&|(?:\)\")]+?'
    r')+)*'
    r')'  # Repeat for multiple arguments, capturing all
)

# COMMAND_TEMPLATE_PATTERN = (
#     r'\\"|"(?:\\"|[^"$])*"|\'(?:\\\'|[^\'])*\'|(^|[|;&()\n{{}}])+\s*'
#     r'\b({command})\b'
#     r"("
#         r'\s*(?:"[^"]+"|[^|;&()\n{{}}])*'
#     r")"
# )

# COMMAND_TEMPLATE_PATTERN = (
#     r'\\"|"(?:\\"|[^"$])*"|\'(?:\\\'|[^\'])*\'|(^|[|;&()\n{{}}])+\s*'
#     r'\b({command})\b'
#     r"("
#         r'\s*(?:"[^"]+"|[^|;&\n])*'
#     r")"
# )

# r'\\"|"(?:\\"|[^"$])*"|\'(?:\\\'|[^\'])*\'|(^|[|;&()\n{{}}])+\s*'

# COMMAND_TEMPLATE_PATTERN = (
#     r'\\"|"(?:\\"|[^"$])*"|\'(?:\\\'|[^\'])*\'|(^|[|;&()\n{{}}])+\s*'
#     # r'(?:'  # Begin group for command structure
#     # r'(?:"?\$\()?\s*'  # Optional command substitution at the start
#     # r'|[^"\';|&]?'  # Match unquoted sequences not containing spaces or separators
#     # r')*?'  # Non-greedy match for repeated sequences
#     r'({command})'  # Capture the exact command
#     r'((?:\s+'  # Whitespace before arguments
#     r'(?:'  # Different argument types
#     r'"(?:\\.|[^"\\])*"'  # Double-quoted strings allowing escaped characters
#     r"|'(?:\\.|[^'\\])*'"  # Single-quoted strings allowing escaped characters
#     r"|\$\((?:[^()]*|\((?:[^()]*|\([^()]*\))*\))*\)"  # Improved nested command substitution
#     # r"|\$?\w+"  # Unquoted words or variables
#     r'|[^"\'\s;|&|(?:\)\")]+?'
#     r')+)*'
#     r')'  # Repeat for multiple arguments, capturing all
# )

COMMAND_TEMPLATE_PATTERN = (
    r'''\\"|"(?:\\"|[^"$])*"|\'(?:\\\'|[^\'])*\''''
    r'|(^|[|;&()\n{{}}]*?\s*)'
    # r'(?!#)'  # Ensure no '#' follows after optional spaces on this command line
    # r'(?:'  # Begin group for command structure
    # r'(?:"?\$\()?\s*'  # Optional command substitution at the start
    # r'|[^"\';|&]?'  # Match unquoted sequences not containing spaces or separators
    # r')*?'  # Non-greedy match for repeated sequences
    r'({command})'  # Capture the exact command
    r'((?:\s+'  # Whitespace before arguments
    r'(?:'  # Different argument types
    r'"(?:\\.|[^"\\])*"'  # Double-quoted strings allowing escaped characters
    r"|'(?:\\.|[^'\\])*'"  # Single-quoted strings allowing escaped characters
    r"|\$\((?:[^()]*|\((?:[^()]*|\([^()]*\))*\))*\)"  # Improved nested command substitution
    # r"|\$?\w+"  # Unquoted words or variables
    r'|[^"\'\s;|&|(?:\)\")]+?'
    r')+)*'
    r')'  # Repeat for multiple arguments, capturing all
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

# Regex for file paths
# Example: "/path/to/file" or './path/to/file'
PATH_PATTERN = re.compile(r"^([a-zA-Z0-9_. \\/-]+)$")
PATH_QUOTED_PATTERN = re.compile(r"^(['\"])([a-zA-Z0-9_. \\/-]+)\1$")

