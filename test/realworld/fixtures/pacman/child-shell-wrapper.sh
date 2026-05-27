printf "wrapper:start\n"

( source ./child-shell-target.sh subshell; printf "subshell:%s\n" "$CHILD_VALUE" )
printf "parent-after-subshell:%s\n" "${CHILD_VALUE-unset}"

source ./child-shell-target.sh pipeline | sed 's/^/pipe:/'
printf "parent-after-pipeline:%s\n" "${CHILD_VALUE-unset}"

command_value="$(source ./child-shell-target.sh command; printf "command:%s" "$CHILD_VALUE")"
printf "[%s]\n" "$command_value"
printf "parent-after-command:%s\n" "${CHILD_VALUE-unset}"

cat <(source ./child-shell-target.sh process; printf "process:%s\n" "$CHILD_VALUE")
printf "parent-after-process:%s\n" "${CHILD_VALUE-unset}"

bash -c 'source ./child-shell-target.sh; printf "bash:%s\n" "$CHILD_VALUE"'
printf "parent-after-bash:%s\n" "${CHILD_VALUE-unset}"
