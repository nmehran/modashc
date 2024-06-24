import re


def find_function_calls(bash_file):

    allowed_functions = {'do', 'disown', '{', 'wait', ']]', 'read', 'unset', '!', 'done', 'fi', 'getopts', 'esac', 'continue', 'trap', 'bg', 'times', 'until', 'let', 'true', 'local', 'set', 'for', 'in', 'elif', 'break', 'readarray', 'pushd', 'type', 'echo', 'exec', 'typeset', 'dirs', '[', '}', 'while', 'shopt', 'ulimit', 'test', 'shift', 'mapfile', 'return', 'popd', 'unalias', 'source', '.', ':', 'then', 'false', 'cd', 'jobs', 'printf', 'exit', 'else', 'eval', 'function', 'help', 'if', 'declare', 'caller', 'suspend', 'select', 'builtin', 'umask', 'hash', 'case', 'fg', 'compopt', '[[', 'history', 'fc', 'readonly', 'alias', 'pwd', 'logout', 'enable', 'bind', 'export', 'compgen', 'kill', 'command', 'complete'}

    function_patterns = [
        r'\$\(\s*(\w+).*?\)',  # $(func ...)
        r'^\s*(\w+)\s+.*',  # func ... at the beginning of a line
        r'&&\s*(\w+)',  # && func
        r';\s*(\w+)',  # ; func
        r'(\w+)\s*\|',  # func |
        r'(\w+)\s*\|\|',  # func ||
        r'\(\s*(\w+)',  # (func
        r'(\w+)\s*&',  # func &
        r'\bdo\s*(\w+)',  # do func
        r'\bthen\s*(\w+)',  # then func
        r'\[\[\s*\$\((\w+)\)\s*\]\]',  # [[ $(func) ]]
        r'\(\s*\$\((\w+)\)\s*\)',  # outer_func $(inner_func)
        r'=\s*\$\((\w+)\)',  # var=$(func)
        r'(\w+)\s*>\s*',  # func >
        r'(\w+)\s*<\s*',  # func <
        r'=\s*\(\$\((\w+)\)\)',  # array=($(func))
        r'(?<![\w-])(\w+)[-_\w]*\s*\(',  # func-name (
        r'(\w+)\s*#',  # func #
        r'^\s*\w+\s*&&\s*(\w+)',  # if $(func1) && func2; then
        r'(\w+)\\\s*',  # func\
    ]

    # Combine patterns into a single regex pattern with exclusion for variable assignments
    combined_pattern = '|'.join(
        rf'({pattern})(?!\s*=\s*)' for pattern in function_patterns
    )

    compiled_pattern = re.compile(combined_pattern, re.MULTILINE)

    function_calls = set()

    with open(bash_file, 'r') as file:
        content = file.read()

        # Remove string literals and comments to avoid false positives
        content = re.sub(r'(["\'])(?:(?=(\\?))\2.)*?\1', '', content)  # Remove string literals
        content = re.sub(r'#.*', '', content)  # Remove comments
        content = re.sub(r'\n', ';', content)  # Remove comments
        content = re.sub(r';{2,}', ';', content)  # Remove comments

        matches = compiled_pattern.findall(content)

        for match in matches:
            for group in match:
                if group and group not in allowed_functions:  # filter out empty groups and allowed functions
                    function_calls.add(group)

    return function_calls


# Usage example
bash_file_path = '/home/delta/PythonProjects/ansible-k3s-cilium-ha/scripts/K3S-HA-Deploy/wireguard/wiresync/src/main.sh'
functions = find_function_calls(bash_file_path)
print("Function calls found:", functions)
