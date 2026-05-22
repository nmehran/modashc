from __future__ import annotations

from pathlib import Path

from methods.source_evaluator import SourceEvaluator


def evaluate_sources(entrypoint: str | Path, mode: str = "executable"):
    return SourceEvaluator(mode=mode).evaluate(entrypoint)
