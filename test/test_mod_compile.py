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
        # Build the command as a list of strings
        command = ['python', COMPILE_SCRIPT, self.entry_point, self.output_file]

        # Run the command
        result = subprocess.run(command, capture_output=True, text=True)

        # Check the result and print output
        self.assertEqual(result.returncode, 0, f"Error compiling output to '{self.output_file}' using `modashc.py`")

        # Optionally, check if the output file exists
        self.assertTrue(os.path.exists(self.output_file), "Output file was not created")
        if result.returncode == 0:
            print(f"Compiled output to '{self.output_file}' using `modashc.py`")
            if result.stdout:
                print(f"Output:\n{result.stdout}")
        else:
            print(f"Error compiling output to '{self.output_file}' using `modashc.py`")
            if result.stderr:
                print(f"Error:\n{result.stderr}")

        print("Success: `TestCompile` passed without errors.")


if __name__ == '__main__':
    unittest.main()

    # Uncomment below to test the main method directly:
    # from modashc import main
    # main(ENTRY_POINT, OUTPUT_FILE)
