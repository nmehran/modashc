#!/bin/bash

# Ensure the script is run as root for proper permission management
if [[ $(id -u) -ne 0 ]]; then
    echo "This script must be run as root."
    exit 1
fi

# Verify that a script path has been provided
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 /path/to/main.sh"
    exit 1
fi

SCRIPT_PATH="$1"

# Check if the provided script file exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: The script does not exist at '$SCRIPT_PATH'."
    exit 1
fi

# Store original permissions and define a function to revert permissions
ORIGINAL_SCRIPT_PERMS=$(stat -c "%a" "$SCRIPT_PATH")
ORIGINAL_DIR_PERMS=$(stat -c "%a" "$(dirname "$SCRIPT_PATH")")

revert_permissions() {
    chmod "$ORIGINAL_SCRIPT_PERMS" "$SCRIPT_PATH"
    chmod "$ORIGINAL_DIR_PERMS" "$(dirname "$SCRIPT_PATH")"
}

# Set a trap to ensure permissions are always reverted on script exit
trap revert_permissions EXIT

# Temporarily make the script and its directory executable
chmod +x "$SCRIPT_PATH"
chmod +x "$(dirname "$SCRIPT_PATH")"

# Execute the script as 'modashc' using the restricted shell environment
echo "Executing script as 'modashc': $SCRIPT_PATH"
if sudo -u modashc /bin/bash "$SCRIPT_PATH"; then
  echo "Script executed successfully."
  exit 0
else
  echo "Script executed with errors."
  exit 1
fi