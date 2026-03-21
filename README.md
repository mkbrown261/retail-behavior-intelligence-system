# Retail Behavior Intelligence System (RBIS) v2.0

A lightweight, self-hostable AI-powered loss-prevention dashboard.  
Point a camera at your store floor and watch the suspicion scoring run in real time.

---

## Live Links

| Environment | URL |
|-------------|-----|
| **Cloudflare Pages (demo)** | https://rbis-dashboard.pages.dev |
| **Backend (sandbox)** | https://8000-i7o55g4uto9w9c184smpt-b9b802c4.sandbox.novita.ai |
| **GitHub** | https://github.com/mkbrown261/retail-behavior-intelligence-system |

---

## Project Structure

```
retail-behavior-intelligence-system/
├── backend/          # FastAPI + SQLite + OpenCV
│   ├── app/
│   │   ├── api/          # REST endpoints (cameras, persons, alerts, analytics, events)
│   │   ├── camera/       # CameraStream, CameraManager, IntentBus
│   │   ├── core/         # config.py, database.py, websocket.py
│   │   ├── models/       # SQLAlchemy ORM models
│   │   └── services/     # scoring, alerts, heatmap, reports, storage
│   ├── cameras.yaml      # Camera configuration (edit to add real cameras)
│   ├── .env              # Your environment variables (DO NOT commit)
│   ├── .env.example      # Template — copy to .env and fill in
│   └── requirements.txt
├── frontend/         # React + Vite + Tailwind dashboard
│   └── src/
│       ├── pages/    # Dashboard, Cameras, Persons, Alerts, Analytics
│       └── components/
├── run.sh            # Mac/Linux one-click start
├── run.bat           # Windows one-click start
├── docker-compose.yml
└── ecosystem.config.cjs   # PM2 process manager config
```

---

## Quick Start (Self-Hosted)

### Prerequisites
- Python 3.10+ → https://python.org
- Git → https://git-scm.com

### Steps

```bash
# 1 — Clone
git clone https://github.com/mkbrown261/retail-behavior-intelligence-system
cd retail-behavior-intelligence-system

# 2 — Configure environment
cp backend/.env.example backend/.env
# Edit backend/.env:
#   Set SECRET_KEY to a random hex string:
#     python3 -c "import secrets; print(secrets.token_hex(32))"
#   Set DEBUG=false for production
#   Set ALLOWED_ORIGINS to your actual frontend domain

# 3 — Start
bash run.sh          # Mac / Linux
run.bat              # Windows (double-click)

# 4 — Open dashboard
# Local browser:  http://localhost:8000
# Phone (same Wi-Fi): http://<your-local-IP>:8000
```

### Docker Alternative

```bash
docker-compose up -d    # First run takes ~5 minutes
docker-compose down     # Stop
```

### Add Real Cameras

Edit `backend/cameras.yaml`:

```yaml
cameras:
  - camera_id: front_door
    cam_type: RTSP
    source: "rtsp://admin:password@192.168.1.100:554/stream1"
    width: 1280
    height: 720
    fps: 15
```

Then restart the backend. Supported types: `USB`, `RTSP`, `HTTP`, `ONVIF`, `FILE`, `MOCK`.

Common RTSP URLs:
- **Hikvision**: `rtsp://admin:PASS@IP:554/Streaming/Channels/101`
- **Reolink**: `rtsp://admin:PASS@IP:554/h264Preview_01_main`
- **Dahua**: `rtsp://admin:PASS@IP:554/cam/realmonitor?channel=1&subtype=0`
- **Wyze**: `rtsp://admin:PASS@IP:554/live`

---

## API Reference

Base URL: `http://localhost:8000`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Service health + pipeline status |
| GET | `/api/system-status` | Full system overview |
| GET | `/api/network-info` | Local IPs for QR code |
| GET | `/api/cameras` | List all cameras |
| POST | `/api/cameras` | Add camera at runtime |
| DELETE | `/api/cameras/{id}` | Remove camera |
| POST | `/api/cameras/{id}/restart` | Restart camera stream |
| GET | `/api/cameras/{id}/snapshot` | Latest JPEG snapshot |
| GET | `/api/cameras/{id}/mjpeg` | Live MJPEG stream |
| POST | `/api/cameras/discover/onvif` | Auto-discover ONVIF cameras |
| GET | `/api/persons/` | List tracked persons |
| GET | `/api/persons/stats` | Counts by type/status |
| GET | `/api/persons/live-scores` | Real-time suspicion scores |
| GET | `/api/persons/{id}/timeline` | Full person event timeline |
| PATCH | `/api/persons/{id}/type` | Mark as STAFF or CUSTOMER |
| GET | `/api/alerts/` | List alerts |
| POST | `/api/alerts/{id}/acknowledge` | Acknowledge an alert |
| GET | `/api/analytics/heatmap` | Store heatmap data |
| GET | `/api/analytics/repeat-visitors` | Cluster visitor data |
| POST | `/api/analytics/reports/generate` | Generate daily PDF report |
| WS | `/ws/{client_id}` | Real-time WebSocket feed |

---

## Security Checklist (Production)

Before deploying to a customer site:

- [ ] **`DEBUG=false`** in `.env`
- [ ] **`SECRET_KEY`** set to a random 64-char hex string:  
  `python3 -c "import secrets; print(secrets.token_hex(32))"`
- [ ] **`ALLOWED_ORIGINS`** restricted to your actual frontend domain  
  e.g. `'["https://your-domain.pages.dev"]'`
- [ ] **`.env` is NOT committed to git** (confirmed in `.gitignore`)
- [ ] Camera RTSP credentials use strong, unique passwords
- [ ] API docs disabled (they are — `docs_url=None` when `DEBUG=false`)
- [ ] Rate limiter active (300 req/min per IP — configurable via `RATE_LIMIT_PER_MINUTE`)
- [ ] WebSocket connection limit active (100 connections — `WS_MAX_CONNECTIONS`)
- [ ] All security headers verified: `X-Frame-Options`, `X-Content-Type-Options`,  
  `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy`, `HSTS`
- [ ] Server fingerprinting header suppressed (`--no-server-header` in uvicorn)

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              Frontend (React)               │
│   Dashboard / Cameras / Persons / Alerts    │
│   Self-hosted: served from backend/static/  │
│   Demo mode: Cloudflare Pages               │
└────────────────┬────────────────────────────┘
                 │ REST + WebSocket
┌────────────────▼────────────────────────────┐
│           Backend (FastAPI)                 │
│                                             │
│  ┌──────────────┐  ┌──────────────────────┐ │
│  │ CameraManager│  │ VideoProcessingPipeline│ │
│  │ (IntentBus)  │  │ (Simulation/YOLO)    │ │
│  └──────┬───────┘  └──────────┬───────────┘ │
│         │                     │             │
│  ┌──────▼─────────────────────▼───────────┐ │
│  │         EventOrchestrator              │ │
│  │   Scoring · Alerts · Heatmap · WS      │ │
│  └──────────────────┬─────────────────────┘ │
│                     │                       │
│  ┌──────────────────▼─────────────────────┐ │
│  │         SQLite (D1-ready)              │ │
│  │  persons · events · alerts · heatmap  │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## Data Models

| Model | Key Fields |
|-------|-----------|
| **Person** | session_id, person_type, suspicion_score, suspicion_level, is_flagged, cameras_seen |
| **Event** | person_id, event_type, camera_id, zone, bbox, confidence, is_suspicious |
| **SuspicionScore** | person_id, score, level, delta, reason |
| **Alert** | person_id, session_id, severity, event_type, suspicion_score, acknowledged |
| **HeatmapPoint** | person_id, camera_id, grid_x, grid_y, interaction_type, weight |
| **RepeatVisitor** | cluster_id, visit_count, avg_suspicion_score, is_flagged_pattern |

---

## Deployment Status

| Component | Status | Platform |
|-----------|--------|----------|
| Frontend (demo) | ✅ Live | Cloudflare Pages |
| Backend | ✅ Running | Self-hosted / Sandbox |
| Database | ✅ SQLite | Local file (`data/rbis.db`) |
| Camera streams | ✅ 2x MOCK | Simulation mode |

**Tech Stack**: FastAPI 0.109 · Python 3.12 · SQLAlchemy 2.0 · OpenCV 4.9 · React 18 · Vite · Tailwind CSS

**Last Updated**: 2026-03-21 — Security audit + production hardening
