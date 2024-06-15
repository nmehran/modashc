import re

# Regular expression to match source statements and global variable definitions
SOURCE_PATTERN = re.compile(r'(^|;\s*)(source|\.)\s+([^\n#;]*)')

# Regex to match bash variable declarations which can be used to define paths
VARIABLE_PATTERN = re.compile(r'(^|;\s*)(export\s+)?([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([^\n#;]*)', re.MULTILINE)

# Update regex to handle nested and mismatched quotes more flexibly
DIRNAME_PATTERN = re.compile(r'\$\(\s*dirname\s+(".*?"|\'.*?\'|[^)]+)\s*\)')
BASENAME_PATTERN = re.compile(r'\$\(\s*basename\s+(".*?"|\'.*?\'|[^)]+)\s*\)')

# Regex to capture source or . commands, ensuring they're not part of a comment or a string
SET_PATTERN = re.compile(r'^\s*set\s+([-\w\s]+)', re.MULTILINE)

# Regex to capture bash functions
FUNCTION_PATTERN = re.compile(r'function\s+\w+|\w+\(\)\s*{', re.MULTILINE)