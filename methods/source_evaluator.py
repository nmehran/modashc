from __future__ import annotations

import ast
import copy
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

from methods.source_diagnostics import unsupported_source_error, with_source_diagnostic
from methods.source_effects import (
    ArrayAssignment,
    Assignment,
    CaseBlock,
    CdCommand,
    DisabledSourceSite,
    EvaluationResult,
    ExecutionModel,
    FunctionDef,
    ForLoop,
    IfBlock,
    OccurrenceModel,
    RawCommand,
    SetCommand,
    SourceEvent,
    SourceSite,
    StateSnapshot,
)
from methods.source_frontend import LineParserFrontend, ParserFrontend
from methods.source_resolver import (
    UnsupportedSourceError,
    contains_source_command,
    contains_nested_source_command,
    expand_glob_word,
    has_unquoted_brace_expansion,
    has_unquoted_extglob,
    contains_unquoted_token,
    has_unquoted_glob,
    parse_shell_words_preserving_quotes,
)
from methods.sources import (
    SOURCE_RESOLVER,
    change_directory,
    resolve_command,
    resolve_shell_path_commands,
    resolve_variable_references,
)
from methods.regex.utilities import strip_matching_quotes

ARRAY_INDEX_PATTERN = re.compile(r'\$\{([a-zA-Z_]\w*)\[(\d+)\]\}')
ARRAY_EXPANSION_PATTERN = re.compile(r'^\$\{([a-zA-Z_]\w*)\[@\]\}$')
SCALAR_REFERENCE_PATTERN = re.compile(r'\$(?:\{([a-zA-Z_]\w*|[0-9]+)\}|([a-zA-Z_]\w*|[0-9]+))')
SCALAR_WORD_PATTERN = re.compile(r'^\$(?:\{([a-zA-Z_]\w*|[0-9]+)\}|([a-zA-Z_]\w*|[0-9]+))$')
ASSIGNMENT_WORD_PATTERN = re.compile(r'^[a-zA-Z_]\w*(?:\+)?=.*$')
DEFAULT_IFS = " \t\n"
SHELL_OPTION_FLAGS = {
    'e': 'errexit',
    'E': 'errtrace',
    'f': 'noglob',
    'u': 'nounset',
}
GLOB_SHOPT_OPTIONS = frozenset({
    'dotglob',
    'extglob',
    'failglob',
    'globstar',
    'nocaseglob',
    'nullglob',
})
CONDITION_UNARY_FILE_OPERATORS = frozenset({'-e', '-f', '-d'})
CONDITION_UNARY_STRING_OPERATORS = frozenset({'-n', '-z'})
CONDITION_STRING_OPERATORS = frozenset({'=', '==', '!='})
CONDITION_INTEGER_OPERATORS = frozenset({'-eq', '-ne', '-gt', '-ge', '-lt', '-le'})
CONDITION_BINARY_OPERATORS = (
    CONDITION_STRING_OPERATORS
    | CONDITION_INTEGER_OPERATORS
    | frozenset({'=~'})
)
GREP_LITERAL_META_PATTERN = re.compile(r'[.\[\\*^$]')
POSIX_CLASS_PATTERN = re.compile(r'\[\[:[a-zA-Z_]+:\]\]')
PYTHON_ONLY_REGEX_PATTERN = re.compile(r'\(\?|\\[AbBdDsSwWZ]')
LAZY_REGEX_QUANTIFIER_PATTERN = re.compile(r'(?:[*+?]|\{[0-9]+(?:,[0-9]*)?\})\?')


@dataclass
class EvaluationState:
    cwd: Path
    variables: dict[str, str] = field(default_factory=dict)
    runtime_variables: dict[str, str] = field(default_factory=dict)
    arrays: dict[str, tuple[str, ...]] = field(default_factory=dict)
    functions: dict[str, FunctionDef] = field(default_factory=dict)
    function_variants: dict[str, tuple[FunctionDef, ...]] = field(default_factory=dict)
    shell_options: set[str] = field(default_factory=set)
    glob_options: set[str] = field(default_factory=set)
    bash_source_stack: tuple[Path, ...] = ()
    occurrence_context: OccurrenceModel = OccurrenceModel.ONCE
    condition_context: str | None = None
    ambiguous_cwd: bool = False
    ambiguous_variables: set[str] = field(default_factory=set)
    ambiguous_arrays: set[str] = field(default_factory=set)
    ambiguous_functions: set[str] = field(default_factory=set)
    ambiguous_shell_options: bool = False
    ambiguous_glob_options: bool = False
    function_call_stack: tuple[str, ...] = ()
    local_scopes: list[dict[str, tuple[bool, str | None, bool, str | None, bool]]] = field(default_factory=list)
    last_status: int | None = 0

    def resolver_context(self):
        return {
            'vars': self.variables,
            'runtime_vars': self.runtime_variables,
            'current_directory': str(self.cwd),
            'shell_options': self.shell_options,
            'glob_options': self.glob_options,
        }

    def runtime_context(self):
        return {
            'vars': self.runtime_variables,
            'current_directory': str(self.cwd),
            'shell_options': self.shell_options,
            'glob_options': self.glob_options,
        }

    def snapshot(self):
        return StateSnapshot(
            cwd=self.cwd,
            variables=dict(self.variables),
            arrays=dict(self.arrays),
            shell_options=frozenset(self.shell_options),
            glob_options=frozenset(self.glob_options),
            bash_source_stack=self.bash_source_stack,
        )

    def child_shell_copy(self):
        return EvaluationState(
            cwd=self.cwd,
            variables=copy.deepcopy(self.variables),
            runtime_variables=copy.deepcopy(self.runtime_variables),
            arrays=copy.deepcopy(self.arrays),
            functions=copy.deepcopy(self.functions),
            function_variants=copy.deepcopy(self.function_variants),
            shell_options=set(self.shell_options),
            glob_options=set(self.glob_options),
            bash_source_stack=self.bash_source_stack,
            occurrence_context=self.occurrence_context,
            condition_context=self.condition_context,
            ambiguous_cwd=self.ambiguous_cwd,
            ambiguous_variables=set(self.ambiguous_variables),
            ambiguous_arrays=set(self.ambiguous_arrays),
            ambiguous_functions=set(self.ambiguous_functions),
            ambiguous_shell_options=self.ambiguous_shell_options,
            ambiguous_glob_options=self.ambiguous_glob_options,
            function_call_stack=self.function_call_stack,
            local_scopes=copy.deepcopy(self.local_scopes),
            last_status=self.last_status,
        )

    def conditional_copy(self):
        state = self.child_shell_copy()
        state.occurrence_context = OccurrenceModel.CONDITIONAL
        return state

    def copy_from(self, other: EvaluationState):
        self.cwd = other.cwd
        self.variables = copy.deepcopy(other.variables)
        self.runtime_variables = copy.deepcopy(other.runtime_variables)
        self.arrays = copy.deepcopy(other.arrays)
        self.functions = copy.deepcopy(other.functions)
        self.function_variants = copy.deepcopy(other.function_variants)
        self.shell_options = set(other.shell_options)
        self.glob_options = set(other.glob_options)
        self.bash_source_stack = other.bash_source_stack
        self.occurrence_context = other.occurrence_context
        self.condition_context = other.condition_context
        self.ambiguous_cwd = other.ambiguous_cwd
        self.ambiguous_variables = set(other.ambiguous_variables)
        self.ambiguous_arrays = set(other.ambiguous_arrays)
        self.ambiguous_functions = set(other.ambiguous_functions)
        self.ambiguous_shell_options = other.ambiguous_shell_options
        self.ambiguous_glob_options = other.ambiguous_glob_options
        self.function_call_stack = other.function_call_stack
        self.local_scopes = copy.deepcopy(other.local_scopes)
        self.last_status = other.last_status


@dataclass
class FunctionReturnSignal(Exception):
    status: int
    node: RawCommand


@dataclass
class EvaluationOutcome:
    state: EvaluationState
    return_signal: FunctionReturnSignal | None = None


class SourceEvaluator:
    """Evaluate source effects for the supported IR subset without executing Bash."""

    def __init__(self, frontend: ParserFrontend | None = None, mode: str = "executable"):
        self.frontend = frontend or LineParserFrontend()
        self.mode = mode
        self.events: list[SourceEvent] = []
        self.disabled_sources: list[DisabledSourceSite] = []

    def evaluate(self, entrypoint: str | Path):
        entrypoint = Path(entrypoint).resolve()
        state = EvaluationState(
            cwd=entrypoint.parent,
            variables={'0': str(entrypoint), 'BASH_SOURCE': str(entrypoint)},
            runtime_variables={'0': str(entrypoint), 'BASH_SOURCE': str(entrypoint)},
            bash_source_stack=(entrypoint,),
        )
        self.events = []
        self.disabled_sources = []
        self._evaluate_file(entrypoint, state, ())
        return EvaluationResult(
            events=self._with_occurrence_models(self.events),
            disabled_sources=tuple(self.disabled_sources),
            final_state=state.snapshot(),
        )

    def _evaluate_file(self, path: Path, state: EvaluationState, stack: tuple[Path, ...]):
        path = path.resolve()
        if path in stack:
            chain = " -> ".join(str(item) for item in (*stack, path))
            raise RecursionError(f"Circular source dependency while evaluating: {chain}")
        current_stack = (*stack, path)

        content = path.read_text()
        ir = self.frontend.parse(path, content)
        previous_bash_source = state.variables.get('BASH_SOURCE')
        previous_runtime_bash_source = state.runtime_variables.get('BASH_SOURCE')
        previous_stack = state.bash_source_stack
        state.variables['BASH_SOURCE'] = str(path)
        state.runtime_variables['BASH_SOURCE'] = str(path)
        state.bash_source_stack = (*previous_stack, path) if previous_stack[-1:] != (path,) else previous_stack

        try:
            self._evaluate_nodes(ir.nodes, state, current_stack)
        finally:
            if previous_bash_source is None:
                state.variables.pop('BASH_SOURCE', None)
            else:
                state.variables['BASH_SOURCE'] = previous_bash_source
            if previous_runtime_bash_source is None:
                state.runtime_variables.pop('BASH_SOURCE', None)
            else:
                state.runtime_variables['BASH_SOURCE'] = previous_runtime_bash_source
            state.bash_source_stack = previous_stack

    def _evaluate_nodes(self, nodes, state: EvaluationState, stack: tuple[Path, ...]):
        nodes = tuple(nodes)
        for index, node in enumerate(nodes):
            try:
                if isinstance(node, Assignment):
                    self._apply_assignment(node, state)
                elif isinstance(node, ArrayAssignment):
                    self._apply_array_assignment(node, state)
                elif isinstance(node, CdCommand):
                    self._apply_cd(node, state)
                elif isinstance(node, SetCommand):
                    self._apply_set(node, state)
                elif isinstance(node, FunctionDef):
                    self._apply_function_def(node, state)
                elif isinstance(node, ForLoop):
                    self._apply_for_loop(node, state, stack)
                elif isinstance(node, IfBlock):
                    self._apply_if_block(node, state, stack)
                elif isinstance(node, CaseBlock):
                    self._apply_case_block(node, state, stack)
                elif isinstance(node, SourceSite):
                    self._apply_source_site(node, state, stack)
                elif isinstance(node, RawCommand):
                    self._apply_raw_command(node, state, stack)
            except FunctionReturnSignal:
                self._disable_unreachable_sources(nodes[index + 1:], "return")
                raise

    @staticmethod
    def _apply_assignment(node: Assignment, state: EvaluationState):
        if node.prefix == "local" and state.local_scopes:
            SourceEvaluator._capture_local_variable(node.name, state)

        runtime_context = state.runtime_context()
        runtime_value = resolve_variable_references(node.value, runtime_context)
        runtime_value = os.path.expandvars(runtime_value)
        runtime_value = resolve_shell_path_commands(runtime_value, str(state.cwd))
        runtime_value = strip_matching_quotes(runtime_value)

        context = state.resolver_context()
        value = strip_matching_quotes(resolve_variable_references(node.value, context))
        resolved_value, _ = resolve_command(value, context)
        state.variables[node.name] = resolved_value
        state.runtime_variables[node.name] = runtime_value
        state.ambiguous_variables.discard(node.name)
        state.last_status = 0

    @staticmethod
    def _capture_local_variable(name: str, state: EvaluationState):
        SourceEvaluator._capture_variable_in_scope(name, state.local_scopes[-1], state)

    @staticmethod
    def _capture_variable_in_scope(
        name: str,
        scope: dict[str, tuple[bool, str | None, bool, str | None, bool]],
        state: EvaluationState,
    ):
        if name in scope:
            return
        has_value = name in state.variables
        has_runtime_value = name in state.runtime_variables
        scope[name] = (
            has_value,
            state.variables.get(name),
            has_runtime_value,
            state.runtime_variables.get(name),
            name in state.ambiguous_variables,
        )

    @staticmethod
    def _restore_local_scope(
        local_scope: dict[str, tuple[bool, str | None, bool, str | None, bool]],
        state: EvaluationState,
    ):
        for name, (
            had_value,
            previous_value,
            had_runtime_value,
            previous_runtime_value,
            was_ambiguous,
        ) in reversed(local_scope.items()):
            if had_value and previous_value is not None:
                state.variables[name] = previous_value
            else:
                state.variables.pop(name, None)

            if had_runtime_value and previous_runtime_value is not None:
                state.runtime_variables[name] = previous_runtime_value
            else:
                state.runtime_variables.pop(name, None)

            if was_ambiguous:
                state.ambiguous_variables.add(name)
            else:
                state.ambiguous_variables.discard(name)

    @staticmethod
    def _apply_array_assignment(node: ArrayAssignment, state: EvaluationState):
        if node.is_exact:
            state.arrays[node.name] = node.values
            state.ambiguous_arrays.discard(node.name)
        state.last_status = 0

    @staticmethod
    def _apply_function_def(node: FunctionDef, state: EvaluationState):
        state.functions[node.name] = node
        state.function_variants.pop(node.name, None)
        state.ambiguous_functions.discard(node.name)
        state.last_status = 0

    @staticmethod
    def _apply_cd(node: CdCommand, state: EvaluationState):
        if state.ambiguous_cwd:
            SourceEvaluator._ensure_cd_state_can_resolve(node, state)
        context = state.resolver_context()
        state.cwd = Path(change_directory(node.path_expression, context))
        state.ambiguous_cwd = False
        state.last_status = 0

    @staticmethod
    def _apply_set(node: SetCommand, state: EvaluationState):
        index = 0
        while index < len(node.arguments):
            argument = node.arguments[index]
            if argument in {'-o', '+o'} and index + 1 < len(node.arguments):
                option = node.arguments[index + 1]
                if argument == '-o':
                    state.shell_options.add(option)
                else:
                    state.shell_options.discard(option)
                index += 2
                continue

            if len(argument) > 1 and argument[0] in {'-', '+'}:
                enabled = argument[0] == '-'
                for flag in argument[1:]:
                    option = SHELL_OPTION_FLAGS.get(flag)
                    if not option:
                        continue
                    if enabled:
                        state.shell_options.add(option)
                    else:
                        state.shell_options.discard(option)
            index += 1
        state.last_status = 0

    def _apply_for_loop(self, node: ForLoop, state: EvaluationState, stack: tuple[Path, ...]):
        try:
            words = self._resolve_loop_words(node, state)
        except UnsupportedSourceError:
            if self.mode == "context":
                return
            raise

        if not words:
            self._disable_unreachable_sources(node.body, f"for {node.variable} in {node.words_text}")
            return

        for word in words:
            state.variables[node.variable] = word
            state.runtime_variables[node.variable] = word
            state.ambiguous_variables.discard(node.variable)
            self._evaluate_nodes(node.body, state, stack)

    def _resolve_loop_words(self, node: ForLoop, state: EvaluationState):
        if not node.is_exact:
            raise self._unsupported_loop_words(node, "unsupported loop word list")

        raw_words = self._loop_raw_words(node)
        if len(raw_words) != len(node.words):
            raise self._unsupported_loop_words(node, "unsupported loop word list syntax")

        words = []
        for word, raw_word in zip(node.words, raw_words):
            words.extend(self._expand_loop_word(word, raw_word, node, state))

        return words

    def _loop_raw_words(self, node: ForLoop):
        try:
            return tuple(parse_shell_words_preserving_quotes(node.words_text))
        except UnsupportedSourceError as exc:
            raise self._unsupported_loop_words(node, "unsupported loop word list syntax") from exc

    def _expand_loop_word(self, word: str, raw_word: str, node: ForLoop, state: EvaluationState):
        if self._raw_word_is_single_quoted(raw_word):
            return [word]

        if '$(' in word or '`' in word:
            raise self._unsupported_loop_words(node, "loop word list is runtime-dynamic")

        array_match = ARRAY_EXPANSION_PATTERN.match(word)
        if array_match:
            array_name = array_match.group(1)
            values = state.arrays.get(array_name)
            if values is None:
                raise self._unsupported_loop_words(node, f"loop word list references unknown array: {array_name}")
            return list(values)

        if (
            has_unquoted_glob(raw_word)
            or has_unquoted_brace_expansion(raw_word)
            or has_unquoted_extglob(raw_word)
        ):
            try:
                return [
                    match.word
                    for match in expand_glob_word(word, state.resolver_context(), node.text, raw_pattern=raw_word)
                ]
            except UnsupportedSourceError as exc:
                raise self._unsupported_loop_words(node, str(exc)) from exc

        if has_unquoted_glob(word):
            raise self._unsupported_loop_words(node, "unsupported quoted loop glob")

        for match in SCALAR_REFERENCE_PATTERN.finditer(word):
            variable_name = match.group(1) or match.group(2)
            if variable_name in state.ambiguous_variables:
                raise self._unsupported_loop_words(node, f"loop word list references branch-dependent variable: {variable_name}")
            if variable_name not in state.runtime_variables:
                raise self._unsupported_loop_words(node, f"loop word list references unknown variable: {variable_name}")

        if '$' in word:
            resolved_word = resolve_variable_references(word, state.runtime_context())

            if "$" in resolved_word:
                raise self._unsupported_loop_words(node, "loop word list contains unresolved scalar expansion")

            if self._raw_word_is_unquoted_scalar(raw_word):
                return self._split_scalar_loop_word(resolved_word, node, state)

            if any(char.isspace() for char in resolved_word) and not self._raw_word_is_double_quoted(raw_word):
                raise self._unsupported_loop_words(
                    node,
                    "unsupported loop word list contains whitespace after scalar expansion",
                )
            if has_unquoted_glob(raw_word) or has_unquoted_glob(resolved_word):
                raise self._unsupported_loop_words(
                    node,
                    "unsupported loop word list requires scalar glob expansion",
                )
            return [resolved_word]

        return [word]

    def _split_scalar_loop_word(self, resolved_word: str, node: ForLoop, state: EvaluationState):
        self._ensure_default_ifs(node, state)
        words = []
        for field in resolved_word.split():
            if has_unquoted_glob(field):
                try:
                    words.extend(
                        match.word
                        for match in expand_glob_word(field, state.resolver_context(), node.text, raw_pattern=field)
                    )
                except UnsupportedSourceError as exc:
                    raise self._unsupported_loop_words(node, str(exc)) from exc
            else:
                words.append(field)
        return words

    @staticmethod
    def _ensure_default_ifs(node: ForLoop, state: EvaluationState):
        if 'IFS' not in state.runtime_variables:
            return
        if state.runtime_variables['IFS'] == DEFAULT_IFS:
            return
        raise SourceEvaluator._unsupported_loop_words(
            node,
            "unsupported scalar loop word splitting with nondefault IFS",
        )

    @staticmethod
    def _raw_word_is_unquoted_scalar(raw_word: str):
        stripped = raw_word.strip()
        return not stripped.startswith(('"', "'")) and bool(SCALAR_WORD_PATTERN.match(stripped))

    @staticmethod
    def _raw_word_is_single_quoted(raw_word: str):
        stripped = raw_word.strip()
        return len(stripped) >= 2 and stripped[0] == stripped[-1] == "'"

    @staticmethod
    def _raw_word_is_double_quoted(raw_word: str):
        stripped = raw_word.strip()
        return len(stripped) >= 2 and stripped[0] == stripped[-1] == '"'

    @staticmethod
    def _unsupported_loop_words(node: ForLoop, message: str):
        if "loop word" not in message:
            message = f"unsupported loop word list: {message}"
        return unsupported_source_error(
            str(node.location.path),
            node.location.line - 1,
            node.text,
            node.text,
            "unsupported.source.loop-word-list",
            message,
            "Use a literal finite list, known scalar variables, or an exact ${array[@]} expansion.",
        )

    def _apply_if_block(self, node: IfBlock, state: EvaluationState, stack: tuple[Path, ...]):
        outer_occurrence_context = state.occurrence_context
        outer_condition_context = state.condition_context
        statuses = []
        for branch in node.branches:
            if branch.condition is None:
                statuses.append("else")
                continue
            try:
                statuses.append(self._evaluate_condition(branch.condition, state))
            except UnsupportedSourceError as exc:
                if self.mode == "context":
                    statuses.append("unknown")
                    continue
                raise with_source_diagnostic(
                    exc,
                    str(node.location.path),
                    node.location.line - 1,
                    node.text,
                    node.text,
                    "unsupported.source.if-condition",
                ) from exc

        if self.mode == "context":
            self._apply_context_if_block(node, state, stack, statuses)
            state.occurrence_context = outer_occurrence_context
            state.condition_context = outer_condition_context
            return

        base_state = state.child_shell_copy()
        branch_outcomes = []
        branch_reachability = self._if_branch_reachability(statuses)
        occurrence_model = (
            OccurrenceModel.MUTUALLY_EXCLUSIVE
            if len(node.branches) > 1
            else OccurrenceModel.CONDITIONAL
        )
        for branch, is_reachable in zip(node.branches, branch_reachability):
            if not is_reachable:
                self._disable_unreachable_sources(branch.body, branch.condition or "else")
                branch_outcomes.append(EvaluationOutcome(base_state.child_shell_copy()))
                continue

            branch_state = state.child_shell_copy()
            branch_state.occurrence_context = occurrence_model
            branch_state.condition_context = branch.condition or "else"
            return_signal = None
            try:
                self._evaluate_nodes(branch.body, branch_state, stack)
            except FunctionReturnSignal as signal:
                return_signal = signal
            branch_outcomes.append(EvaluationOutcome(branch_state, return_signal))

        possible_outcomes = self._possible_if_outcomes(statuses, base_state, branch_outcomes)
        try:
            self._apply_possible_outcomes(node, state, possible_outcomes)
        finally:
            state.occurrence_context = outer_occurrence_context
            state.condition_context = outer_condition_context

    def _apply_context_if_block(
        self,
        node: IfBlock,
        state: EvaluationState,
        stack: tuple[Path, ...],
        statuses: list[str],
    ):
        branch_outcomes = []
        occurrence_model = (
            OccurrenceModel.MUTUALLY_EXCLUSIVE
            if len(node.branches) > 1
            else OccurrenceModel.CONDITIONAL
        )

        for branch in node.branches:
            branch_state = state.child_shell_copy()
            branch_state.occurrence_context = occurrence_model
            branch_state.condition_context = branch.condition or "else"
            return_signal = None
            try:
                self._evaluate_nodes(branch.body, branch_state, stack)
            except FunctionReturnSignal as signal:
                return_signal = signal
            branch_outcomes.append(EvaluationOutcome(branch_state, return_signal))

        possible_outcomes = self._possible_if_outcomes(statuses, state.child_shell_copy(), branch_outcomes)
        continuing_outcomes = [outcome for outcome in possible_outcomes if outcome.return_signal is None]
        returning_outcomes = [outcome for outcome in possible_outcomes if outcome.return_signal is not None]
        self._merge_possible_states(
            state,
            [outcome.state for outcome in continuing_outcomes or returning_outcomes],
        )

    @staticmethod
    def _if_branch_reachability(statuses: list[str]):
        reachable = []
        fallthrough_possible = True

        for status in statuses:
            if not fallthrough_possible or status == "false":
                reachable.append(False)
                continue

            reachable.append(True)
            if status in {"true", "else"}:
                fallthrough_possible = False

        return reachable

    @staticmethod
    def _possible_if_outcomes(
        statuses: list[str],
        base_state: EvaluationState,
        branch_outcomes: list[EvaluationOutcome],
    ):
        if not statuses:
            return [EvaluationOutcome(base_state)]

        if "unknown" not in statuses:
            for status, branch_outcome in zip(statuses, branch_outcomes):
                if status in {"true", "else"}:
                    return [branch_outcome]
            return [EvaluationOutcome(base_state)]

        possible_outcomes = []
        fallthrough_possible = True
        for status, branch_outcome in zip(statuses, branch_outcomes):
            if not fallthrough_possible:
                break
            if status == "false":
                continue
            if status == "true":
                possible_outcomes.append(branch_outcome)
                fallthrough_possible = False
            elif status == "else":
                possible_outcomes.append(branch_outcome)
                fallthrough_possible = False
            else:
                possible_outcomes.append(branch_outcome)

        if fallthrough_possible:
            possible_outcomes.append(EvaluationOutcome(base_state))
        return possible_outcomes

    def _apply_possible_outcomes(self, node, state: EvaluationState, outcomes: list[EvaluationOutcome]):
        returning_outcomes = [outcome for outcome in outcomes if outcome.return_signal is not None]
        continuing_outcomes = [outcome for outcome in outcomes if outcome.return_signal is None]

        if returning_outcomes and continuing_outcomes:
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.function-control",
                "unsupported branch-dependent function return",
                "Make function return flow exact before later source-aware effects.",
            )

        selected_outcomes = returning_outcomes or continuing_outcomes
        if returning_outcomes:
            first_status = returning_outcomes[0].return_signal.status
            if any(outcome.return_signal.status != first_status for outcome in returning_outcomes):
                raise unsupported_source_error(
                    str(node.location.path),
                    node.location.line - 1,
                    node.text,
                    node.text,
                    "unsupported.source.function-control",
                    "unsupported branch-dependent function return",
                    "Make function return status exact before later source-aware effects.",
                )
        self._merge_possible_states(state, [outcome.state for outcome in selected_outcomes])
        if returning_outcomes:
            raise returning_outcomes[0].return_signal

    def _apply_case_block(self, node: CaseBlock, state: EvaluationState, stack: tuple[Path, ...]):
        outer_occurrence_context = state.occurrence_context
        outer_condition_context = state.condition_context
        try:
            subject_value = self._case_subject_value(node.subject, state)
            self._validate_case_patterns(node)
        except UnsupportedSourceError as exc:
            if self.mode == "context":
                subject_value = None
            else:
                raise self._unsupported_case(
                    node,
                    exc.code or "unsupported.source.case",
                    str(exc),
                    exc.hint,
                ) from exc

        if self.mode == "executable":
            self._ensure_case_terminators_supported(node)

        if self.mode == "context":
            self._apply_context_case_block(node, state, stack, subject_value)
            state.occurrence_context = outer_occurrence_context
            state.condition_context = outer_condition_context
            return

        if subject_value is None:
            if not self._nodes_may_source(node.arms):
                self._apply_source_free_unknown_case_block(node, state, stack)
                state.occurrence_context = outer_occurrence_context
                state.condition_context = outer_condition_context
                return
            raise self._unsupported_case(
                node,
                "unsupported.source.case-subject",
                "unsupported case subject",
                "Use a literal, known scalar variable, or environment-provided subject.",
            )

        base_state = state.child_shell_copy()
        arm_outcomes = []
        reachable_arms = self._case_arm_reachability(node, subject_value)
        occurrence_model = (
            OccurrenceModel.MUTUALLY_EXCLUSIVE
            if len(node.arms) > 1
            else OccurrenceModel.CONDITIONAL
        )

        for arm, is_reachable in zip(node.arms, reachable_arms):
            condition = self._case_arm_condition(node, arm)
            if not is_reachable:
                self._disable_unreachable_sources(arm.body, condition)
                arm_outcomes.append(EvaluationOutcome(base_state.child_shell_copy()))
                continue

            arm_state = state.child_shell_copy()
            arm_state.occurrence_context = occurrence_model
            arm_state.condition_context = condition
            return_signal = None
            try:
                self._evaluate_nodes(arm.body, arm_state, stack)
            except FunctionReturnSignal as signal:
                return_signal = signal
            arm_outcomes.append(EvaluationOutcome(arm_state, return_signal))

        possible_outcomes = [
            arm_outcome
            for arm_outcome, is_reachable in zip(arm_outcomes, reachable_arms)
            if is_reachable
        ] or [EvaluationOutcome(base_state)]
        try:
            self._apply_possible_outcomes(node, state, possible_outcomes)
        finally:
            state.occurrence_context = outer_occurrence_context
            state.condition_context = outer_condition_context

    def _apply_context_case_block(
        self,
        node: CaseBlock,
        state: EvaluationState,
        stack: tuple[Path, ...],
        subject_value: str | None,
    ):
        occurrence_model = (
            OccurrenceModel.MUTUALLY_EXCLUSIVE
            if len(node.arms) > 1
            else OccurrenceModel.CONDITIONAL
        )
        arm_outcomes = []

        for arm in node.arms:
            arm_state = state.child_shell_copy()
            arm_state.occurrence_context = occurrence_model
            arm_state.condition_context = self._case_arm_condition(node, arm)
            return_signal = None
            try:
                self._evaluate_nodes(arm.body, arm_state, stack)
            except FunctionReturnSignal as signal:
                return_signal = signal
            arm_outcomes.append(EvaluationOutcome(arm_state, return_signal))

        if subject_value is None:
            possible_outcomes = arm_outcomes
            if not self._case_has_default_arm(node):
                possible_outcomes.append(EvaluationOutcome(state.child_shell_copy()))
        else:
            reachable_arms = self._case_arm_reachability(node, subject_value)
            possible_outcomes = [
                arm_outcome
                for arm_outcome, is_reachable in zip(arm_outcomes, reachable_arms)
                if is_reachable
            ] or [EvaluationOutcome(state.child_shell_copy())]

        selected_states = [
            outcome.state
            for outcome in possible_outcomes
            if outcome.return_signal is None
        ] or [outcome.state for outcome in possible_outcomes]
        self._merge_possible_states(state, selected_states)

    def _apply_source_free_unknown_case_block(self, node: CaseBlock, state: EvaluationState, stack: tuple[Path, ...]):
        arm_outcomes = []

        for arm in node.arms:
            arm_state = state.child_shell_copy()
            arm_state.occurrence_context = OccurrenceModel.MUTUALLY_EXCLUSIVE
            arm_state.condition_context = self._case_arm_condition(node, arm)
            return_signal = None
            try:
                self._evaluate_nodes(arm.body, arm_state, stack)
            except FunctionReturnSignal as signal:
                return_signal = signal
            arm_outcomes.append(EvaluationOutcome(arm_state, return_signal))

        possible_outcomes = arm_outcomes
        if not self._case_has_default_arm(node):
            possible_outcomes.append(EvaluationOutcome(state.child_shell_copy()))
        self._apply_possible_outcomes(node, state, possible_outcomes)

    def _case_subject_value(self, subject: str, state: EvaluationState):
        subject = subject.strip()
        if '$(' in subject or '`' in subject:
            raise UnsupportedSourceError(
                f"unsupported dynamic case subject: {subject}",
                code="unsupported.source.case-subject",
                hint="Use a literal, known scalar variable, or environment-provided subject.",
            )
        if ARRAY_INDEX_PATTERN.search(subject):
            raise UnsupportedSourceError(
                f"unsupported array case subject: {subject}",
                code="unsupported.source.case-subject",
                hint="Array case subjects need explicit array semantics.",
            )

        value = self._condition_value(subject, state)
        if value is not None:
            return value

        expanded = os.path.expandvars(strip_matching_quotes(subject))
        return None if "$" in expanded else expanded

    def _validate_case_patterns(self, node: CaseBlock):
        for arm in node.arms:
            for pattern in arm.patterns:
                self._validate_case_pattern(pattern)

    @staticmethod
    def _validate_case_pattern(pattern: str):
        stripped_pattern = pattern.strip()
        is_quoted_literal = SourceEvaluator._is_quoted_case_pattern(stripped_pattern)
        if '$(' in stripped_pattern or '`' in stripped_pattern:
            raise UnsupportedSourceError(
                f"unsupported dynamic case pattern: {stripped_pattern}",
                code="unsupported.source.case-pattern",
                hint="Use literal case patterns in the modeled subset.",
            )
        variable_names = {
            match.group(1) or match.group(2)
            for match in SCALAR_REFERENCE_PATTERN.finditer(stripped_pattern)
        }
        if variable_names:
            raise UnsupportedSourceError(
                f"unsupported variable case pattern: {stripped_pattern}",
                code="unsupported.source.case-pattern",
                hint="Variable-expanded case patterns need explicit pattern expansion semantics.",
            )
        if is_quoted_literal:
            return
        if "'" in stripped_pattern or '"' in stripped_pattern:
            raise UnsupportedSourceError(
                f"unsupported mixed-quoted case pattern: {stripped_pattern}",
                code="unsupported.source.case-pattern",
                hint="Mixed quoted case patterns need exact shell pattern normalization.",
            )
        if SourceEvaluator._contains_unquoted_backslash(stripped_pattern):
            raise UnsupportedSourceError(
                f"unsupported escaped case pattern: {stripped_pattern}",
                code="unsupported.source.case-pattern",
                hint="Backslash-escaped case patterns need exact shell pattern normalization.",
            )
        if re.search(r'\[:[a-zA-Z_]+:\]', stripped_pattern):
            raise UnsupportedSourceError(
                f"unsupported POSIX class case pattern: {stripped_pattern}",
                code="unsupported.source.case-pattern",
                hint="POSIX character classes need exact shell pattern semantics.",
            )
        if any(contains_unquoted_token(stripped_pattern, token) for token in {"@(", "!(", "+(", "?(", "*("}):
            raise UnsupportedSourceError(
                f"unsupported extglob case pattern: {stripped_pattern}",
                code="unsupported.source.case-pattern",
                hint="Extglob case patterns need explicit shell-option semantics.",
            )

    def _ensure_case_terminators_supported(self, node: CaseBlock):
        for arm in node.arms:
            if arm.terminator != ";;":
                raise self._unsupported_case(
                    node,
                    "unsupported.source.case-terminator",
                    f"unsupported case terminator: {arm.terminator}",
                    "Case fallthrough terminators need explicit fallthrough semantics.",
                )

    def _case_arm_reachability(self, node: CaseBlock, subject_value: str):
        reachable = []
        matched = False
        for arm in node.arms:
            is_match = not matched and self._case_arm_matches(arm, subject_value)
            reachable.append(is_match)
            matched = matched or is_match
        return reachable

    def _case_arm_matches(self, arm, subject_value: str):
        return any(self._case_pattern_matches(pattern, subject_value) for pattern in arm.patterns)

    @staticmethod
    def _case_pattern_matches(pattern: str, subject_value: str):
        stripped_pattern = pattern.strip()
        quoted = SourceEvaluator._is_quoted_case_pattern(stripped_pattern)
        pattern_value = strip_matching_quotes(stripped_pattern)
        if quoted:
            return subject_value == pattern_value
        pattern_value = SourceEvaluator._normalize_case_glob_pattern(pattern_value)
        return fnmatchcase(subject_value, pattern_value)

    @staticmethod
    def _is_quoted_case_pattern(pattern: str):
        return (
            len(pattern) >= 2
            and pattern[0] == pattern[-1]
            and pattern[0] in {"'", '"'}
        )

    @staticmethod
    def _contains_unquoted_backslash(text: str):
        in_single_quote = False
        in_double_quote = False

        for char in text:
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                continue

            if char == '\\' and not in_single_quote and not in_double_quote:
                return True

        return False

    @staticmethod
    def _normalize_case_glob_pattern(pattern: str):
        return re.sub(r'\[\^', '[!', pattern)

    @staticmethod
    def _case_has_default_arm(node: CaseBlock):
        return any(
            any(SourceEvaluator._case_pattern_matches(pattern, "") for pattern in arm.patterns)
            for arm in node.arms
        )

    @staticmethod
    def _case_arm_condition(node: CaseBlock, arm):
        return f"case {node.subject} in {'|'.join(arm.patterns)}"

    @staticmethod
    def _unsupported_case(node: CaseBlock, code: str, message: str, hint: str | None = None):
        return unsupported_source_error(
            str(node.location.path),
            node.location.line - 1,
            node.text,
            node.text,
            code,
            message,
            hint,
        )

    @staticmethod
    def _merge_possible_states(target: EvaluationState, possible_states: list[EvaluationState]):
        if not possible_states:
            return
        if len(possible_states) == 1:
            target.copy_from(possible_states[0])
            return

        first = possible_states[0]
        target.cwd = first.cwd
        target.ambiguous_cwd = any(state.ambiguous_cwd for state in possible_states) or any(
            state.cwd != first.cwd for state in possible_states
        )

        target.ambiguous_variables.clear()
        SourceEvaluator._merge_state_mapping(
            target.variables,
            [state.variables for state in possible_states],
            target.ambiguous_variables,
            [state.ambiguous_variables for state in possible_states],
            clear_ambiguous=False,
        )
        SourceEvaluator._merge_state_mapping(
            target.runtime_variables,
            [state.runtime_variables for state in possible_states],
            target.ambiguous_variables,
            [state.ambiguous_variables for state in possible_states],
            clear_ambiguous=False,
        )
        SourceEvaluator._merge_state_mapping(
            target.arrays,
            [state.arrays for state in possible_states],
            target.ambiguous_arrays,
            [state.ambiguous_arrays for state in possible_states],
        )
        SourceEvaluator._merge_function_state(target, possible_states)

        first_shell_options = first.shell_options
        if any(state.ambiguous_shell_options for state in possible_states) or any(
            state.shell_options != first_shell_options for state in possible_states
        ):
            target.ambiguous_shell_options = True
        else:
            target.shell_options = set(first_shell_options)
            target.ambiguous_shell_options = False

        first_glob_options = first.glob_options
        if any(state.ambiguous_glob_options for state in possible_states) or any(
            state.glob_options != first_glob_options for state in possible_states
        ):
            target.ambiguous_glob_options = True
        else:
            target.glob_options = set(first_glob_options)
            target.ambiguous_glob_options = False

        first_last_status = first.last_status
        target.last_status = (
            first_last_status
            if all(state.last_status == first_last_status for state in possible_states)
            else None
        )

    @staticmethod
    def _merge_state_mapping(target: dict, state_mappings: list[dict], ambiguous: set[str],
                             ambiguous_sets: list[set[str]], clear_ambiguous: bool = True):
        merged = {}
        if clear_ambiguous:
            ambiguous.clear()
        keys = set().union(*(mapping.keys() for mapping in state_mappings), *ambiguous_sets)
        for key in keys:
            values = [mapping.get(key) for mapping in state_mappings]
            if key in set().union(*ambiguous_sets) or any(value != values[0] for value in values[1:]):
                ambiguous.add(key)
                continue
            if values[0] is not None:
                merged[key] = copy.deepcopy(values[0])
        target.clear()
        target.update(merged)

    @staticmethod
    def _merge_function_state(target: EvaluationState, possible_states: list[EvaluationState]):
        target.functions.clear()
        target.function_variants.clear()
        target.ambiguous_functions.clear()

        keys = set().union(
            *(state.functions.keys() for state in possible_states),
            *(state.function_variants.keys() for state in possible_states),
            *(state.ambiguous_functions for state in possible_states),
        )
        for key in keys:
            if any(key in state.ambiguous_functions for state in possible_states):
                target.ambiguous_functions.add(key)
                continue

            variants_by_signature = {}
            missing = False
            for state in possible_states:
                variants = state.function_variants.get(key)
                if variants is None:
                    function_def = state.functions.get(key)
                    variants = (function_def,) if function_def is not None else ()
                if not variants:
                    missing = True
                    continue
                for function_def in variants:
                    signature_variants = variants_by_signature.setdefault(
                        SourceEvaluator._function_signature(function_def),
                        [],
                    )
                    if function_def not in signature_variants:
                        signature_variants.append(function_def)

            if missing or len(variants_by_signature) != 1:
                target.ambiguous_functions.add(key)
                continue

            variants = tuple(next(iter(variants_by_signature.values())))
            target.functions[key] = variants[0]
            if len(variants) > 1:
                target.function_variants[key] = variants

    @staticmethod
    def _function_signature(function_def: FunctionDef):
        return (
            "function",
            function_def.name,
            tuple(SourceEvaluator._node_signature(node) for node in function_def.body),
        )

    @staticmethod
    def _node_signature(node):
        if isinstance(node, Assignment):
            return ("assignment", node.name, node.value, node.prefix)
        if isinstance(node, ArrayAssignment):
            return ("array", node.name, node.values, node.is_exact)
        if isinstance(node, CdCommand):
            return ("cd", node.path_expression)
        if isinstance(node, SetCommand):
            return ("set", node.arguments)
        if isinstance(node, FunctionDef):
            return SourceEvaluator._function_signature(node)
        if isinstance(node, ForLoop):
            return (
                "for",
                node.variable,
                node.words,
                node.words_text,
                node.is_exact,
                tuple(SourceEvaluator._node_signature(child) for child in node.body),
            )
        if isinstance(node, IfBlock):
            return (
                "if",
                tuple(
                    (
                        branch.keyword,
                        branch.condition,
                        tuple(SourceEvaluator._node_signature(child) for child in branch.body),
                    )
                    for branch in node.branches
                ),
            )
        if isinstance(node, CaseBlock):
            return (
                "case",
                node.subject,
                tuple(
                    (
                        arm.patterns,
                        arm.terminator,
                        tuple(SourceEvaluator._node_signature(child) for child in arm.body),
                    )
                    for arm in node.arms
                ),
            )
        if isinstance(node, SourceSite):
            return (
                "source",
                node.command_name,
                node.source_expression,
                node.separator,
                node.is_control_flow,
            )
        if isinstance(node, RawCommand):
            return ("raw", node.text)
        return (type(node).__name__, node.text)

    def _evaluate_condition(self, condition: str, state: EvaluationState):
        condition = condition.strip()
        if not condition:
            raise UnsupportedSourceError(f"unsupported empty if condition: {condition}")
        if '$(' in condition or '`' in condition:
            raise UnsupportedSourceError(f"unsupported dynamic if condition: {condition}")

        if condition.startswith("((") and condition.endswith("))"):
            return self._evaluate_arithmetic_condition(condition[2:-2].strip(), state, condition)

        try:
            words = self._condition_words(condition)
        except UnsupportedSourceError:
            return self._evaluate_command_condition(condition, state)

        if not words:
            raise UnsupportedSourceError(f"unsupported empty if condition: {condition}")
        return self._evaluate_condition_tokens(words, state, condition)

    def _evaluate_condition_tokens(self, words: list[str], state: EvaluationState, condition: str):
        result, index = self._parse_condition_or(words, 0, state, condition)
        if index != len(words):
            raise UnsupportedSourceError(f"unsupported if condition: {condition}")
        return result

    def _parse_condition_or(self, words: list[str], index: int, state: EvaluationState, condition: str):
        left, index = self._parse_condition_and(words, index, state, condition)
        while index < len(words) and words[index] == "||":
            right, index = self._parse_condition_and(words, index + 1, state, condition)
            left = self._condition_or(left, right)
        return left, index

    def _parse_condition_and(self, words: list[str], index: int, state: EvaluationState, condition: str):
        left, index = self._parse_condition_not(words, index, state, condition)
        while index < len(words) and words[index] == "&&":
            right, index = self._parse_condition_not(words, index + 1, state, condition)
            left = self._condition_and(left, right)
        return left, index

    def _parse_condition_not(self, words: list[str], index: int, state: EvaluationState, condition: str):
        if index >= len(words):
            raise UnsupportedSourceError(f"unsupported if condition: {condition}")
        if words[index] == "!":
            result, next_index = self._parse_condition_not(words, index + 1, state, condition)
            return self._condition_not(result), next_index
        if words[index] == "(":
            result, next_index = self._parse_condition_or(words, index + 1, state, condition)
            if next_index >= len(words) or words[next_index] != ")":
                raise UnsupportedSourceError(f"unsupported if condition grouping: {condition}")
            return result, next_index + 1
        return self._parse_condition_atom(words, index, state, condition)

    def _parse_condition_atom(self, words: list[str], index: int, state: EvaluationState, condition: str):
        if index >= len(words) or words[index] in {")", "&&", "||"}:
            raise UnsupportedSourceError(f"unsupported if condition: {condition}")

        if words[index] in CONDITION_UNARY_FILE_OPERATORS | CONDITION_UNARY_STRING_OPERATORS:
            if index + 1 >= len(words):
                raise UnsupportedSourceError(f"unsupported if condition: {condition}")
            return self._evaluate_condition_unary(words[index], words[index + 1], state, condition), index + 2

        if index + 1 < len(words) and words[index + 1] in CONDITION_BINARY_OPERATORS:
            if index + 2 >= len(words):
                raise UnsupportedSourceError(f"unsupported if condition: {condition}")
            return self._evaluate_condition_binary(
                words[index],
                words[index + 1],
                words[index + 2],
                state,
                condition,
            ), index + 3

        value = self._condition_value(words[index], state)
        if value is None:
            return "unknown", index + 1
        return ("true" if bool(value) else "false"), index + 1

    def _evaluate_condition_unary(self, operator: str, operand: str, state: EvaluationState, condition: str):
        if operator in CONDITION_UNARY_FILE_OPERATORS:
            if has_unquoted_glob(operand):
                raise UnsupportedSourceError(f"unsupported glob if condition: {condition}")
            path = self._condition_path(operand, state, condition)
            if path is None:
                return "unknown"
            result = path.exists()
            if operator == "-f":
                result = path.is_file()
            elif operator == "-d":
                result = path.is_dir()
            return "true" if result else "false"

        value = self._condition_value(operand, state)
        if value is None:
            return "unknown"
        result = bool(value) if operator == "-n" else not bool(value)
        return "true" if result else "false"

    def _evaluate_condition_binary(self, left_token: str, operator: str, right_token: str,
                                   state: EvaluationState, condition: str):
        if operator in CONDITION_STRING_OPERATORS:
            is_double_bracket = condition.strip().startswith("[[")
            if not is_double_bracket and (has_unquoted_glob(left_token) or has_unquoted_glob(right_token)):
                raise UnsupportedSourceError(f"unsupported glob if condition: {condition}")
            left = self._condition_value(left_token, state)
            right = self._condition_value(right_token, state)
            if left is None or right is None:
                return "unknown"
            if is_double_bracket and self._condition_rhs_is_pattern(right_token, right):
                result = fnmatchcase(left, right)
            else:
                result = left == right
            if operator == "!=":
                result = not result
            return "true" if result else "false"

        if operator in CONDITION_INTEGER_OPERATORS:
            left = self._condition_integer_value(left_token, state, condition)
            right = self._condition_integer_value(right_token, state, condition)
            if left is None or right is None:
                return "unknown"
            comparisons = {
                "-eq": left == right,
                "-ne": left != right,
                "-gt": left > right,
                "-ge": left >= right,
                "-lt": left < right,
                "-le": left <= right,
            }
            return "true" if comparisons[operator] else "false"

        if operator == "=~":
            if not condition.strip().startswith("[["):
                raise UnsupportedSourceError(f"unsupported regex if condition: {condition}")
            return self._evaluate_condition_regex(left_token, right_token, state, condition)

        raise UnsupportedSourceError(f"unsupported if condition: {condition}")

    @staticmethod
    def _condition_rhs_is_pattern(raw_token: str, resolved_value: str):
        if has_unquoted_glob(raw_token):
            return True
        if SourceEvaluator._raw_word_is_single_quoted(raw_token) or SourceEvaluator._raw_word_is_double_quoted(raw_token):
            return False
        return has_unquoted_glob(resolved_value)

    @staticmethod
    def _condition_and(left: str, right: str):
        if left == "false" or right == "false":
            return "false"
        if left == "true" and right == "true":
            return "true"
        return "unknown"

    @staticmethod
    def _condition_or(left: str, right: str):
        if left == "true" or right == "true":
            return "true"
        if left == "false" and right == "false":
            return "false"
        return "unknown"

    @staticmethod
    def _condition_not(result: str):
        if result == "true":
            return "false"
        if result == "false":
            return "true"
        return "unknown"

    def _evaluate_condition_regex(self, left_token: str, right_token: str, state: EvaluationState, condition: str):
        left = self._condition_value(left_token, state)
        pattern = self._condition_value(right_token, state)
        if left is None or pattern is None:
            return "unknown"
        if self._raw_word_is_single_quoted(right_token) or self._raw_word_is_double_quoted(right_token):
            pattern = re.escape(pattern)
        self._ensure_supported_regex_pattern(pattern, condition)
        try:
            return "true" if re.search(pattern, left) else "false"
        except re.error as exc:
            raise UnsupportedSourceError(f"unsupported regex if condition: {condition} ({exc})") from exc

    def _evaluate_command_condition(self, condition: str, state: EvaluationState):
        try:
            words = parse_shell_words_preserving_quotes(condition)
        except UnsupportedSourceError as exc:
            raise UnsupportedSourceError(f"unsupported if condition syntax: {condition}") from exc
        if not words:
            raise UnsupportedSourceError(f"unsupported empty if condition: {condition}")

        command_name = strip_matching_quotes(words[0])
        if command_name == "grep":
            return self._evaluate_grep_condition(words, state, condition)
        raise UnsupportedSourceError(f"unsupported command if condition: {condition}")

    def _evaluate_grep_condition(self, words: list[str], state: EvaluationState, condition: str):
        options = set()
        index = 1
        while index < len(words):
            option = strip_matching_quotes(words[index])
            if option == "--":
                index += 1
                break
            if not option.startswith("-") or option == "-":
                break
            for flag in option[1:]:
                if flag not in {"q", "E", "F", "s"}:
                    raise UnsupportedSourceError(f"unsupported grep option in if condition: {condition}")
                options.add(flag)
            index += 1

        if "q" not in options:
            raise UnsupportedSourceError(f"unsupported grep if condition without -q: {condition}")
        if {"E", "F"} <= options:
            raise UnsupportedSourceError(f"unsupported grep if condition with both -E and -F: {condition}")
        if len(words) - index != 2:
            raise UnsupportedSourceError(f"unsupported grep if condition arguments: {condition}")

        pattern = self._condition_value(words[index], state)
        path = self._condition_path(words[index + 1], state, condition)
        if pattern is None or path is None:
            return "unknown"
        if not path.is_file():
            return "false"

        if "F" in options:
            matched = self._file_contains_literal(path, pattern)
        elif "E" in options:
            self._ensure_supported_regex_pattern(pattern, condition, "grep regex")
            try:
                regex = re.compile(pattern)
            except re.error as exc:
                raise UnsupportedSourceError(f"unsupported grep regex in if condition: {condition} ({exc})") from exc
            matched = self._file_matches_regex(path, regex)
        else:
            if GREP_LITERAL_META_PATTERN.search(pattern):
                raise UnsupportedSourceError(f"unsupported basic-regex grep if condition: {condition}")
            matched = self._file_contains_literal(path, pattern)

        return "true" if matched else "false"

    @staticmethod
    def _ensure_supported_regex_pattern(pattern: str, condition: str, label: str = "regex"):
        if POSIX_CLASS_PATTERN.search(pattern):
            raise UnsupportedSourceError(f"unsupported POSIX {label} in if condition: {condition}")
        if PYTHON_ONLY_REGEX_PATTERN.search(pattern) or LAZY_REGEX_QUANTIFIER_PATTERN.search(pattern):
            raise UnsupportedSourceError(f"unsupported Python-specific {label} in if condition: {condition}")

    @staticmethod
    def _file_contains_literal(path: Path, needle: str):
        with path.open('r', errors='ignore') as file:
            return any(needle in line for line in file)

    @staticmethod
    def _file_matches_regex(path: Path, regex):
        with path.open('r', errors='ignore') as file:
            return any(regex.search(line) for line in file)

    def _evaluate_arithmetic_condition(self, expression: str, state: EvaluationState, condition: str):
        if not expression:
            raise UnsupportedSourceError(f"unsupported empty arithmetic if condition: {condition}")
        value = self._evaluate_arithmetic_expression(expression, state, condition)
        if value is None:
            return "unknown"
        return "true" if bool(value) else "false"

    def _evaluate_arithmetic_expression(self, expression: str, state: EvaluationState, condition: str):
        normalized = self._normalize_arithmetic_expression(expression)
        try:
            tree = ast.parse(normalized, mode="eval")
        except SyntaxError as exc:
            raise UnsupportedSourceError(f"unsupported arithmetic if condition: {condition}") from exc
        return self._evaluate_arithmetic_ast(tree.body, state, condition)

    @staticmethod
    def _normalize_arithmetic_expression(expression: str):
        normalized = re.sub(r'\$\{([a-zA-Z_]\w*)\}', r'\1', expression)
        normalized = re.sub(r'\$([a-zA-Z_]\w*)', r'\1', normalized)
        normalized = normalized.replace("&&", " and ")
        normalized = normalized.replace("||", " or ")
        normalized = re.sub(r'(?<![=!<>])!(?!=)', ' not ', normalized)
        normalized = re.sub(r'(?<!/)/(?!/)', '//', normalized)
        return normalized

    def _evaluate_arithmetic_ast(self, node, state: EvaluationState, condition: str):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, bool)):
            return int(node.value)

        if isinstance(node, ast.Name):
            return self._arithmetic_name_value(node.id, state, condition)

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            operand = self._evaluate_arithmetic_ast(node.operand, state, condition)
            if operand is None:
                return None
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.USub):
                return -operand
            return 0 if bool(operand) else 1

        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
            left = self._evaluate_arithmetic_ast(node.left, state, condition)
            right = self._evaluate_arithmetic_ast(node.right, state, condition)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise UnsupportedSourceError(f"unsupported arithmetic division by zero in if condition: {condition}")
            if isinstance(node.op, ast.FloorDiv):
                return int(left / right)
            return left % right

        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [self._evaluate_arithmetic_ast(value, state, condition) for value in node.values]
            if any(value is None for value in values):
                return None
            if isinstance(node.op, ast.And):
                return int(all(bool(value) for value in values))
            return int(any(bool(value) for value in values))

        if isinstance(node, ast.Compare):
            left = self._evaluate_arithmetic_ast(node.left, state, condition)
            if left is None:
                return None
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._evaluate_arithmetic_ast(comparator, state, condition)
                if right is None:
                    return None
                if not self._arithmetic_compare(left, operator, right, condition):
                    return 0
                left = right
            return 1

        raise UnsupportedSourceError(f"unsupported arithmetic if condition: {condition}")

    @staticmethod
    def _arithmetic_compare(left: int, operator, right: int, condition: str):
        if isinstance(operator, ast.Eq):
            return left == right
        if isinstance(operator, ast.NotEq):
            return left != right
        if isinstance(operator, ast.Lt):
            return left < right
        if isinstance(operator, ast.LtE):
            return left <= right
        if isinstance(operator, ast.Gt):
            return left > right
        if isinstance(operator, ast.GtE):
            return left >= right
        raise UnsupportedSourceError(f"unsupported arithmetic comparison in if condition: {condition}")

    @staticmethod
    def _arithmetic_name_value(name: str, state: EvaluationState, condition: str):
        if name in state.ambiguous_variables:
            return None
        raw_value = state.runtime_variables.get(name, os.environ.get(name, "0"))
        raw_value = strip_matching_quotes(str(raw_value))
        if not re.fullmatch(r'[+-]?\d+', raw_value):
            raise UnsupportedSourceError(f"unsupported non-integer arithmetic variable in if condition: {condition}")
        return int(raw_value)

    @staticmethod
    def _condition_words(condition: str):
        stripped = condition.strip()
        if stripped.startswith("[[") and stripped.endswith("]]"):
            stripped = stripped[2:-2].strip()
        elif stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1].strip()
        elif stripped.startswith("test "):
            stripped = stripped[5:].strip()
        else:
            raise UnsupportedSourceError(f"unsupported if condition syntax: {condition}")
        return parse_shell_words_preserving_quotes(stripped)

    @staticmethod
    def _condition_value(value: str, state: EvaluationState):
        variable_names = [match.group(1) or match.group(2) for match in SCALAR_REFERENCE_PATTERN.finditer(value)]
        if any(name in state.ambiguous_variables for name in variable_names):
            return None
        if any(name not in state.runtime_variables and f"${name}" in value for name in variable_names):
            return None

        resolved = resolve_variable_references(value, state.runtime_context())
        if SCALAR_REFERENCE_PATTERN.search(resolved):
            return None
        resolved = os.path.expandvars(resolved)
        return strip_matching_quotes(resolved)

    def _condition_integer_value(self, value: str, state: EvaluationState, condition: str):
        resolved = self._condition_value(value, state)
        if resolved is None:
            return None
        if not re.fullmatch(r'[+-]?\d+', resolved):
            raise UnsupportedSourceError(f"unsupported integer if condition: {condition}")
        return int(resolved)

    @staticmethod
    def _condition_path(value: str, state: EvaluationState, condition: str):
        if state.ambiguous_cwd:
            raise UnsupportedSourceError(f"unsupported branch-dependent cwd in if condition: {condition}")
        resolved = SourceEvaluator._condition_value(value, state)
        if resolved is None:
            return None
        resolved = resolve_shell_path_commands(resolved, str(state.cwd))
        path = Path(resolved)
        if not path.is_absolute():
            path = state.cwd / path
        return path.resolve()

    def _apply_source_site(self, node: SourceSite, state: EvaluationState, stack: tuple[Path, ...]):
        if self._source_site_skipped_by_known_status(node, state):
            return

        if not self._is_plain_source_site(node) and self.mode == "executable":
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.command-unresolved",
                "unsupported unresolved source command",
                "Only direct source and dot commands can be lowered in executable mode.",
            )

        if node.is_control_flow and self.mode == "executable":
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.control-flow",
                "unsupported source in control flow",
                "Control-flow source sites need modeled branch semantics before executable lowering.",
            )
        is_context_control_flow = node.is_control_flow and self.mode == "context"

        try:
            self._ensure_source_state_can_resolve(node, node.source_expression, state)
            resolved_expression = self._expand_array_indexes(node.source_expression, node, state)
        except UnsupportedSourceError:
            if self.mode == "context":
                return
            raise

        source_site = f"{node.command_name} {node.source_expression.strip()}"
        try:
            resolved_source = SOURCE_RESOLVER.resolve_source_expression(
                resolved_expression,
                source_site,
                state.resolver_context(),
            )
        except UnsupportedSourceError as exc:
            if self.mode == "context":
                return
            raise with_source_diagnostic(
                exc,
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.resolution",
            ) from exc

        if not resolved_source:
            if self.mode == "context":
                return
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.unresolved",
                "unsupported unresolved source",
                "Use a statically resolvable source path for IR evaluation.",
            )

        source_path = Path(resolved_source.path)
        source_value = resolved_source.source_value or self._source_runtime_value(resolved_expression, state)
        if is_context_control_flow:
            branch_state = state.conditional_copy()
            self._record_event(
                source_path,
                node,
                node.source_expression,
                source_site,
                ExecutionModel.PARENT_SOURCE,
                "source",
                state,
                occurrence_model=OccurrenceModel.CONDITIONAL,
                source_value=source_value,
            )
            self._evaluate_file(source_path, branch_state, stack)
            return

        self._record_and_descend(
            source_path,
            node,
            node.source_expression,
            source_site,
            state,
            stack,
            ExecutionModel.PARENT_SOURCE,
            "source",
            source_value,
        )
        state.last_status = 0

    def _source_site_skipped_by_known_status(self, node: SourceSite, state: EvaluationState):
        if node.separator == "&&" and state.last_status not in {None, 0}:
            self._disable_unreachable_sources([node], "&& previous command status")
            return True
        if node.separator == "||" and state.last_status == 0:
            self._disable_unreachable_sources([node], "|| previous command status")
            return True
        return False

    def _apply_raw_command(self, node: RawCommand, state: EvaluationState, stack: tuple[Path, ...]):
        if self._apply_function_call(node, state, stack):
            return

        if state.function_call_stack and self._raw_function_return_command(node):
            raise FunctionReturnSignal(self._function_return_status(node, state), node)

        if state.function_call_stack and self._raw_function_shift_command(node):
            self._apply_function_shift(node, state)
            return

        exact_status = self._raw_exact_status_command(node)
        if exact_status is not None:
            state.last_status = exact_status
            return

        if self._apply_shopt(node, state):
            state.last_status = 0
            return

        try:
            if contains_source_command(node.text):
                self._ensure_source_state_can_resolve(node, node.text, state)
            resolved_sources = SOURCE_RESOLVER.resolve_command_level_sources(
                node.text,
                state.resolver_context(),
                self.mode,
            )
        except UnsupportedSourceError as exc:
            if self.mode == "context":
                return
            raise with_source_diagnostic(
                exc,
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.command-resolution",
            ) from exc

        if not resolved_sources and self._raw_command_may_source(node.text) and self.mode == "executable":
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.command-unresolved",
                "unsupported unresolved source command",
                "Use a direct source command or a supported dynamic source expression.",
            )

        for resolved_source in resolved_sources:
            execution_model = ExecutionModel(resolved_source.execution_model)
            source_path = Path(resolved_source.path)
            self._record_event(
                source_path,
                node,
                resolved_source.source_expression,
                resolved_source.source_site,
                execution_model,
                resolved_source.replacement_kind,
                state,
                source_value=resolved_source.source_value,
            )
            if execution_model == ExecutionModel.CHILD_SHELL:
                self._evaluate_file(source_path, state.child_shell_copy(), stack)
            else:
                self._evaluate_file(source_path, state, stack)
        state.last_status = 0 if resolved_sources else None

    def _apply_function_call(self, node: RawCommand, state: EvaluationState, stack: tuple[Path, ...]):
        try:
            words = parse_shell_words_preserving_quotes(node.text.strip())
        except UnsupportedSourceError:
            return False
        if not words:
            return False

        index = 0
        while index < len(words) and ASSIGNMENT_WORD_PATTERN.match(words[index]):
            index += 1
        if index >= len(words):
            return False

        function_name, exact_dispatch = self._resolve_function_name(words[index], node, state)
        if not exact_dispatch:
            if self._state_has_source_relevant_functions(state):
                raise unsupported_source_error(
                    str(node.location.path),
                    node.location.line - 1,
                    node.text,
                    node.text,
                    "unsupported.source.function-dispatch",
                    "unsupported dynamic function dispatch",
                    "Function dispatch must resolve exactly when source-relevant functions are in scope.",
                )
            return False

        if function_name in state.ambiguous_functions:
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.function-dispatch",
                f"unsupported branch-dependent function call: {function_name}",
                "Define source-relevant functions consistently before calling them.",
            )
        function_def = state.functions.get(function_name)
        if function_def is None:
            return False

        if function_name in state.function_call_stack:
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.function-recursion",
                f"unsupported recursive function call: {function_name}",
                "Recursive source effects need an explicit bounded recursion model.",
            )

        variants = state.function_variants.get(function_name, (function_def,))
        arguments = self._resolve_function_arguments(words[index + 1:], node, state)
        prefix_words = words[:index]
        if len(variants) == 1:
            self._apply_function_call_variant(
                variants[0],
                function_name,
                arguments,
                prefix_words,
                node,
                state,
                stack,
            )
            return True

        base_state = state.child_shell_copy()
        outcomes = []
        for variant in variants:
            variant_state = base_state.child_shell_copy()
            variant_state.occurrence_context = OccurrenceModel.MUTUALLY_EXCLUSIVE
            self._apply_function_call_variant(
                variant,
                function_name,
                arguments,
                prefix_words,
                node,
                variant_state,
                stack,
            )
            outcomes.append(EvaluationOutcome(variant_state))

        self._merge_possible_states(state, [outcome.state for outcome in outcomes])
        return True

    def _apply_function_call_variant(
        self,
        function_def: FunctionDef,
        function_name: str,
        arguments: tuple[str, ...],
        prefix_words: list[str],
        call_node: RawCommand,
        state: EvaluationState,
        stack: tuple[Path, ...],
    ):
        prefix_scope = {}
        self._apply_function_assignment_prefixes(prefix_words, prefix_scope, call_node, state)
        previous_positionals = self._push_function_positionals(arguments, state)
        previous_call_stack = state.function_call_stack
        state.function_call_stack = (*state.function_call_stack, function_name)
        state.local_scopes.append({})
        return_status = None
        try:
            try:
                self._evaluate_nodes(function_def.body, state, stack)
            except FunctionReturnSignal as signal:
                return_status = signal.status
        finally:
            local_scope = state.local_scopes.pop()
            self._restore_local_scope(local_scope, state)
            self._restore_function_positionals(previous_positionals, len(arguments), state)
            self._restore_local_scope(prefix_scope, state)
            state.function_call_stack = previous_call_stack
        if return_status is not None:
            state.last_status = return_status

    def _resolve_function_name(self, word: str, node: RawCommand, state: EvaluationState):
        if "$" not in word:
            return strip_matching_quotes(word), True

        try:
            return self._resolve_function_exact_word(
                word,
                node,
                state,
                "unsupported.source.function-dispatch",
                "unsupported dynamic function dispatch",
                "unsupported unresolved function dispatch",
                "Function dispatch must resolve to a known local function before source-aware evaluation.",
            ), True
        except UnsupportedSourceError:
            return strip_matching_quotes(word), False

    def _state_has_source_relevant_functions(self, state: EvaluationState):
        return any(
            self._node_list_may_source(function_def.body)
            for function_def in state.functions.values()
        ) or any(
            self._node_list_may_source(function_def.body)
            for variants in state.function_variants.values()
            for function_def in variants
        )

    def _apply_function_assignment_prefixes(self, words: list[str], scope: dict, node: RawCommand,
                                            state: EvaluationState):
        for word in words:
            match = re.match(r'^([a-zA-Z_]\w*)(\+?)=(.*)$', word, re.S)
            if not match:
                raise unsupported_source_error(
                    str(node.location.path),
                    node.location.line - 1,
                    node.text,
                    node.text,
                    "unsupported.source.function-assignment",
                    "unsupported function assignment prefix",
                    "Function assignment prefixes must be exact scalar assignments.",
                )
            name, append_operator, value = match.groups()
            self._capture_variable_in_scope(name, scope, state)
            resolved = self._resolve_function_exact_word(
                value,
                node,
                state,
                "unsupported.source.function-assignment",
                "unsupported dynamic function assignment prefix",
                "unsupported unresolved function assignment prefix",
                "Function assignment prefixes must be exact for source-aware function evaluation.",
            )
            if append_operator:
                resolved = state.runtime_variables.get(name, "") + resolved
            state.variables[name] = resolved
            state.runtime_variables[name] = resolved
            state.ambiguous_variables.discard(name)

    @staticmethod
    def _resolve_function_arguments(words: list[str], node: RawCommand, state: EvaluationState):
        arguments = []
        for word in words:
            arguments.append(SourceEvaluator._resolve_function_exact_word(
                word,
                node,
                state,
                "unsupported.source.function-argument",
                "unsupported dynamic function argument",
                "unsupported unresolved function argument",
                "Function arguments must be exact for source-aware function evaluation.",
            ))
        return tuple(arguments)

    @staticmethod
    def _resolve_function_exact_word(word: str, node: RawCommand, state: EvaluationState, code: str,
                                     dynamic_message: str, unresolved_message: str, hint: str):
        if '$(' in word or '`' in word:
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                code,
                dynamic_message,
                hint,
            )
        resolved = resolve_variable_references(word, state.runtime_context())
        resolved = os.path.expandvars(resolved)
        if "$" in resolved:
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                code,
                unresolved_message,
                hint,
            )
        return strip_matching_quotes(resolved)

    @staticmethod
    def _push_function_positionals(arguments: tuple[str, ...], state: EvaluationState):
        positional_names = {str(index) for index in range(1, len(arguments) + 1)}
        positional_names.update(
            name
            for mapping in (state.variables, state.runtime_variables)
            for name in mapping
            if name.isdigit()
        )
        previous = {
            name: (
                name in state.variables,
                state.variables.get(name),
                name in state.runtime_variables,
                state.runtime_variables.get(name),
                name in state.ambiguous_variables,
            )
            for name in positional_names
        }
        for index, argument in enumerate(arguments, start=1):
            name = str(index)
            state.variables[name] = argument
            state.runtime_variables[name] = argument
            state.ambiguous_variables.discard(name)
        for name in positional_names - {str(index) for index in range(1, len(arguments) + 1)}:
            state.variables.pop(name, None)
            state.runtime_variables.pop(name, None)
            state.ambiguous_variables.discard(name)
        return previous

    @staticmethod
    def _restore_function_positionals(previous_positionals, argument_count: int, state: EvaluationState):
        for index in range(1, argument_count + 1):
            state.ambiguous_variables.discard(str(index))
        for name, (
            had_value,
            previous_value,
            had_runtime_value,
            previous_runtime_value,
            was_ambiguous,
        ) in previous_positionals.items():
            if had_value and previous_value is not None:
                state.variables[name] = previous_value
            else:
                state.variables.pop(name, None)
            if had_runtime_value and previous_runtime_value is not None:
                state.runtime_variables[name] = previous_runtime_value
            else:
                state.runtime_variables.pop(name, None)
            if was_ambiguous:
                state.ambiguous_variables.add(name)
            else:
                state.ambiguous_variables.discard(name)

    @staticmethod
    def _raw_function_return_command(node: RawCommand):
        stripped = node.text.strip()
        return bool(re.match(r'^return(?:\s|$)', stripped))

    @staticmethod
    def _raw_function_shift_command(node: RawCommand):
        stripped = node.text.strip()
        return bool(re.match(r'^shift(?:\s|$)', stripped))

    @staticmethod
    def _raw_exact_status_command(node: RawCommand):
        stripped = node.text.strip()
        if contains_source_command(stripped) or contains_nested_source_command(stripped):
            return None

        try:
            words = parse_shell_words_preserving_quotes(stripped)
        except UnsupportedSourceError:
            return None
        if not words:
            return 0

        index = 0
        while index < len(words) and ASSIGNMENT_WORD_PATTERN.match(words[index]):
            index += 1
        if index >= len(words):
            return 0

        command_name = strip_matching_quotes(words[index])
        if command_name in {":", "true"}:
            return 0
        if command_name == "false":
            return 1
        return None

    def _function_return_status(self, node: RawCommand, state: EvaluationState):
        try:
            words = parse_shell_words_preserving_quotes(node.text.strip())
        except UnsupportedSourceError as exc:
            raise self._unsupported_function_control(node, "unsupported function return syntax") from exc

        if len(words) > 2 or not words or words[0] != "return":
            raise self._unsupported_function_control(node, "unsupported function return syntax")
        if len(words) == 1:
            return 0

        status_text = self._resolve_function_control_word(words[1], node, state, "return")
        if not re.fullmatch(r'[+-]?\d+', status_text):
            raise self._unsupported_function_control(node, "unsupported non-integer function return status")
        return int(status_text) % 256

    def _apply_function_shift(self, node: RawCommand, state: EvaluationState):
        try:
            words = parse_shell_words_preserving_quotes(node.text.strip())
        except UnsupportedSourceError as exc:
            raise self._unsupported_function_control(node, "unsupported function shift syntax") from exc

        if len(words) > 2 or not words or words[0] != "shift":
            raise self._unsupported_function_control(node, "unsupported function shift syntax")

        if len(words) == 1:
            count = 1
        else:
            count_text = self._resolve_function_control_word(words[1], node, state, "shift")
            if not re.fullmatch(r'\d+', count_text):
                raise self._unsupported_function_control(node, "unsupported non-integer function shift count")
            count = int(count_text)

        positional_indexes = sorted(
            int(name)
            for name in set(state.variables) | set(state.runtime_variables)
            if name.isdigit() and int(name) > 0
        )
        argument_count = positional_indexes[-1] if positional_indexes else 0
        if count == 0:
            state.last_status = 0
            return
        if count > argument_count:
            state.last_status = 1
            return

        for index in range(1, argument_count + 1):
            target = str(index)
            source = str(index + count)
            if index + count <= argument_count:
                if source in state.variables:
                    state.variables[target] = state.variables[source]
                else:
                    state.variables.pop(target, None)
                if source in state.runtime_variables:
                    state.runtime_variables[target] = state.runtime_variables[source]
                else:
                    state.runtime_variables.pop(target, None)
            else:
                state.variables.pop(target, None)
                state.runtime_variables.pop(target, None)
            state.ambiguous_variables.discard(target)
        state.last_status = 0

    def _resolve_function_control_word(self, word: str, node: RawCommand, state: EvaluationState, command: str):
        return self._resolve_function_exact_word(
            word,
            node,
            state,
            "unsupported.source.function-control",
            f"unsupported dynamic function {command}",
            f"unsupported unresolved function {command}",
            "Function control arguments must be exact for source-aware function evaluation.",
        )

    @staticmethod
    def _unsupported_function_control(node: RawCommand, message: str):
        return unsupported_source_error(
            str(node.location.path),
            node.location.line - 1,
            node.text,
            node.text,
            "unsupported.source.function-control",
            message,
            "Function return/shift semantics must be exact for source-aware lowering.",
        )

    @staticmethod
    def _apply_shopt(node: RawCommand, state: EvaluationState):
        stripped_text = node.text.strip()
        if not stripped_text.startswith("shopt "):
            return False

        try:
            words = parse_shell_words_preserving_quotes(stripped_text)
        except UnsupportedSourceError:
            return False

        if len(words) < 3 or words[0] != "shopt":
            return False

        action = words[1]
        if action not in {"-s", "-u"}:
            return False

        for option in words[2:]:
            if option not in GLOB_SHOPT_OPTIONS:
                continue
            if action == "-s":
                state.glob_options.add(option)
            else:
                state.glob_options.discard(option)
        return True

    def _record_and_descend(self, source_path: Path, node: SourceSite, source_expression: str, source_site: str,
                            state: EvaluationState, stack: tuple[Path, ...], execution_model: ExecutionModel,
                            replacement_kind: str, source_value: str | None = None):
        self._record_event(
            source_path, node, source_expression, source_site, execution_model, replacement_kind, state,
            source_value=source_value,
        )
        self._evaluate_file(source_path, state, stack)

    def _record_event(self, source_path: Path, node, source_expression: str, source_site: str,
                      execution_model: ExecutionModel, replacement_kind: str, state: EvaluationState,
                      occurrence_model: OccurrenceModel | None = None, source_value: str | None = None):
        self.events.append(SourceEvent(
            path=source_path.resolve(),
            location=node.location,
            source_expression=source_expression.strip(),
            source_site=source_site.strip(),
            execution_model=execution_model,
            occurrence_model=occurrence_model or state.occurrence_context,
            replacement_kind=replacement_kind,
            source_value=source_value,
            state_before=state.snapshot(),
            condition=state.condition_context,
        ))

    def _disable_unreachable_sources(self, nodes, condition: str):
        for node in nodes:
            if isinstance(node, SourceSite):
                self.disabled_sources.append(DisabledSourceSite(
                    location=node.location,
                    source_expression=node.source_expression.strip(),
                    source_site=f"{node.command_name} {node.source_expression.strip()}".strip(),
                    replacement_kind="source",
                    condition=condition,
                ))
            elif isinstance(node, RawCommand):
                if self._raw_command_may_source(node.text):
                    self.disabled_sources.append(DisabledSourceSite(
                        location=node.location,
                        source_expression=node.text.strip(),
                        source_site=node.text.strip(),
                        replacement_kind="command",
                        condition=condition,
                    ))
            elif isinstance(node, FunctionDef):
                self._disable_unreachable_sources(node.body, condition)
            elif isinstance(node, ForLoop):
                self._disable_unreachable_sources(node.body, condition)
            elif isinstance(node, IfBlock):
                for branch in node.branches:
                    self._disable_unreachable_sources(branch.body, branch.condition or "else")
            elif isinstance(node, CaseBlock):
                for arm in node.arms:
                    self._disable_unreachable_sources(arm.body, self._case_arm_condition(node, arm))

    def _nodes_may_source(self, arms):
        for arm in arms:
            if self._node_list_may_source(arm.body):
                return True
        return False

    def _node_list_may_source(self, nodes):
        for node in nodes:
            if isinstance(node, SourceSite):
                return True
            if isinstance(node, RawCommand) and self._raw_command_may_source(node.text):
                return True
            if isinstance(node, FunctionDef) and self._node_list_may_source(node.body):
                return True
            if isinstance(node, ForLoop) and self._node_list_may_source(node.body):
                return True
            if isinstance(node, IfBlock):
                if any(self._node_list_may_source(branch.body) for branch in node.branches):
                    return True
            if isinstance(node, CaseBlock) and self._nodes_may_source(node.arms):
                return True
        return False

    @staticmethod
    def _raw_command_may_source(command: str):
        return bool(
            contains_source_command(command)
            or contains_nested_source_command(command)
            or SourceEvaluator._raw_command_payload_may_source(command)
            or SourceEvaluator._raw_command_may_expand_to_source(command)
        )

    @staticmethod
    def _raw_command_payload_may_source(command: str):
        try:
            words = parse_shell_words_preserving_quotes(command.strip())
        except UnsupportedSourceError:
            return bool(
                re.search(r'^\s*(?:[a-zA-Z_]\w*(?:\+)?=\S+\s+)*(?:eval|bash|/bin/bash|/usr/bin/bash)\b', command)
                and re.search(r'\bsource\b|(?:^|[\s;&|])\.', command)
            )

        index = 0
        while index < len(words) and ASSIGNMENT_WORD_PATTERN.match(words[index]):
            index += 1
        if index >= len(words):
            return False

        command_name = words[index]
        if command_name == "eval":
            payload = strip_matching_quotes(" ".join(words[index + 1:]))
            return contains_source_command(payload) or contains_nested_source_command(payload)

        if command_name in {"bash", "/bin/bash", "/usr/bin/bash"} and len(words) > index + 2 and words[index + 1] == "-c":
            payload = strip_matching_quotes(words[index + 2])
            return contains_source_command(payload) or contains_nested_source_command(payload)

        return False

    @staticmethod
    def _raw_command_may_expand_to_source(command: str):
        try:
            words = parse_shell_words_preserving_quotes(command.strip())
        except UnsupportedSourceError:
            return bool(
                '$' in command
                and re.search(r'^\s*(?:[a-zA-Z_]\w*(?:\+)?=\S+\s+)*(?:eval|bash|/bin/bash|/usr/bin/bash)\b', command)
            )

        index = 0
        while index < len(words) and ASSIGNMENT_WORD_PATTERN.match(words[index]):
            index += 1
        if index >= len(words):
            return False

        command_name = words[index]
        if command_name == "eval":
            return any("$" in word for word in words[index + 1:])

        if command_name in {"bash", "/bin/bash", "/usr/bin/bash"}:
            return (
                len(words) > index + 2
                and words[index + 1] == "-c"
                and "$" in words[index + 2]
            )

        return False

    @staticmethod
    def _ensure_source_state_can_resolve(node, source_expression: str, state: EvaluationState):
        if state.ambiguous_cwd:
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.branch-state",
                "unsupported source after branch-dependent cwd",
                "Reset cwd with an exact cd before the next source, or keep branch cwd effects convergent.",
            )

        variable_names = {match.group(1) or match.group(2) for match in SCALAR_REFERENCE_PATTERN.finditer(source_expression)}
        ambiguous_variables = sorted(variable_names & state.ambiguous_variables)
        if ambiguous_variables:
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.branch-state",
                f"unsupported source after branch-dependent variable: {', '.join(ambiguous_variables)}",
                "Assign the same source-relevant value on every branch before sourcing it.",
            )

        array_names = {match.group(1) for match in ARRAY_INDEX_PATTERN.finditer(source_expression)}
        ambiguous_arrays = sorted(array_names & state.ambiguous_arrays)
        if ambiguous_arrays:
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.branch-state",
                f"unsupported source after branch-dependent array: {', '.join(ambiguous_arrays)}",
                "Assign the same source-relevant array values on every branch before sourcing them.",
            )

    @staticmethod
    def _ensure_cd_state_can_resolve(node: CdCommand, state: EvaluationState):
        candidate = resolve_variable_references(node.path_expression, state.runtime_context())
        if "$" in candidate:
            candidate = ""
        candidate = os.path.expandvars(strip_matching_quotes(candidate))
        candidate = resolve_shell_path_commands(candidate, None)
        if candidate and os.path.isabs(candidate):
            return

        raise unsupported_source_error(
            str(node.location.path),
            node.location.line - 1,
            node.text,
            node.text,
            "unsupported.source.branch-state",
            "unsupported relative cd after branch-dependent cwd",
            "Use an absolute cd target before the next source, or keep branch cwd effects convergent.",
        )

    @staticmethod
    def _expand_array_indexes(source_expression: str, node: SourceSite, state: EvaluationState):
        def replace(match):
            name, index_text = match.groups()
            values = state.arrays.get(name)
            index = int(index_text)
            if values is None or index >= len(values):
                raise unsupported_source_error(
                    str(node.location.path),
                    node.location.line - 1,
                    node.text,
                    node.text,
                    "unsupported.source.array-index",
                    "unsupported array source expression",
                    "Only exact array indexes can be resolved by the IR evaluator.",
                )
            return values[index]

        return ARRAY_INDEX_PATTERN.sub(replace, source_expression)

    @staticmethod
    def _source_runtime_value(source_expression: str, state: EvaluationState):
        context = state.runtime_context()
        resolved_expression = resolve_variable_references(source_expression, context)
        return strip_matching_quotes(resolved_expression)

    @staticmethod
    def _is_plain_source_site(node: SourceSite):
        stripped_text = node.text.strip()
        for separator in ("&&", "||", ";"):
            if stripped_text.startswith(separator):
                stripped_text = stripped_text[len(separator):].strip()
                break
        return (
            stripped_text.startswith("source ")
            or stripped_text.startswith(". ")
            or stripped_text == "."
        )

    @staticmethod
    def _with_occurrence_models(events: list[SourceEvent]):
        path_counts = Counter(event.path for event in events)
        return tuple(
            SourceEvent(
                path=event.path,
                location=event.location,
                source_expression=event.source_expression,
                source_site=event.source_site,
                execution_model=event.execution_model,
                occurrence_model=(
                    OccurrenceModel.REPEATED
                    if path_counts[event.path] > 1 and event.occurrence_model == OccurrenceModel.ONCE
                    else event.occurrence_model
                ),
                replacement_kind=event.replacement_kind,
                source_value=event.source_value,
                state_before=event.state_before,
                condition=event.condition,
            )
            for event in events
        )
