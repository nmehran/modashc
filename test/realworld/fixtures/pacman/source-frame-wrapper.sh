#!/bin/bash

frame_trace=

set -- outer
source ./source-frame-explicit-barrier.sh arg
explicit_status=$?
printf 'explicit-after:%s:%s:%s:%s:%s\n' "$1" "${2-}" "$#" "$explicit_status" "$frame_trace"

frame_trace=
set -- outer
source ./source-frame-shared-mutation.sh arg
shared_status=$?
printf 'shared-after:%s:%s:%s:%s:%s\n' "$1" "${2-}" "$#" "$shared_status" "$frame_trace"

frame_trace=
set -- outer
source ./source-frame-post-set.sh arg
post_status=$?
printf 'post-after:%s:%s:%s:%s:%s\n' "$1" "${2-}" "$#" "$post_status" "$frame_trace"

frame_trace=
set -- outer
source ./source-frame-set-shift.sh arg
set_shift_status=$?
printf 'set-shift-after:%s:%s:%s:%s:%s\n' "$1" "${2-}" "$#" "$set_shift_status" "$frame_trace"
