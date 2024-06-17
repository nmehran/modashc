#!/bin/bash
# dir1/script6.sh

THIS_FILE="$BASH_SOURCE"
cd "$(dirname "${BASH_SOURCE}")" || exit 1
README_PATH="../../outputs/README.txt"
cat "$README_PATH"

echo "This is script6.sh in dir1"
