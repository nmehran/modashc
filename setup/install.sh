#!/bin/bash

# Set up strict error handling
set -euo pipefail

# Constants
BASE_DIR="/opt/modashc"
USER_HOME="$BASE_DIR/.user"
SCRIPT_DIR="$BASE_DIR/scripts"
MODASHC_SHELL_PATH="$SCRIPT_DIR/modashc_shell.sh"

# Include uninstall script to clean up any previous installations
echo "Checking for previous installations..."
if [ -f "$(dirname "$0")/uninstall.sh" ]; then
    echo "Running uninstallation of previous setup..."
    bash "$(dirname "$0")/uninstall.sh"
else
    echo "No uninstall script found, skipping..."
fi

# Create directories
echo "Creating directories..."
mkdir -p "$USER_HOME" "$SCRIPT_DIR"

# Copy the custom shell script to the appropriate directory
echo "Setting up the shell script..."
cp "$(dirname "$0")/modashc_shell.sh" "$SCRIPT_DIR/"

# Make the shell script executable
chmod +x "$MODASHC_SHELL_PATH"

# Check if the group exists and create if not
if ! getent group modashc >/dev/null; then
    echo "Creating group 'modashc'..."
    groupadd modashc
fi

# Create the user with the restricted shell and no standard home directory
echo "Creating user 'modashc'..."
useradd modashc -s "$MODASHC_SHELL_PATH" -d "$USER_HOME" -M -g modashc

# Set ownership and permissions
chown -R modashc:modashc "$BASE_DIR"
chmod -R 755 "$BASE_DIR"
chmod 700 "$USER_HOME"

# Create and configure .bashrc file
echo "Configuring .bashrc for restricted environment..."
touch "$USER_HOME/.bashrc"
echo "# Restricted environment settings" > "$USER_HOME/.bashrc"
chmod 644 "$USER_HOME/.bashrc"
chown modashc:modashc "$USER_HOME/.bashrc"

# Make user home directory and script immutable
chattr +i "$USER_HOME"
chattr +i "$MODASHC_SHELL_PATH"

# Ensure no other unnecessary files exist
rm -f "$USER_HOME/.bash_profile" "$USER_HOME/.profile"

echo "Installation complete: 'modashc' is now configured as a restricted user."
