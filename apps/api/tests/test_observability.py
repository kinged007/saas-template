"""Issue #21: request IDs, metrics endpoint, retention cleanup."""

from __future__ import annotations

from src.core import metrics
from src.core.request_id import get_request_id


async def test_request_id_echoed_and_minted(app_client):
    resp = await app_client.get("/api/v1/healthz")
    assert resp.status_code == 200
    assert len(resp.headers["X-Request-ID"]) == 16

    resp = await app_client.get("/api/v1/healthz", headers={"X-Request-ID": "abc123"})
    assert resp.headers["X-Request-ID"] == "abc123"


async def test_request_id_default_outside_request():
    assert get_request_id() == "-"


async def test_metrics_endpoint_counts_requests(app_client):
    metrics.reset()
    await app_client.get("/api/v1/healthz")
    await app_client.get("/api/v1/healthz")
    resp = await app_client.get("/api/v1/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "X-Request-ID" in resp.headers
    body = resp.text
    assert "# TYPE http_requests_total counter" in body
    assert 'http_requests_total{method="GET",path="/api/v1/healthz",status="200"} 2' in body


async def test_metrics_render_empty_and_reset():
    metrics.reset()
    assert metrics.render_prometheus() == ""
    metrics.inc("job_runs_total", key="k", status="success")
    assert 'job_runs_total{key="k",status="success"} 1' in metrics.render_prometheus()
    metrics.reset()
    assert metrics.render_prometheus() == ""


async def test_retention_cleanup_job_registered_and_runs(app_client, monkeypatch):
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.jobs.registry import job_registry
    from src.models.jobs import JobDefinition

    spec = job_registry.get("system.retention_cleanup")
    assert spec is not None and spec.scope == "global"

    async with SessionFactory() as session:
        definition = (
            await session.execute(
                select(JobDefinition).where(JobDefinition.key == "system.retention_cleanup")
            )
        ).scalar_one()
        assert definition.enabled is True

    # Old acknowledged notification is removed; unacknowledged is kept.
    from datetime import UTC, datetime, timedelta

    from src import settings as settings_module
    from src.models.core import Notification

    monkeypatch.setattr(settings_module.settings, "notifications_retention_days", 90)

    import uuid

    old = datetime.now(UTC) - timedelta(days=400)
    uid, wid = str(uuid.uuid4()), str(uuid.uuid4())
    async with SessionFactory() as session:
        session.add(
            Notification(
                user_id=uid,
                workspace_id=wid,
                type="t",
                title="old-acked",
                created_at=old,
                acknowledged_at=old,
            )
        )
        session.add(
            Notification(
                user_id=uid,
                workspace_id=wid,
                type="t",
                title="old-unacked",
                created_at=old,
            )
        )
        await session.commit()
        await spec.handler(type("Ctx", (), {"session": lambda self: SessionFactory()})())
        remaining = (await session.execute(select(Notification.title))).scalars().all()
    assert remaining == ["old-unacked"]
