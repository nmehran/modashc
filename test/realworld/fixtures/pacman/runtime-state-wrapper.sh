#!/bin/bash

source ./runtime-state-lib.sh
printf 'value:%s\n' "$MODASHC_STATE_VALUE"
export -p | grep ' MODASHC_EXPORTED_VALUE='
modashc_fixture_function
