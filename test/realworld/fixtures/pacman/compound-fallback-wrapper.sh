compound_fallback_state=unset

if awk 'BEGIN { exit ENVIRON["MODASHC_SKIP_FALLBACK"] == "1" ? 0 : 1 }' || source ./compound-fallback-lib.sh; then
  echo "compound-fallback=${compound_fallback_state}"
else
  echo "compound-fallback=failed"
fi
