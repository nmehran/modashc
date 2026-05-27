#!/bin/bash

source ./runtime-return-lib.sh
status=$?
printf 'return-status:%s\n' "$status"
printf 'return-value:%s\n' "$MODASHC_RETURN_VALUE"
