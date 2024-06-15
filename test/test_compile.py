import os
import subprocess


PWD = os.getcwd()

# Path to `compile.py`
COMPILE_SCRIPT = os.path.abspath(f"{PWD}/../methods/compile.py")


def test_compile(entry_point, output_file):

    # Build the command as a list of strings
    command = ['python', COMPILE_SCRIPT, os.path.abspath(entry_point), os.path.abspath(output_file)]

    # Run the command
    result = subprocess.run(command, capture_output=True, text=True)

    # Check the result and print output
    if result.returncode == 0:
        print(f"Successfully ran `compile.py`")
        if stdout := result.stdout:
            print(f"Output:\n{stdout}")
    else:
        print(f"Error running `compile.py")
        if stderr := result.stderr:
            print(f"Output:\n{stderr}")


if __name__ == '__main__':
    # Example usage
    test_entry_point = f'{PWD}/sources/main.sh'
    test_output_file = f'{PWD}/outputs/merged_script.sh'
    test_compile(test_entry_point, test_output_file)
