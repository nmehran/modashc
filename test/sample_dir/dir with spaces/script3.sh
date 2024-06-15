#!/bin/bash
# dir with spaces/script3.sh

# Define a variable and source a script using it
SCRIPT_DIR=$(dirname "$BASH_SOURCE")
source "$SCRIPT_DIR/../script4.sh"

echo "This is script3.sh in 'dir with spaces'"
