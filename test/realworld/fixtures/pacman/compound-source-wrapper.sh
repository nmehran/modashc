compound_source_state=unset

if source ./compound-source-lib.sh && awk 'BEGIN { exit 0 }'; then
  echo "compound-source=${compound_source_state}"
else
  echo "compound-source=skipped"
fi
