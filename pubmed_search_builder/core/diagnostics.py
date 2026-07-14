"""Machine-readable diagnostics with stable codes for workflow automation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Diagnostic:
    """One validation or execution finding.

    ``message`` remains suitable for the current human-facing CLIs while
    ``code`` gives callers a stable value that does not depend on wording.
    """

    code: str
    message: str
    severity: str = "error"
    stage: str | None = None
    artifact: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.stage:
            value["stage"] = self.stage
        if self.artifact:
            value["artifact"] = self.artifact
        return value
