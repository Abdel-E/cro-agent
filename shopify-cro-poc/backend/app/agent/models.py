from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal

from app.funnel import utcnow_iso

ObservationKind = Literal[
    "stage_drop_off",
    "stage_decline_trend",
    "segment_underperforming",
]
ObservationSeverity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Observation:
    kind: ObservationKind
    severity: ObservationSeverity
    stage: str
    message: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    segment: str | None = None
    observed_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "stage": self.stage,
            "segment": self.segment,
            "message": self.message,
            "evidence": dict(self.evidence),
            "observed_at": self.observed_at,
        }
