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

