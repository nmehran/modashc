#!/bin/bash

ALLOWED_COMMANDS=(
"ls"
"cd"
"pwd"
"echo"
"env"
"cat"
"grep"
"find"
"head"
"tail"
"whoami"
"date"
"df"
"du"
"ps"
"dirname"
"basename"
"realpath"
"readlink"
"stat"
"which"
"type"
"id"
"printenv"
"xargs"
"awk"
"cut"
"tr"
"sed"
"sort"
"uniq"
"wc"
"locate"
"whereis"
"man"
"apropos"
"whatis"
)

# Function to check if a command is in the allowed list
command_is_allowed() {
    local cmd=$1
    for allowed_cmd in "${ALLOWED_COMMANDS[@]}"; do
        if [[ "$cmd" == "$allowed_cmd" ]]; then
            return 0
        fi
    done
    return 1
}

# Function to execute allowed commands or source scripts
execute_command() {
    local cmd=$1
    shift
    if command_is_allowed "$cmd"; then
        $cmd "$@"
    else
        echo "Command not allowed: $cmd"
        return 1
    fi
}

export -f execute_command command_is_allowed

# Set the shell prompt
PS1='restricted$ '

# Replace system command execution with the custom execute_command function
trap 'read -p "$PS1" cmd args; execute_command $cmd $args' DEBUG

# Run an interactive shell to catch commands
/bin/bash --norc --noprofile
