from __future__ import annotations

from collections import Counter
from pathlib import Path

from methods.source_effects import (
    EvaluationResult,
    ExecutionModel,
    OccurrenceModel,
    SourceEvent,
    SourceLocation,
)
from methods.sources import get_sources


def evaluate_sources(entrypoint: str | Path, mode: str = "executable") -> EvaluationResult:
    """Evaluate source declarations through the current traversal backend.

    This is the compatibility bridge from the existing resolver-driven compiler
    to the new source-effect event contract. It should shrink as traversal moves
    onto the IR evaluator.
    """
    entrypoint = Path(entrypoint).resolve()
    _, context = get_sources(str(entrypoint), mode=mode)
    return source_events_from_context(entrypoint, context)


def source_events_from_context(entrypoint: str | Path, context: dict) -> EvaluationResult:
    source_declarations = context.get('source_declarations', {})
    declaration_items = _walk_declarations(Path(entrypoint), source_declarations)
    path_counts = Counter(Path(declaration.path) for _, _, _, declaration in declaration_items)
    events = tuple(
        _source_event_from_declaration(filepath, line_number, line_text, declaration, path_counts)
        for filepath, line_number, line_text, declaration in declaration_items
    )
    return EvaluationResult(events=events)


def _walk_declarations(entrypoint: Path, source_declarations: dict):
    declaration_items = []
    line_cache = {}

    def lines_for(filepath: Path):
        if filepath not in line_cache:
            line_cache[filepath] = filepath.read_text().splitlines()
        return line_cache[filepath]

    def walk(filepath: Path):
        line_declarations = source_declarations.get(str(filepath), {})
        if not line_declarations:
            return

        lines = lines_for(filepath)
        for line_number in sorted(line_declarations):
            line_text = lines[line_number] if line_number < len(lines) else ""
            for declaration in line_declarations[line_number]:
                declaration_items.append((filepath, line_number + 1, line_text, declaration))
                walk(Path(declaration.path))

    walk(entrypoint)
    return declaration_items


def _source_event_from_declaration(filepath: Path, line_number: int, line_text: str, declaration, path_counts: Counter):
    column = line_text.find(declaration.source_site)
    if column < 0:
        column = line_text.find(declaration.source_expression)
    column = 1 if column < 0 else column + 1

    resolved_path = Path(declaration.path)
    occurrence_model = (
        OccurrenceModel.REPEATED
        if path_counts[resolved_path] > 1
        else OccurrenceModel.ONCE
    )

    return SourceEvent(
        path=resolved_path,
        location=SourceLocation(filepath, line_number, column),
        source_expression=declaration.source_expression,
        source_site=declaration.source_site,
        execution_model=ExecutionModel(declaration.execution_model),
        occurrence_model=occurrence_model,
    )
