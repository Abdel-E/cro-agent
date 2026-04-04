from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FunnelSurface(str, Enum):
    LANDING = "landing"
    PRODUCT_PAGE = "product_page"
    CART = "cart"

    @classmethod
    def ordered(cls) -> List["FunnelSurface"]:
        return [cls.LANDING, cls.PRODUCT_PAGE, cls.CART]


class JourneyEventType(str, Enum):
    ADVANCE = "advance"
    DROP_OFF = "drop_off"
    CONVERT = "convert"


@dataclass
class JourneyDecisionRecord:
    decision_id: str
    session_id: str
    stage: FunnelSurface
    segment: str
    variant_id: str
    probability: float
    context: Dict[str, Any] = field(default_factory=dict)
    reward: int | None = None
    created_at: str = field(default_factory=utcnow_iso)


@dataclass
class JourneyEventRecord:
    event_id: str
    session_id: str
    event_type: JourneyEventType
    from_stage: FunnelSurface
    to_stage: FunnelSurface | None
    reward: int
    created_at: str = field(default_factory=utcnow_iso)


@dataclass
class JourneySession:
    session_id: str
    created_at: str = field(default_factory=utcnow_iso)
    context: Dict[str, Any] = field(default_factory=dict)
    decisions_by_stage: Dict[FunnelSurface, str] = field(default_factory=dict)
    stage_path: List[FunnelSurface] = field(default_factory=list)
    event_ids: List[str] = field(default_factory=list)
    closed: bool = False

    def register_decision(self, stage: FunnelSurface, decision_id: str) -> None:
        self.decisions_by_stage[stage] = decision_id
        if not self.stage_path or self.stage_path[-1] != stage:
            self.stage_path.append(stage)

    def register_event(self, event_id: str, to_stage: FunnelSurface | None) -> None:
        self.event_ids.append(event_id)
        if to_stage is not None and (not self.stage_path or self.stage_path[-1] != to_stage):
            self.stage_path.append(to_stage)
