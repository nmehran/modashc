from __future__ import annotations

import copy
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from methods.source_diagnostics import unsupported_source_error, with_source_diagnostic
from methods.source_effects import (
    ArrayAssignment,
    Assignment,
    CdCommand,
    EvaluationResult,
    ExecutionModel,
    OccurrenceModel,
    RawCommand,
    SetCommand,
    SourceEvent,
    SourceSite,
    StateSnapshot,
)
from methods.source_frontend import LineParserFrontend, ParserFrontend
from methods.source_resolver import UnsupportedSourceError
from methods.sources import SOURCE_RESOLVER, change_directory, resolve_command, resolve_variable_references
from methods.regex.utilities import strip_matching_quotes

ARRAY_INDEX_PATTERN = re.compile(r'\$\{([a-zA-Z_]\w*)\[(\d+)\]\}')
SHELL_OPTION_FLAGS = {
    'e': 'errexit',
    'E': 'errtrace',
    'u': 'nounset',
}


@dataclass
class EvaluationState:
    cwd: Path
    variables: dict[str, str] = field(default_factory=dict)
    arrays: dict[str, tuple[str, ...]] = field(default_factory=dict)
    shell_options: set[str] = field(default_factory=set)
    bash_source_stack: tuple[Path, ...] = ()

    def resolver_context(self):
        return {
            'vars': self.variables,
            'current_directory': str(self.cwd),
        }

    def snapshot(self):
        return StateSnapshot(
            cwd=self.cwd,
            variables=dict(self.variables),
            arrays=dict(self.arrays),
            shell_options=frozenset(self.shell_options),
            bash_source_stack=self.bash_source_stack,
        )

    def child_shell_copy(self):
        return EvaluationState(
            cwd=self.cwd,
            variables=copy.deepcopy(self.variables),
            arrays=copy.deepcopy(self.arrays),
            shell_options=set(self.shell_options),
            bash_source_stack=self.bash_source_stack,
        )


class SourceEvaluator:
    """Evaluate source effects for the supported IR subset without executing Bash."""

    def __init__(self, frontend: ParserFrontend | None = None, mode: str = "executable"):
        self.frontend = frontend or LineParserFrontend()
        self.mode = mode
        self.events: list[SourceEvent] = []

    def evaluate(self, entrypoint: str | Path):
        entrypoint = Path(entrypoint).resolve()
        state = EvaluationState(
            cwd=entrypoint.parent,
            variables={'0': str(entrypoint), 'BASH_SOURCE': str(entrypoint)},
            bash_source_stack=(entrypoint,),
        )
        self.events = []
        self._evaluate_file(entrypoint, state, ())
        return EvaluationResult(
            events=self._with_occurrence_models(self.events),
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
        previous_stack = state.bash_source_stack
        state.variables['BASH_SOURCE'] = str(path)
        state.bash_source_stack = (*previous_stack, path) if previous_stack[-1:] != (path,) else previous_stack

        try:
            for node in ir.nodes:
                if isinstance(node, Assignment):
                    self._apply_assignment(node, state)
                elif isinstance(node, ArrayAssignment):
                    self._apply_array_assignment(node, state)
                elif isinstance(node, CdCommand):
                    self._apply_cd(node, state)
                elif isinstance(node, SetCommand):
                    self._apply_set(node, state)
                elif isinstance(node, SourceSite):
                    self._apply_source_site(node, state, current_stack)
                elif isinstance(node, RawCommand):
                    self._apply_raw_command(node, state, current_stack)
        finally:
            if previous_bash_source is None:
                state.variables.pop('BASH_SOURCE', None)
            else:
                state.variables['BASH_SOURCE'] = previous_bash_source
            state.bash_source_stack = previous_stack

    @staticmethod
    def _apply_assignment(node: Assignment, state: EvaluationState):
        context = state.resolver_context()
        value = strip_matching_quotes(resolve_variable_references(node.value, context))
        resolved_value, _ = resolve_command(value, context)
        state.variables[node.name] = resolved_value

    @staticmethod
    def _apply_array_assignment(node: ArrayAssignment, state: EvaluationState):
        if node.is_exact:
            state.arrays[node.name] = node.values

    @staticmethod
    def _apply_cd(node: CdCommand, state: EvaluationState):
        context = state.resolver_context()
        state.cwd = Path(change_directory(node.path_expression, context))

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

    def _apply_source_site(self, node: SourceSite, state: EvaluationState, stack: tuple[Path, ...]):
        source_expression = self._expand_array_indexes(node.source_expression, node, state)
        source_site = f"{node.command_name} {source_expression.strip()}"
        try:
            resolved_source = SOURCE_RESOLVER.resolve_source_expression(
                source_expression,
                source_site,
                state.resolver_context(),
            )
        except UnsupportedSourceError as exc:
            raise with_source_diagnostic(
                exc,
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.ir-resolution",
            ) from exc

        if not resolved_source:
            raise unsupported_source_error(
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.ir-unresolved",
                "unsupported unresolved source",
                "Use a statically resolvable source path for IR evaluation.",
            )

        self._record_and_descend(Path(resolved_source.path), node, source_expression, source_site, state, stack,
                                ExecutionModel.PARENT_SOURCE)

    def _apply_raw_command(self, node: RawCommand, state: EvaluationState, stack: tuple[Path, ...]):
        try:
            resolved_sources = SOURCE_RESOLVER.resolve_command_level_sources(
                node.text,
                state.resolver_context(),
                self.mode,
            )
        except UnsupportedSourceError as exc:
            raise with_source_diagnostic(
                exc,
                str(node.location.path),
                node.location.line - 1,
                node.text,
                node.text,
                "unsupported.source.ir-command-resolution",
            ) from exc

        for resolved_source in resolved_sources:
            execution_model = ExecutionModel(resolved_source.execution_model)
            source_path = Path(resolved_source.path)
            self._record_event(
                source_path,
                node,
                resolved_source.source_expression,
                resolved_source.source_site,
                execution_model,
                state,
            )
            if execution_model == ExecutionModel.CHILD_SHELL:
                self._evaluate_file(source_path, state.child_shell_copy(), stack)
            else:
                self._evaluate_file(source_path, state, stack)

    def _record_and_descend(self, source_path: Path, node: SourceSite, source_expression: str, source_site: str,
                            state: EvaluationState, stack: tuple[Path, ...], execution_model: ExecutionModel):
        self._record_event(source_path, node, source_expression, source_site, execution_model, state)
        self._evaluate_file(source_path, state, stack)

    def _record_event(self, source_path: Path, node, source_expression: str, source_site: str,
                      execution_model: ExecutionModel, state: EvaluationState):
        self.events.append(SourceEvent(
            path=source_path.resolve(),
            location=node.location,
            source_expression=source_expression.strip(),
            source_site=source_site.strip(),
            execution_model=execution_model,
            occurrence_model=OccurrenceModel.ONCE,
            state_before=state.snapshot(),
        ))

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
                    OccurrenceModel.REPEATED if path_counts[event.path] > 1 else event.occurrence_model
                ),
                state_before=event.state_before,
                condition=event.condition,
            )
            for event in events
        )
