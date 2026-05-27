set -- changed one
source ./source-frame-nested-noop.sh "$@"
set -- final value
frame_trace="${frame_trace}:post=${1}/${2}/${#}"
return 7
