pattern_trace=

shopt -s extglob
GLOBIGNORE=./pattern-fixtures/skip.sh
for dep in ./pattern-fixtures/@(core|extra|skip).sh; do
  source "$dep"
done

pattern_mode=stage
case "$pattern_mode" in
  @(prod|stage)) source ./pattern-fixtures/case.sh ;;
  *) source ./pattern-fixtures/missing.sh ;;
esac

if [[ "$pattern_mode" == @(prod|stage) ]]; then
  source ./pattern-fixtures/predicate.sh
fi

GLOBIGNORE=./pattern-fixtures/extra.sh:./pattern-fixtures/skip.sh
if [ -f ./pattern-fixtures/@(core|extra).sh ]; then
  source ./pattern-fixtures/guard.sh
fi

echo "pattern=$pattern_trace"
