#!/bin/bash

printf 'start:%s\n' "${PWD##*/}"
source ./runtime-cwd-lib.sh
printf 'after:%s:%s:%s\n' "${PWD##*/}" "$MODASHC_CWD_NESTED" "$MODASHC_CWD_STATUS"
