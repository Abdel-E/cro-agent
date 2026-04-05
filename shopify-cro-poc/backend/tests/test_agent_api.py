from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def setup_function() -> None:
    client.post("/reset")


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

