from __future__ import annotations

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
    expand_glob_word,
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
SCALAR_REFERENCE_PATTERN = re.compile(r'\$(?:\{([a-zA-Z_]\w*)\}|([a-zA-Z_]\w*))')
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


@dataclass
class EvaluationState:
    cwd: Path
    variables: dict[str, str] = field(default_factory=dict)
    runtime_variables: dict[str, str] = field(default_factory=dict)
    arrays: dict[str, tuple[str, ...]] = field(default_factory=dict)
    shell_options: set[str] = field(default_factory=set)
    glob_options: set[str] = field(default_factory=set)
    bash_source_stack: tuple[Path, ...] = ()
    occurrence_context: OccurrenceModel = OccurrenceModel.ONCE
    condition_context: str | None = None
    ambiguous_cwd: bool = False
    ambiguous_variables: set[str] = field(default_factory=set)
    ambiguous_arrays: set[str] = field(default_factory=set)
    ambiguous_shell_options: bool = False
    ambiguous_glob_options: bool = False

    def resolver_context(self):
        return {
            'vars': self.variables,
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
            shell_options=set(self.shell_options),
            glob_options=set(self.glob_options),
            bash_source_stack=self.bash_source_stack,
            occurrence_context=self.occurrence_context,
            condition_context=self.condition_context,
            ambiguous_cwd=self.ambiguous_cwd,
            ambiguous_variables=set(self.ambiguous_variables),
            ambiguous_arrays=set(self.ambiguous_arrays),
            ambiguous_shell_options=self.ambiguous_shell_options,
            ambiguous_glob_options=self.ambiguous_glob_options,
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
        self.shell_options = set(other.shell_options)
        self.glob_options = set(other.glob_options)
        self.bash_source_stack = other.bash_source_stack
        self.occurrence_context = other.occurrence_context
        self.condition_context = other.condition_context
        self.ambiguous_cwd = other.ambiguous_cwd
        self.ambiguous_variables = set(other.ambiguous_variables)
        self.ambiguous_arrays = set(other.ambiguous_arrays)
        self.ambiguous_shell_options = other.ambiguous_shell_options
        self.ambiguous_glob_options = other.ambiguous_glob_options


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
        for node in nodes:
            if isinstance(node, Assignment):
                self._apply_assignment(node, state)
            elif isinstance(node, ArrayAssignment):
                self._apply_array_assignment(node, state)
            elif isinstance(node, CdCommand):
                self._apply_cd(node, state)
            elif isinstance(node, SetCommand):
                self._apply_set(node, state)
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

    @staticmethod
    def _apply_assignment(node: Assignment, state: EvaluationState):
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

    @staticmethod
    def _apply_array_assignment(node: ArrayAssignment, state: EvaluationState):
        if node.is_exact:
            state.arrays[node.name] = node.values
            state.ambiguous_arrays.discard(node.name)

    @staticmethod
    def _apply_cd(node: CdCommand, state: EvaluationState):
        if state.ambiguous_cwd:
            SourceEvaluator._ensure_cd_state_can_resolve(node, state)
        context = state.resolver_context()
        state.cwd = Path(change_directory(node.path_expression, context))
        state.ambiguous_cwd = False

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

    def _apply_for_loop(self, node: ForLoop, state: EvaluationState, stack: tuple[Path, ...]):
        try:
            words = self._resolve_loop_words(node, state)
        except UnsupportedSourceError:
            if self.mode == "context":
                return
            raise

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
        if '$(' in word or '`' in word:
            raise self._unsupported_loop_words(node, "loop word list is runtime-dynamic")

        array_match = ARRAY_EXPANSION_PATTERN.match(word)
        if array_match:
            array_name = array_match.group(1)
            values = state.arrays.get(array_name)
            if values is None:
                raise self._unsupported_loop_words(node, f"loop word list references unknown array: {array_name}")
            return list(values)

        if has_unquoted_glob(raw_word):
            try:
                return [
                    match.word
                    for match in expand_glob_word(word, state.resolver_context(), node.text, raw_pattern=raw_word)
                ]
            except UnsupportedSourceError as exc:
                raise self._unsupported_loop_words(node, str(exc)) from exc

        if contains_unquoted_token(raw_word, '{') or contains_unquoted_token(raw_word, '}'):
            raise self._unsupported_loop_words(node, "unsupported brace loop word list")

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
            if any(char.isspace() for char in resolved_word):
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
        branch_states = []
        branch_reachability = self._if_branch_reachability(statuses)
        occurrence_model = (
            OccurrenceModel.MUTUALLY_EXCLUSIVE
            if len(node.branches) > 1
            else OccurrenceModel.CONDITIONAL
        )
        for branch, is_reachable in zip(node.branches, branch_reachability):
            if not is_reachable:
                self._disable_unreachable_sources(branch.body, branch.condition or "else")
                branch_states.append(base_state.child_shell_copy())
                continue

            branch_state = state.child_shell_copy()
            branch_state.occurrence_context = occurrence_model
            branch_state.condition_context = branch.condition or "else"
            self._evaluate_nodes(branch.body, branch_state, stack)
            branch_states.append(branch_state)

        possible_states = self._possible_if_states(statuses, base_state, branch_states)
        self._merge_possible_states(state, possible_states)
        state.occurrence_context = outer_occurrence_context
        state.condition_context = outer_condition_context

    def _apply_context_if_block(
        self,
        node: IfBlock,
        state: EvaluationState,
        stack: tuple[Path, ...],
        statuses: list[str],
    ):
        branch_states = []
        occurrence_model = (
            OccurrenceModel.MUTUALLY_EXCLUSIVE
            if len(node.branches) > 1
            else OccurrenceModel.CONDITIONAL
        )

        for branch in node.branches:
            branch_state = state.child_shell_copy()
            branch_state.occurrence_context = occurrence_model
            branch_state.condition_context = branch.condition or "else"
            self._evaluate_nodes(branch.body, branch_state, stack)
            branch_states.append(branch_state)

        possible_states = self._possible_if_states(statuses, state.child_shell_copy(), branch_states)
        self._merge_possible_states(state, possible_states)

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
    def _possible_if_states(statuses: list[str], base_state: EvaluationState, branch_states: list[EvaluationState]):
        if not statuses:
            return [base_state]

        if "unknown" not in statuses:
            for status, branch_state in zip(statuses, branch_states):
                if status in {"true", "else"}:
                    return [branch_state]
            return [base_state]

        possible_states = []
        fallthrough_possible = True
        for status, branch_state in zip(statuses, branch_states):
            if not fallthrough_possible:
                break
            if status == "false":
                continue
            if status == "true":
                possible_states.append(branch_state)
                fallthrough_possible = False
            elif status == "else":
                possible_states.append(branch_state)
                fallthrough_possible = False
            else:
                possible_states.append(branch_state)

        if fallthrough_possible:
            possible_states.append(base_state)
        return possible_states

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
        arm_states = []
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
                arm_states.append(base_state.child_shell_copy())
                continue

            arm_state = state.child_shell_copy()
            arm_state.occurrence_context = occurrence_model
            arm_state.condition_context = condition
            self._evaluate_nodes(arm.body, arm_state, stack)
            arm_states.append(arm_state)

        possible_states = [
            arm_state
            for arm_state, is_reachable in zip(arm_states, reachable_arms)
            if is_reachable
        ] or [base_state]
        self._merge_possible_states(state, possible_states)
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
        arm_states = []

        for arm in node.arms:
            arm_state = state.child_shell_copy()
            arm_state.occurrence_context = occurrence_model
            arm_state.condition_context = self._case_arm_condition(node, arm)
            self._evaluate_nodes(arm.body, arm_state, stack)
            arm_states.append(arm_state)

        if subject_value is None:
            possible_states = arm_states
            if not self._case_has_default_arm(node):
                possible_states.append(state.child_shell_copy())
        else:
            reachable_arms = self._case_arm_reachability(node, subject_value)
            possible_states = [
                arm_state
                for arm_state, is_reachable in zip(arm_states, reachable_arms)
                if is_reachable
            ] or [state.child_shell_copy()]

        self._merge_possible_states(state, possible_states)

    def _apply_source_free_unknown_case_block(self, node: CaseBlock, state: EvaluationState, stack: tuple[Path, ...]):
        arm_states = []

        for arm in node.arms:
            arm_state = state.child_shell_copy()
            arm_state.occurrence_context = OccurrenceModel.MUTUALLY_EXCLUSIVE
            arm_state.condition_context = self._case_arm_condition(node, arm)
            self._evaluate_nodes(arm.body, arm_state, stack)
            arm_states.append(arm_state)

        possible_states = arm_states
        if not self._case_has_default_arm(node):
            possible_states.append(state.child_shell_copy())
        self._merge_possible_states(state, possible_states)

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
        quoted = (
            len(stripped_pattern) >= 2
            and stripped_pattern[0] == stripped_pattern[-1]
            and stripped_pattern[0] in {"'", '"'}
        )
        pattern_value = strip_matching_quotes(stripped_pattern)
        if quoted:
            return subject_value == pattern_value
        return fnmatchcase(subject_value, pattern_value)

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

    def _evaluate_condition(self, condition: str, state: EvaluationState):
        words = self._condition_words(condition)
        if not words:
            raise UnsupportedSourceError(f"unsupported empty if condition: {condition}")

        if words[0] == "!":
            result = self._evaluate_condition(" ".join(words[1:]), state)
            if result == "true":
                return "false"
            if result == "false":
                return "true"
            return "unknown"

        if any(token in words for token in {"&&", "||", "=~"}):
            raise UnsupportedSourceError(f"unsupported compound if condition: {condition}")
        if '$(' in condition or '`' in condition:
            raise UnsupportedSourceError(f"unsupported dynamic if condition: {condition}")

        if len(words) == 2 and words[0] in {"-e", "-f", "-d"}:
            if has_unquoted_glob(words[1]):
                raise UnsupportedSourceError(f"unsupported glob if condition: {condition}")
            path = self._condition_path(words[1], state, condition)
            if path is None:
                return "unknown"
            result = path.exists()
            if words[0] == "-f":
                result = path.is_file()
            elif words[0] == "-d":
                result = path.is_dir()
            return "true" if result else "false"

        if len(words) == 2 and words[0] in {"-n", "-z"}:
            value = self._condition_value(words[1], state)
            if value is None:
                return "unknown"
            result = bool(value) if words[0] == "-n" else not bool(value)
            return "true" if result else "false"

        if len(words) == 3 and words[1] in {"=", "==", "!="}:
            left = self._condition_value(words[0], state)
            right = self._condition_value(words[2], state)
            if left is None or right is None:
                return "unknown"
            result = left == right
            if words[1] == "!=":
                result = not result
            return "true" if result else "false"

        raise UnsupportedSourceError(f"unsupported if condition: {condition}")

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
        if "$" in resolved:
            return None
        resolved = os.path.expandvars(resolved)
        return strip_matching_quotes(resolved)

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

    def _apply_raw_command(self, node: RawCommand, state: EvaluationState, stack: tuple[Path, ...]):
        self._apply_shopt(node, state)

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

        if not resolved_sources and contains_source_command(node.text) and self.mode == "executable":
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

    @staticmethod
    def _apply_shopt(node: RawCommand, state: EvaluationState):
        stripped_text = node.text.strip()
        if not stripped_text.startswith("shopt "):
            return

        try:
            words = parse_shell_words_preserving_quotes(stripped_text)
        except UnsupportedSourceError:
            return

        if len(words) < 3 or words[0] != "shopt":
            return

        action = words[1]
        if action not in {"-s", "-u"}:
            return

        for option in words[2:]:
            if option not in GLOB_SHOPT_OPTIONS:
                continue
            if action == "-s":
                state.glob_options.add(option)
            else:
                state.glob_options.discard(option)

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
            or re.search(r'\b(?:eval|bash|/bin/bash|/usr/bin/bash)\b.*(?:\bsource\b|(?:^|[\s;&|])\.)', command)
        )

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
