from pathlib import Path

from methods.source_effects import Diagnostic, DiagnosticSeverity, SourceLocation
from methods.source_resolver import UnsupportedSourceError


def command_column(line: str, fragment: str):
    stripped_fragment = fragment.strip()
    if not stripped_fragment:
        return 1

    column = line.find(stripped_fragment)
    if column < 0:
        column = line.find(fragment)
    return 1 if column < 0 else column + 1


def source_diagnostic(script_path: str, line_number: int, line: str, fragment: str, code: str,
                      message: str, hint: str | None = None, details: dict | None = None):
    return Diagnostic(
        code=code,
        severity=DiagnosticSeverity.ERROR,
        location=SourceLocation(Path(script_path), line_number + 1, command_column(line, fragment)),
        fragment=fragment.strip(),
        message=message,
        hint=hint,
        details=details or {},
    )


def unsupported_source_error(script_path: str, line_number: int, line: str, fragment: str, code: str,
                             message: str, hint: str | None = None, details: dict | None = None):
    diagnostic = source_diagnostic(script_path, line_number, line, fragment, code, message, hint, details)
    return UnsupportedSourceError(f"{message}: {diagnostic.fragment}", diagnostic=diagnostic)


def with_source_diagnostic(error: UnsupportedSourceError, script_path: str, line_number: int, line: str,
                           fragment: str, fallback_code: str):
    if error.diagnostic is not None:
        return error

    diagnostic = source_diagnostic(
        script_path,
        line_number,
        line,
        fragment,
        error.code or fallback_code,
        str(error),
        error.hint,
        error.details,
    )
    return error.with_diagnostic(diagnostic)
