import unittest
import re


def preprocess_script(script):
    # Aggressively remove single and double quoted strings
    script = re.sub(r'(["\'])(?:(?!\$\().)*?\1', '', script)
    # Remove comments
    script = re.sub(r'#.*$', '', script, flags=re.MULTILINE)
    return script


class TestFunctionDetection(unittest.TestCase):
    def setUp(self):
        # Define a regex pattern to correctly identify all valid function calls excluding those in quotes or comments
        self.pattern = re.compile(
            r'''
            (?:^|\s|;|\s*&{2}|\(\s*)\s*           # Match start of line, whitespace, semicolon, or double ampersands followed by any whitespace
            \b(\w+)\b                     # Match the function name as a whole word
            (?!\s*=\s*(?![=!<>~]))            # Ensure no '=' sign follows immediately after, unless it's a comparison
            ''', re.VERBOSE | re.MULTILINE)

    def test_function_calls(self):
        test_string = preprocess_script("""
        function1=100                    # Should not match, it's an assignment
        function2 = "value"              # Should not match, it's an assignment
        "function3()"                    # Should not match, inside quotes
        function4= "another_value"       # Should not match, it's an assignment
        function5 == comparison          # Should match, it's a comparison
        function6 != "test"              # Should match, it's a comparison
        'function7("value")=improper'    # Should not match, inside quotes
        function8()                      # Should match, it's a simple call
        command && function9()           # Should match
        if condition; then function10(); # Should match
        function12() # test function     # Should match, before comment
        "commented out #function13()"    # Should not match, inside quotes
        $(substitute) == function14      # Should match, it's a comparison
        "$(a && b)" =~ "$(function15)"   # Should match, it's a comparison
        """)
        # Define expected matches explicitly
        expected = [
            'function5',   # Comparison
            'comparison',  # Valid function name
            'function6',   # Comparison
            'function8',   # Simple call
            'command',     # Command in logical sequence
            'function9',   # Function call after logical operator
            'if',          # Conditional statement
            'condition',   # Condition for if statement
            'then',        # Then in if-then statement
            'function10',  # Function call in if-then statement
            'function12',  # Simple call before comment
            'substitute',  # Command substitution
            'function14',  # Comparison with command substitution
            'a',           # Command substitution
            'b',           # Command substitution
            'function15'   # Function call within a comparison
        ]
        matches = [match for match in self.pattern.findall(test_string)]  # Find all matches using the updated pattern
        self.assertEqual(sorted(matches), sorted(expected))


if __name__ == '__main__':
    unittest.main()
