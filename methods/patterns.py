import re


# Regular expression to match source statements and global variable definitions
# Example: source /path/to/file or . /path/to/file
SOURCE_PATTERN = re.compile(r'(^|;\s*|&{2}\s*)(source|\.)\s+([^\n#;]*)')

# Regex to match bash variable declarations which can be used to define paths
# Example: export VAR=value or VAR=value
VARIABLE_PATTERN = re.compile(r'(^|;\s*\b|&{2}\s*)(export\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([^\n#;]*)', re.MULTILINE)

# Regex for cd commands, accommodating paths with optional quotes and surrounding whitespace
# Example: cd /path/to/dir or cd "/path with spaces"
CD_PATTERN = re.compile(r'(^|;\s*\b)cd\s+("([^"]*)"|\'([^\']*)\'|([^\s#;]+))')

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
PATH_PATTERN = re.compile(r"^(['\"])([a-zA-Z0-9_. \\/-]+)\1$")
