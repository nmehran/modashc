# modashc

`modashc` aims to provide a tool for merging multiple Bash scripts into a single script, ensuring all dependencies, variables, and functions are properly resolved and included.

## Features

- **Merge Multiple Scripts**: Combines multiple Bash scripts into one, maintaining the order of dependencies.
- **Resolve Shell Functions**: Handles shell functions like `$(dirname ...)`, `$(basename ...)`, and `$(realpath ...)`.
- **Variable Substitution**: Substitutes variables using a provided context and environment variables.
- **Error Handling**: Validates paths and provides warnings for potential issues like unresolved variables.
- **Extract Components**: Extracts global variables, function definitions, and source statements from scripts.

## Limitations

- **Environment Specific**: `modashc` assumes a Unix-like environment for path and shell function handling. It may not work correctly on non-Unix systems.
- **Complex Expressions**: The tool may struggle with overly complex expressions or deeply nested shell functions that are not directly supported.
- **Limited Shell Function Support**: While it supports common shell functions like `$(dirname ...)`, `$(basename ...)`, and `$(realpath ...)`, other custom or less common shell functions may not be resolved correctly.
- **Variable Resolution**: `modashc` resolves variables based on the provided context and environment. Unresolved or dynamically generated variables at runtime may not be accurately substituted.
- **Error Reporting**: The tool provides basic warnings and error messages. However, detailed debugging information for complex scripts might require manual inspection.
- **Function Definitions**: The extraction of function definitions assumes standard Bash syntax. Non-standard or malformed function definitions may not be correctly identified and extracted.
- **Comment Handling**: By default, the tool strips comments. This might result in the loss of important inline documentation unless explicitly managed.
- **File System Changes**: `modashc` changes the working directory during script processing, which could affect scripts that rely on relative paths in a specific directory structure.

## Installation

1. Clone the repository:
   ```sh
   git clone https://github.com/nmehran/modashc.git
   cd modashc
   ```

## Usage

To use `modashc`, run the `main.py` script with the entry-point Bash script and the desired output file:

```sh
python modashc.py <entrypoint> <output>
```

### Arguments

- `<entrypoint>`: The entry-point Bash script that initiates the merging process.
- `<output>`: The output file where the merged script will be saved.

### Example

```sh
python modashc.py scripts/main.sh merged_output.sh
```

## How It Works

### File Structure

- `methods/sources.py`: Contains functions to resolve paths, variables, and shell functions.
- `methods/compile.py`: Contains functions to extract script components, merge files, and write the final output.
- `modashc.py`: Entry point for the CLI tool.

## Contributing

Contributions are welcome! Please submit a pull request or open an issue to discuss your ideas or report bugs.

## License

This project is licensed under the Apache 2.0 License. See the [LICENSE](./LICENSE) file for details.

---

By using `modashc`, you can efficiently manage and compile your Bash scripting projects into a single, organized script.