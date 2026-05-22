from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DiagnosticSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ExecutionModel(str, Enum):
    PARENT_SOURCE = "parent-source"
    CHILD_SHELL = "child-shell"
    CONTEXT_ONLY = "context-only"
    UNSUPPORTED = "unsupported"


class OccurrenceModel(str, Enum):
    ONCE = "once"
    REPEATED = "repeated"
    CONDITIONAL = "conditional"
    MUTUALLY_EXCLUSIVE = "mutually-exclusive"


@dataclass(frozen=True)
class SourceLocation:
    path: Path
    line: int
    column: int = 1


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: DiagnosticSeverity
    location: SourceLocation
    fragment: str
    message: str
    hint: str | None = None


@dataclass(frozen=True)
class StateSnapshot:
    cwd: Path
    variables: dict[str, str] = field(default_factory=dict)
    arrays: dict[str, tuple[str, ...]] = field(default_factory=dict)
    shell_options: frozenset[str] = field(default_factory=frozenset)
    bash_source_stack: tuple[Path, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SourceEvent:
    path: Path
    location: SourceLocation
    source_expression: str
    source_site: str
    execution_model: ExecutionModel
    occurrence_model: OccurrenceModel
    state_before: StateSnapshot | None = None
    condition: str | None = None


@dataclass(frozen=True)
class EvaluationResult:
    events: tuple[SourceEvent, ...]
    diagnostics: tuple[Diagnostic, ...] = ()
    final_state: StateSnapshot | None = None


@dataclass(frozen=True)
class IRNode:
    location: SourceLocation
    text: str


@dataclass(frozen=True)
class RawCommand(IRNode):
    pass


@dataclass(frozen=True)
class Assignment(IRNode):
    name: str
    value: str
    prefix: str = ""


@dataclass(frozen=True)
class ArrayAssignment(IRNode):
    name: str
    values: tuple[str, ...]
    is_exact: bool = True


@dataclass(frozen=True)
class CdCommand(IRNode):
    path_expression: str


@dataclass(frozen=True)
class SetCommand(IRNode):
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class SourceSite(IRNode):
    command_name: str
    source_expression: str
    separator: str = ""
    is_control_flow: bool = False


@dataclass(frozen=True)
class ScriptIR:
    path: Path
    nodes: tuple[IRNode, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def source_sites(self) -> tuple[SourceSite, ...]:
        return tuple(node for node in self.nodes if isinstance(node, SourceSite))
