#!/bin/bash
# script5.sh
THIS_DIR="$(dirname "$0")"
cd "$THIS_DIR" || exit 1

source "${THIS_DIR}/dir1/script6.sh"

# Test importing script6.sh again:
source "${THIS_DIR}/dir1/script6.sh"

# Uncomment below to test recursion detection:
#source "${THIS_DIR}/dir1/script1.sh"

echo "This is script5.sh in the root directory"
