#!/bin/bash
# dir1/script6.sh

THIS_FILE="$BASH_SOURCE"
echo "This is the last dependency: script6.sh in dir1" && cd "$(dirname "${THIS_FILE}")" || exit 1
README_PATH="../../outputs/README.txt"
cat "$README_PATH"
