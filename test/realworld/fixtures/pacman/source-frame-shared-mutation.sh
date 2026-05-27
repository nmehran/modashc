set -- changed one
source ./source-frame-nested-set.sh
frame_trace="${frame_trace}:shared=${1}/${2}/${#}"
return 5
