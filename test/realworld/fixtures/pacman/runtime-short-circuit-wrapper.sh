#!/bin/bash

false && eval "source ./missing-and.sh"
printf 'and-status:%s\n' "$?"
true || eval "source ./missing-or.sh"
printf 'or-status:%s\n' "$?"
