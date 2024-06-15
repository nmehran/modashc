#!/bin/bash

SOME_PATH="$(dirname "$0")/dir1"
HOME="./"

# Source configuration and utilities
source "$(dirname "$0")/dir1/script1.sh"
. "${SOME_PATH}/script3.sh"

source "${HOME}/sources/dir1/script2.sh"
source "$HOME/sources/dir1/script2.sh"


source "$SOME_PATH/script4.sh"

source "$(dirname "$SOME_PATH")/dir2/has spaces/script5.sh"


function foo() {
    echo "source hello/world"
}
