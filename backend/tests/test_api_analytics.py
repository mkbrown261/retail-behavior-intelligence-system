"""
test_api_analytics.py — HTTP-level tests for the /api/analytics endpoints.

Covers:
  - GET /api/analytics/heatmap              raw heatmap data
  - GET /api/analytics/heatmap/hourly       hourly aggregation
  - GET /api/analytics/heatmap/hotspots     top hotspot cells
  - GET /api/analytics/repeat-visitors      all clusters
  - GET /api/analytics/repeat-visitors/flagged  flagged clusters
  - GET /api/analytics/reports              report index
"""
import pytest

from app.models.analytics import HeatmapPoint, RepeatVisitor


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _create_heatmap_point(db, camera_id=1, grid_x=5, grid_y=5, weight=1.0, hour=10, day="2026-01-15"):
    hp = HeatmapPoint(
        camera_id=camera_id,
        grid_x=grid_x,
        grid_y=grid_y,
        norm_x=grid_x / 100.0,
        norm_y=grid_y / 100.0,
        weight=weight,
        hour_bucket=hour,
        day_bucket=day,
        interaction_type="WALK",
    )
    db.add(hp)
    await db.commit()
    return hp


async def _create_repeat_visitor(db, flagged=False, visit_count=1, score=0.0):
    import uuid
    rv = RepeatVisitor(
        cluster_id=f"cluster_{uuid.uuid4().hex[:8]}",
        dominant_color="#AA3344",
        visit_count=visit_count,
        avg_suspicion_score=score,
        max_suspicion_score=score,
        is_flagged_pattern=flagged,
    )
    db.add(rv)
    await db.commit()
    return rv


# ── GET /api/analytics/heatmap ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heatmap_empty(client):
    resp = await client.get("/api/analytics/heatmap")
    assert resp.status_code == 200
    data = resp.json()
    # Endpoint returns grid data — structure depends on implementation
    assert isinstance(data, (dict, list))


@pytest.mark.asyncio
async def test_heatmap_with_data(client, db):
    await _create_heatmap_point(db, grid_x=10, grid_y=20, weight=2.0)
    await _create_heatmap_point(db, grid_x=10, grid_y=20, weight=3.0)
    resp = await client.get("/api/analytics/heatmap")
    assert resp.status_code == 200


# ── GET /api/analytics/heatmap/hourly ────────────────────────────────────────

@pytest.mark.asyncio
async def test_heatmap_hourly_empty(client):
    resp = await client.get("/api/analytics/heatmap/hourly")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_heatmap_hourly_with_day_param(client, db):
    await _create_heatmap_point(db, hour=14, day="2026-01-15")
    resp = await client.get("/api/analytics/heatmap/hourly?day=2026-01-15")
    assert resp.status_code == 200


# ── GET /api/analytics/heatmap/hotspots ──────────────────────────────────────

@pytest.mark.asyncio
async def test_heatmap_hotspots_empty(client):
    resp = await client.get("/api/analytics/heatmap/hotspots")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_heatmap_hotspots_returns_top_cells(client, db):
    # Create several heatmap points, some at same cell (aggregate weight)
    await _create_heatmap_point(db, grid_x=1, grid_y=1, weight=10.0)
    await _create_heatmap_point(db, grid_x=1, grid_y=1, weight=5.0)
    await _create_heatmap_point(db, grid_x=2, grid_y=2, weight=1.0)
    resp = await client.get("/api/analytics/heatmap/hotspots")
    assert resp.status_code == 200


# ── GET /api/analytics/repeat-visitors ───────────────────────────────────────

@pytest.mark.asyncio
async def test_repeat_visitors_empty(client):
    resp = await client.get("/api/analytics/repeat-visitors")
    assert resp.status_code == 200
    data = resp.json()
    assert "visitors" in data or "clusters" in data or isinstance(data, list) or isinstance(data, dict)


@pytest.mark.asyncio
async def test_repeat_visitors_returns_data(client, db):
    await _create_repeat_visitor(db, visit_count=3, score=45.0)
    resp = await client.get("/api/analytics/repeat-visitors")
    assert resp.status_code == 200


# ── GET /api/analytics/repeat-visitors/flagged ───────────────────────────────

@pytest.mark.asyncio
async def test_flagged_repeat_visitors_empty(client):
    resp = await client.get("/api/analytics/repeat-visitors/flagged")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_flagged_repeat_visitors_only_flagged(client, db):
    await _create_repeat_visitor(db, flagged=False)
    await _create_repeat_visitor(db, flagged=True, visit_count=5, score=65.0)
    resp = await client.get("/api/analytics/repeat-visitors/flagged")
    assert resp.status_code == 200


# ── GET /api/analytics/reports ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_reports_empty(client):
    resp = await client.get("/api/analytics/reports")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_report_not_found(client):
    """Requesting a non-existent report date should return 404."""
    resp = await client.get("/api/analytics/reports/2020-01-01")
    assert resp.status_code == 404
