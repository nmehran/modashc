MODASHC_STATE_VALUE="${MODASHC_STATE_VALUE:-seed}:lib"
export MODASHC_EXPORTED_VALUE=exported-from-lib

modashc_fixture_function() {
	printf 'function:%s:%s\n' "$MODASHC_STATE_VALUE" "$MODASHC_EXPORTED_VALUE"
}
