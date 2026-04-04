from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def setup_function() -> None:
    client.post("/reset")


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_decide_and_feedback_happy_path() -> None:
    decide_response = client.post(
        "/decide",
        json={"surface_id": "hero_banner", "context": {"device_type": "desktop"}},
    )
    assert decide_response.status_code == 200
    payload = decide_response.json()
    assert payload["variant_id"] in {"A", "B", "C"}
    assert "segment" in payload
    assert "content" in payload
    assert payload["content"]["headline"]

    feedback_response = client.post(
        "/feedback",
        json={
            "decision_id": payload["decision_id"],
            "variant_id": payload["variant_id"],
            "reward": 1,
        },
    )
    assert feedback_response.status_code == 200
    fb = feedback_response.json()
    assert fb["accepted"] is True
    assert fb["idempotent"] is False


def test_decide_with_full_context() -> None:
    resp = client.post("/decide", json={
        "surface_id": "hero_banner",
        "device_type": "mobile",
        "traffic_source": "meta",
        "is_returning": False,
        "context": {},
    })
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["segment"] == "new_mobile_paid"
    assert payload["content"]["trust_signals"]


def test_decide_empty_context_returns_default_segment() -> None:
    resp = client.post("/decide", json={"surface_id": "hero_banner"})
    assert resp.status_code == 200
    # With no context at all, desktop + empty source → "new_desktop_direct"
    # or "default" depending on the classifier
    assert resp.json()["segment"] in {
        "default", "new_desktop_direct",
    }


def test_decide_returning_visitor() -> None:
    resp = client.post("/decide", json={
        "surface_id": "hero_banner",
        "is_returning": True,
        "context": {},
    })
    assert resp.status_code == 200
    assert resp.json()["segment"] == "returning_any"


def test_feedback_is_idempotent() -> None:
    decision = client.post(
        "/decide", json={"surface_id": "hero_banner", "context": {}},
    ).json()

    first = client.post("/feedback", json={
        "decision_id": decision["decision_id"],
        "variant_id": decision["variant_id"],
        "reward": 0,
    })
    assert first.status_code == 200

    second = client.post("/feedback", json={
        "decision_id": decision["decision_id"],
        "variant_id": decision["variant_id"],
        "reward": 0,
    })
    assert second.status_code == 200
    assert second.json()["accepted"] is False
    assert second.json()["idempotent"] is True


def test_feedback_conflict_returns_409() -> None:
    decision = client.post(
        "/decide", json={"surface_id": "hero_banner", "context": {}},
    ).json()

    client.post("/feedback", json={
        "decision_id": decision["decision_id"],
        "variant_id": decision["variant_id"],
        "reward": 1,
    })

    conflicting = client.post("/feedback", json={
        "decision_id": decision["decision_id"],
        "variant_id": decision["variant_id"],
        "reward": 0,
    })
    assert conflicting.status_code == 409


def test_metrics_includes_segments() -> None:
    decision = client.post("/decide", json={
        "surface_id": "hero_banner",
        "device_type": "mobile",
        "traffic_source": "meta",
        "context": {},
    }).json()

    client.post("/feedback", json={
        "decision_id": decision["decision_id"],
        "variant_id": decision["variant_id"],
        "reward": 0,
    })

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    payload = metrics.json()
    assert "segments" in payload
    assert payload["totals"]["impressions"] >= 1


def test_metrics_after_feedback_updates_segment() -> None:
    decision = client.post("/decide", json={
        "surface_id": "hero_banner",
        "device_type": "mobile",
        "traffic_source": "meta",
        "context": {},
    }).json()

    client.post("/feedback", json={
        "decision_id": decision["decision_id"],
        "variant_id": decision["variant_id"],
        "reward": 1,
    })

    metrics = client.get("/metrics").json()
    seg = metrics["segments"].get("new_mobile_paid")
    assert seg is not None
    assert seg["totals"]["successes"] >= 1


def test_segments_endpoint() -> None:
    resp = client.get("/segments")
    assert resp.status_code == 200
    payload = resp.json()
    ids = [s["segment_id"] for s in payload["segments"]]
    assert "default" in ids
    assert "new_mobile_paid" in ids


def test_generate_copy_endpoint() -> None:
    resp = client.post("/generate-copy", json={
        "product": "workspace desk lamp",
        "reviews": ["Great quality!", "Love the design"],
        "segment": "returning_any",
        "num_variants": 3,
    })
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["segment"] == "returning_any"
    assert payload["variants_generated"] == 3


def test_backward_compat_old_style_request() -> None:
    """Old-style requests without the new fields should still work."""
    resp = client.post("/decide", json={
        "surface_id": "hero_banner",
        "context": {"device_type": "desktop", "traffic_source": "direct"},
    })
    assert resp.status_code == 200
    assert resp.json()["variant_id"] in {"A", "B", "C"}


def test_journey_decide_creates_session() -> None:
    resp = client.post("/journey/decide", json={
        "stage": "landing",
        "context": {"device_type": "mobile", "traffic_source": "meta"},
    })
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["session_id"]
    assert payload["stage"] == "landing"
    assert payload["variant_id"] in {"A", "B", "C"}
    assert payload["segment"] == "new_mobile_paid"


def test_journey_event_advance_updates_funnel_metrics() -> None:
    decide_payload = client.post("/journey/decide", json={
        "stage": "landing",
        "context": {"device_type": "desktop", "traffic_source": "direct"},
    }).json()

    event = client.post("/journey/event", json={
        "decision_id": decide_payload["decision_id"],
        "event_type": "advance",
        "to_stage": "product_page",
    })
    assert event.status_code == 200
    assert event.json()["accepted"] is True
    assert event.json()["decision_id"] == decide_payload["decision_id"]

    metrics = client.get("/journey/metrics")
    assert metrics.status_code == 200
    landing = metrics.json()["stages"]["landing"]
    assert landing["impressions"] >= 1
    assert landing["conversions"] >= 1
    assert landing["transitions"]["product_page"] >= 1


def test_journey_cross_stage_path_and_session_close() -> None:
    landing = client.post("/journey/decide", json={
        "stage": "landing",
        "context": {"device_type": "mobile", "traffic_source": "meta"},
    }).json()

    client.post("/journey/event", json={
        "decision_id": landing["decision_id"],
        "event_type": "advance",
        "to_stage": "product_page",
    })

    product = client.post("/journey/decide", json={
        "continue_from_decision_id": landing["decision_id"],
        "stage": "product_page",
    }).json()
    assert product["session_id"] == landing["session_id"]

    drop = client.post("/journey/event", json={
        "decision_id": product["decision_id"],
        "event_type": "drop_off",
    })
    assert drop.status_code == 200

    metrics = client.get("/journey/metrics").json()
    assert metrics["sessions"]["closed"] >= 1
    assert metrics["top_paths"]
    assert "landing:" in metrics["top_paths"][0]["path"]
    assert "product_page:" in metrics["top_paths"][0]["path"]


def test_journey_event_requires_to_stage_for_advance() -> None:
    landing = client.post("/journey/decide", json={"stage": "landing"}).json()
    resp = client.post("/journey/event", json={
        "session_id": landing["session_id"],
        "from_stage": "landing",
        "event_type": "advance",
    })
    assert resp.status_code == 400


def test_journey_decide_invalid_stage_returns_400() -> None:
    resp = client.post("/journey/decide", json={"stage": "unknown_stage"})
    assert resp.status_code == 400


def test_journey_decide_unknown_session_is_auto_created() -> None:
    resp = client.post("/journey/decide", json={
        "stage": "landing",
        "session_id": "missing-session",
    })
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["session_id"] == "missing-session"


def test_journey_event_unknown_session_returns_404() -> None:
    resp = client.post("/journey/event", json={
        "session_id": "missing-session",
        "from_stage": "landing",
        "event_type": "drop_off",
    })
    assert resp.status_code == 404


def test_journey_event_is_idempotent_with_same_outcome() -> None:
    landing = client.post("/journey/decide", json={"stage": "landing"}).json()

    first = client.post("/journey/event", json={
        "decision_id": landing["decision_id"],
        "event_type": "advance",
        "to_stage": "product_page",
    })
    assert first.status_code == 200
    assert first.json()["accepted"] is True

    second = client.post("/journey/event", json={
        "decision_id": landing["decision_id"],
        "event_type": "advance",
        "to_stage": "product_page",
    })
    assert second.status_code == 200
    assert second.json()["accepted"] is False
    assert second.json()["idempotent"] is True


def test_journey_event_conflict_returns_409() -> None:
    landing = client.post("/journey/decide", json={"stage": "landing"}).json()

    client.post("/journey/event", json={
        "decision_id": landing["decision_id"],
        "event_type": "advance",
        "to_stage": "product_page",
    })

    conflict = client.post("/journey/event", json={
        "decision_id": landing["decision_id"],
        "event_type": "drop_off",
    })
    assert conflict.status_code == 409


def test_journey_event_requires_identifiers() -> None:
    resp = client.post("/journey/event", json={"event_type": "drop_off"})
    assert resp.status_code == 400


def test_journey_continue_from_unknown_decision_returns_404() -> None:
    resp = client.post("/journey/decide", json={
        "stage": "product_page",
        "continue_from_decision_id": "missing-decision",
    })
    assert resp.status_code == 404


def test_journey_observations_detect_stage_drop_off() -> None:
    for _ in range(6):
        decide = client.post("/journey/decide", json={
            "stage": "landing",
            "context": {"device_type": "mobile", "traffic_source": "meta"},
        }).json()
        client.post("/journey/event", json={
            "decision_id": decide["decision_id"],
            "event_type": "drop_off",
        })

    obs = client.get(
        "/journey/observations",
        params={
            "min_stage_impressions": 5,
            "stage_drop_off_threshold": 0.5,
            "min_segment_impressions": 5,
            "segment_gap_threshold": 0.5,
            "trend_window": 3,
            "trend_decline_threshold": 0.9,
        },
    )
    assert obs.status_code == 200
    payload = obs.json()
    assert payload["policy"] == "journey_perception_v1"
    assert payload["totals"]["total"] >= 1
    assert any(
        item["kind"] == "stage_drop_off" and item["stage"] == "landing"
        for item in payload["observations"]
    )


def test_journey_reasoning_returns_plan() -> None:
    for _ in range(6):
        decide = client.post("/journey/decide", json={
            "stage": "product_page",
            "context": {"device_type": "mobile", "traffic_source": "meta"},
        }).json()
        client.post("/journey/event", json={
            "decision_id": decide["decision_id"],
            "event_type": "drop_off",
        })

    resp = client.get(
        "/journey/reasoning",
        params={
            "min_stage_impressions": 5,
            "stage_drop_off_threshold": 0.5,
            "max_hypotheses": 2,
            "max_experiments": 2,
        },
    )
    assert resp.status_code == 200

    payload = resp.json()
    assert payload["policy"] == "journey_reasoning_v1"
    assert payload["backend"] == "mock"
    assert payload["source_observations"] >= 1
    assert len(payload["hypotheses"]) >= 1
    assert len(payload["hypotheses"]) <= 2
    assert len(payload["experiments"]) >= 1
    assert len(payload["experiments"]) <= 2
    assert payload["experiments"][0]["hypothesis_id"] in {
        h["hypothesis_id"]
        for h in payload["hypotheses"]
    }


def test_agent_tick_status_and_history_flow() -> None:
    first = client.post("/agent/tick", json={
        "simulate_sessions": 140,
        "min_stage_impressions": 20,
        "stage_drop_off_threshold": 0.5,
        "max_hypotheses": 2,
        "max_experiments": 2,
    })
    assert first.status_code == 200
    tick_one = first.json()
    assert tick_one["tick"] == 1
    assert tick_one["simulation"]["sessions"] == 140
    assert tick_one["status"]["tick_count"] == 1
    assert tick_one["events"]

    status = client.get("/agent/status")
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["tick_count"] == 1
    assert "journey_metrics" in status_payload
    assert "stages" in status_payload["journey_metrics"]

    second = client.post("/agent/tick", json={
        "simulate_sessions": 180,
        "min_stage_impressions": 20,
        "stage_drop_off_threshold": 0.5,
        "max_hypotheses": 2,
        "max_experiments": 2,
    })
    assert second.status_code == 200
    tick_two = second.json()
    assert tick_two["tick"] == 2
    assert tick_two["status"]["tick_count"] == 2

    history = client.get("/agent/history", params={"limit": 8})
    assert history.status_code == 200
    events = history.json()["events"]
    assert 1 <= len(events) <= 8
    event_types = {e["event_type"] for e in events}
    assert "observe" in event_types
    assert "reason" in event_types
