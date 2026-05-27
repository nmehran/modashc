MODASHC_RETURN_VALUE=before
printf 'return-lib:%s\n' "$MODASHC_RETURN_VALUE"
return 4
MODASHC_RETURN_VALUE=after
printf 'unreachable\n'
