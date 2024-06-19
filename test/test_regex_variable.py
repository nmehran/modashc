import unittest
from methods.patterns import VARIABLE_SIMPLE_PATTERN, VARIABLE_COMPLEX_PATTERN


class TestVariableAssignmentRegex(unittest.TestCase):
    def setUp(self):
        # Simple test cases are used in both test methods
        self.simple_test_cases = {
            "var=value": "var=value",
            "Var=value": "Var=value",
            "VAR=value": "VAR=value",
            "var123=123": "var123=123",
            "v_=true": "v_=true",
            "_user='John Doe'": "_user='John Doe'",
            "a1=\"1.0.0\" || echo 'version error'": "a1=\"1.0.0\"",
            "   _2 =  value2": "_2 =  value2",
            "long_variable_name=(1 2 3 4)": "long_variable_name=(1 2 3 4)",
            "max_num=$((3+5))": "max_num=$((3+5))",
            "export MIN_NUM=1": "export MIN_NUM=1",  # Updated expectation if excluding 'export'
            "echo 'var=notthisone'": None,
            "# Commented_var=notthis": None,
            "\"varname=invalid\"": None,
            "echo 'Setting X=5'": None,
            "count+=1": "count+=1",
            "_var_ok=ok": "_var_ok=ok",
            "VAR-NAME=invalid": None,  # '-' is not allowed in variable names
            "declare -i Var=value": "declare -i Var=value",
            "export VAR=value": "export VAR=value",
            "declare -xr var123=123": "declare -xr var123=123",
            "THIS_DIR=\"$(dirname \"$0\")\"": "THIS_DIR=\"$(dirname \"$0\")\"",
            "local v_=true": "local v_=true",
            "local _user='John Doe'": "local _user='John Doe'",
            "function my_func() { local loc_var=inside; }": None,  # Exclude single-line function scopes
        }

    def test_variable_simple_assignments(self):
        """Test simpler pattern, which does not handle complex scenarios."""
        for case, expected in self.simple_test_cases.items():
            with self.subTest(case=case):
                match = VARIABLE_SIMPLE_PATTERN.match(case.strip())
                result = match.group(0).strip() if match else None
                self.assertEqual(result, expected)

    def test_variable_complex_assignments(self):
        """Test complex pattern, handling both simple and complex scenarios."""
        # Merge simple cases with additional complex cases
        complex_test_cases = {**self.simple_test_cases, **{
            "export LONG_VAR=\"value that \\\ncontinues on the next line\"": None,
            "var=$(echo $(date) | cut -d' ' -f1)": "var=$(echo $(date) | cut -d' ' -f1)",
            "var=\"$(echo $(date) | cut -d' ' -f1)\"": "var=\"$(echo $(date) | cut -d' ' -f1)\"",
            "if [ condition ]; then VAR=\"value\"; else VAR=\"other\"; fi": None,
            "[[ condition ]] && VAR=value": None,
            "VAR=\"Complex \\\"inner quote\\\" scenario\"": "VAR=\"Complex \\\"inner quote\\\" scenario\"",
            "VAR=value # this is a comment": "VAR=value",
            "arr=( item1 item2 item3 )": "arr=( item1 item2 item3 )",
            "VAR=value; ANOTHER_VAR=another_value": "VAR=value",
            "# var=is_a_comment": None,
            "\"var=is_in_quotes\"": None,
        }}

        for case, expected in complex_test_cases.items():
            with self.subTest(case=case):
                match = VARIABLE_COMPLEX_PATTERN.match(case.strip())
                result = match.group(0).strip() if match else None
                self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
