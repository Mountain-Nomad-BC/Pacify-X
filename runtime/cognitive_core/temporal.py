"""Interval and event-order reasoning for stateful engineering systems."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .common import stable_hash


def _parse_timestamp(raw: object, field: str) -> datetime:
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include an explicit timezone")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class Interval:
    interval_id: str
    start: datetime
    end: datetime

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Interval":
        identifier = str(value.get("id", "")).strip()
        if not identifier:
            raise ValueError("interval id is required")
        start = _parse_timestamp(value["start"], f"interval {identifier} start")
        end = _parse_timestamp(value["end"], f"interval {identifier} end")
        if end < start:
            raise ValueError("interval end precedes start")
        return cls(identifier, start, end)


def relation(left: Interval, right: Interval) -> str:
    if left.start == right.start and left.end == right.end:
        return "equals"
    if left.end < right.start:
        return "before"
    if left.end == right.start:
        return "meets"
    if left.start > right.end:
        return "after"
    if left.start == right.end:
        return "met_by"
    if left.start < right.start < left.end < right.end:
        return "overlaps"
    if right.start < left.start < right.end < left.end:
        return "overlapped_by"
    if right.start < left.start and left.end < right.end:
        return "during"
    if left.start < right.start and right.end < left.end:
        return "contains"
    if left.start == right.start and left.end < right.end:
        return "starts"
    if left.start == right.start and left.end > right.end:
        return "started_by"
    if left.start > right.start and left.end == right.end:
        return "finishes"
    if left.start < right.start and left.end == right.end:
        return "finished_by"
    raise ValueError("unclassified interval relation")


def analyze(payload: Mapping[str, Any]) -> dict[str, Any]:
    intervals = [Interval.from_mapping(item) for item in payload.get("intervals", ())]
    if len({item.interval_id for item in intervals}) != len(intervals):
        raise ValueError("interval IDs must be unique")
    relationships = []
    for index, left in enumerate(intervals):
        for right in intervals[index + 1 :]:
            relationships.append(
                {
                    "left": left.interval_id,
                    "right": right.interval_id,
                    "relation": relation(left, right),
                }
            )

    events_raw: Sequence[Mapping[str, Any]] = payload.get("events", ())
    parsed_events: list[tuple[datetime, str, Mapping[str, Any]]] = []
    seen_ids: set[str] = set()
    for event in events_raw:
        if not isinstance(event, Mapping):
            raise ValueError("each event must be an object")
        identifier = str(event.get("id", "")).strip()
        if not identifier or identifier in seen_ids:
            raise ValueError("event IDs must be unique and non-empty")
        seen_ids.add(identifier)
        parsed_events.append(
            (
                _parse_timestamp(
                    event.get("timestamp"), f"event {identifier} timestamp"
                ),
                identifier,
                event,
            )
        )
    parsed_events.sort(key=lambda item: (item[0], item[1]))

    transition_errors = []
    allowed = payload.get("allowed_transitions", {})
    current = payload.get("initial_state")
    timeline = []
    simultaneous: dict[str, list[str]] = defaultdict(list)
    for timestamp, identifier, event in parsed_events:
        simultaneous[timestamp.isoformat()].append(identifier)
        target = event.get("state")
        if current is not None and target is not None and allowed:
            permitted = set(map(str, allowed.get(str(current), ())))
            if str(target) not in permitted:
                transition_errors.append(
                    {
                        "event_id": identifier,
                        "timestamp": timestamp.isoformat(),
                        "from": current,
                        "to": target,
                    }
                )
        timeline.append(
            {
                "id": identifier,
                "timestamp": timestamp.isoformat(),
                "from_state": current,
                "to_state": target,
            }
        )
        if target is not None:
            current = target
    simultaneous_groups = [ids for ids in simultaneous.values() if len(ids) > 1]
    result = {
        "valid": not transition_errors,
        "interval_relations": relationships,
        "ordered_event_ids": [identifier for _, identifier, _ in parsed_events],
        "timeline": timeline,
        "simultaneous_event_groups": simultaneous_groups,
        "transition_errors": transition_errors,
        "final_state": current,
        "warning": "Equal timestamps establish simultaneity, not causal order; ID ordering is deterministic only.",
    }
    return {**result, "result_sha256": stable_hash(result)}
