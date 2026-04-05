from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def setup_function() -> None:
    client.post("/reset")


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

