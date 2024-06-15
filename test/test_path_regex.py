from methods.patterns import PATH_PATTERN

# Adjust the regular expression to handle backslashes correctly and avoid empty valid matches
path_regex = PATH_PATTERN

# Re-run the refined test cases
test_cases = [
    (r"'/home/user/file.txt'", True),
    (r"\"C:\\Users\\New Folder\\file.txt\"", False),
    (r"'single_quote_path/'", True),
    (r"\"double_quote_path\\file\"", False),
    (r"'mixed/slashes\\path'", True),
    (r"'unmatched_double\"'", False),
    (r"unquoted/path", False),
    (r"'illegal*chars'", False),
    (r"\"\"", False),
    (r"/trailing/slash/", False),
    (r"'unbalanced\"'", False),
    (r"''", False)  # Empty string inside quotes
]


def run_tests():
    all_passed = True
    test_results = []
    for path, expected in test_cases:
        result = bool(path_regex.match(path))
        if result != expected:
            all_passed = False
            test_results.append(f"Failed: {path} (Expected: {expected}, Got: {result})")
        else:
            test_results.append(f"Passed: {path}")

    if not all_passed:
        joined_tests = "\n".join(test_results)
        raise AssertionError(f"Some tests failed:\n{joined_tests}")

    return all_passed


# Execute tests
if __name__ == '__main__':
    run_tests()
