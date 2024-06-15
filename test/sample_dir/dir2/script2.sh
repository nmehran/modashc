#!/bin/bash
# dir2/script2.sh

# Change directory to another script
cd "$(dirname "$BASH_SOURCE")" || exit 1
echo "BS: $BASH_SOURCE"
cd "../dir with spaces" || exit 1
source "./script3.sh"

echo "This is script2.sh in dir2"
