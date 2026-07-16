"""Cross-document human-in-the-loop routing, audit logs, and metrics."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable


@dataclass(frozen=True)
class ReviewThresholds:
    auto_accept: float = 0.80
    reject: float = 0.40

    def __post_init__(self):
        if not 0 <= self.reject < self.auto_accept <= 1:
            raise ValueError("thresholds must satisfy 0 <= reject < auto_accept <= 1")


def calibrate(extraction_confidence: float, validation: dict) -> float:
    """Combine independent extraction and deterministic validation signals."""
    extraction = max(0.0, min(1.0, float(extraction_confidence)))
    validation_signal = max(0.0, min(1.0, float(validation.get("confidence", 0))))
    return round(extraction * validation_signal, 3)


def route_record(record: dict, thresholds=None, clock: Callable[[], datetime] | None = None) -> dict:
    thresholds = thresholds or ReviewThresholds()
    validation = record["validation"]
    extraction = float(record.get("extraction_confidence", 1.0))
    score = calibrate(extraction, validation)
    issues = validation.get("issues") or []
    has_errors = any(x.get("severity") == "error" for x in issues)

    # Reject only when both extraction and validation are below the hard floor.
    # A deterministic rule violation on an otherwise legible document belongs
    # in human review, not silent rejection.
    if extraction < thresholds.reject and float(validation.get("confidence", 0)) < thresholds.reject:
        decision = "reject"
    elif has_errors or validation.get("needs_review") or score < thresholds.auto_accept:
        decision = "needs_review"
    else:
        decision = "auto_accept"

    reasons = [x.get("message", "Unspecified validation issue") for x in issues]
    if not reasons and decision != "auto_accept":
        reasons = [f"calibrated confidence {score} is below auto-accept threshold {thresholds.auto_accept}"]
    now = (clock or (lambda: datetime.now(timezone.utc)))().isoformat().replace("+00:00", "Z")
    audit = [{"timestamp": now, "rule": x.get("code", "confidence_threshold"),
              "reason": x.get("message", reasons[0] if reasons else "No issue"),
              "severity": x.get("severity", "warning")} for x in issues]
    if not audit:
        audit = [{"timestamp": now, "rule": "routing_threshold", "reason": reasons[0] if reasons else "All gates passed",
                  "severity": "info"}]
    return {**record, "calibrated_confidence": score, "decision": decision,
            "explanation": reasons or ["All deterministic validation gates passed"], "audit_log": audit}


def review_batch(records: list[dict], thresholds=None, clock=None, top_n=3) -> dict:
    routed = [route_record(record, thresholds, clock) for record in records]
    counts = Counter(x["decision"] for x in routed)
    reasons = Counter(event["rule"] for row in routed if row["decision"] != "auto_accept"
                      for event in row["audit_log"] if event["severity"] != "info")
    total = len(routed) or 1
    metrics = {
        "records": len(routed), "auto_accept_rate": round(counts["auto_accept"] / total, 3),
        "review_rate": round(counts["needs_review"] / total, 3),
        "reject_rate": round(counts["reject"] / total, 3),
        "top_failure_reasons": [{"code": code, "count": count} for code, count in reasons.most_common(top_n)],
    }
    return {"thresholds": asdict(thresholds or ReviewThresholds()), "metrics": metrics,
            "review_queue": [x for x in routed if x["decision"] != "auto_accept"], "records": routed}
