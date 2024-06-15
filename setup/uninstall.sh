#!/bin/bash

# Set up strict error handling
set -euo pipefail

# Constants
BASE_DIR="/opt/modashc"

# Function to remove immutable attribute if file or directory exists
remove_immutable() {
    if [ -e "$1" ]; then
        echo "Removing immutable attribute from $1"
        sudo chattr -i "$1"
    fi
}

# Remove immutable attributes from the directories and files
echo "Checking for immutable attributes..."
remove_immutable "$BASE_DIR/.user"
remove_immutable "$BASE_DIR/scripts/modashc_shell.sh"
remove_immutable "$BASE_DIR"

# Remove installation directories
echo "Removing installation directories..."
sudo rm -rf "$BASE_DIR"

# Check if the user exists and remove
if id "modashc" &>/dev/null; then
    echo "Checking for active user processes..."
    if pkill -u "modashc"; then
        echo "Killed active processes for user 'modashc'."
    fi
    echo "Removing user 'modashc'..."
    sudo userdel -rf modashc 2>&1 | grep -v 'mail spool\|home directory' || echo "Failed to remove user 'modashc'. Please check manually."
fi

# Check if the group exists and remove
if getent group "modashc" &>/dev/null; then
    echo "Removing group 'modashc'..."
    groupdel modashc || echo "Failed to remove group 'modashc'. Please check manually."
fi

echo "Uninstallation complete. All components associated with 'modashc' have been removed."
