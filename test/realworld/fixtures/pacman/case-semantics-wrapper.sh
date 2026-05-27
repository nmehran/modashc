#!/bin/bash

case_semantics_trace=

case_mode='prod*'
case "$case_mode" in
  prod\*) source ./case-semantics-escaped.sh ;;
esac

case_mode='prod-eu'
case "$case_mode" in
  prod"-"eu) source ./case-semantics-mixed.sh ;&
  [[:digit:]]) source ./case-semantics-digit.sh ;;
esac

case_mode='5'
case "$case_mode" in
  [[:digit:]]) source ./case-semantics-digit.sh ;;
esac

case_pattern='stage-*'
case_mode='stage-us'
case "$case_mode" in
  $case_pattern) source ./case-semantics-variable.sh ;;&
  *) source ./case-semantics-default.sh ;;
esac

echo "case-semantics=$case_semantics_trace"
