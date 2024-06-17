import os
import subprocess
import unittest

PWD = os.getcwd()

# Path to `compile.py`
COMPILE_SCRIPT = os.path.abspath(f"{PWD}/../modashc.py")

# Global variables for entry point and output file
ENTRY_POINT = os.path.abspath(f'{PWD}/sample_dir/script_main.sh')
OUTPUT_FILE = os.path.abspath(f'{PWD}/outputs/merged_script.sh')


class TestCompile(unittest.TestCase):
    def setUp(self):
        self.entry_point = ENTRY_POINT
        self.output_file = OUTPUT_FILE

    def test_compile(self):
        # Compile the scripts using modashc.py
        compile_command = ['python', COMPILE_SCRIPT, self.entry_point, self.output_file]
        compile_result = subprocess.run(compile_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        # Assert that compilation was successful
        self.assertEqual(compile_result.returncode, 0,
                         f"Error compiling output to '{self.output_file}' using `modashc.py`")
        self.assertTrue(os.path.exists(self.output_file), "Output file was not created")

        # Execute the compiled output script
        execution_command = ['bash', self.output_file]
        execution_result = subprocess.run(execution_command,
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          text=True)

        # Define the expected output
        expected_output = (
            "This directory contains the compiled outputs used by the `modashc` test suite.\n"
            "This is script6.sh in dir1\n"
            "This is script5.sh in the root directory\n"
            "This is script4.sh in the root directory\n"
            "This is script3.sh in 'dir with spaces'\n"
            "This is script2.sh in dir2\n"
            "This is script1.sh in dir1\n"
            "This is the main script\n"
        )

        # Check if the actual output from executing the compiled script matches the expected output
        self.assertEqual(execution_result.stdout, expected_output,
                         "The execution output did not match the expected result")

        # Inform about test success
        print("Success: `TestCompile` passed without errors.")


if __name__ == '__main__':
    unittest.main()

    # Uncomment below to test the main method directly:
    # from modashc import main
    # main(ENTRY_POINT, OUTPUT_FILE)
