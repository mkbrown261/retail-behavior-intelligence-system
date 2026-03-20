# Retail Behavior Intelligence System (RBIS) v2.0

> **Production-grade multi-camera retail surveillance platform** — Phase 1 core tracking + Phase 2 advanced analytics. Behavior-based only. No facial recognition.

---

## 🖥️ Live Dashboard
- **Frontend:** React + Vite (port 5173)
- **Backend API:** FastAPI + Python (port 8000)
- **API Docs:** `http://localhost:8000/api/docs`

---

## 🏗️ Architecture

```
rbis/
├── backend/              ← FastAPI Python backend
│   ├── app/
│   │   ├── core/         ← Config, DB engine, WebSocket manager
│   │   ├── models/       ← 8 SQLAlchemy tables
│   │   ├── services/     ← Scoring, pipeline, heatmap, alerts, reports
│   │   └── api/          ← REST routes (persons, alerts, analytics, cameras)
│   └── data/             ← snapshots/, clips/, reports/
└── frontend/             ← React 18 + Vite dashboard
    └── src/
        ├── pages/        ← LiveDashboard, Analytics, Persons
        ├── components/   ← CameraGrid, Alerts, Heatmap, Timeline
        ├── hooks/        ← useWebSocket (real-time)
        └── utils/        ← API client (axios)
```

---

## ✅ Phase 1 Features
| Feature | Status |
|---|---|
| 5-camera simulation pipeline | ✅ |
| Person detection & multi-camera tracking | ✅ |
| 8 event types (ENTER, PICK, HOLD, RETURN, CHECKOUT, BYPASS, EXIT…) | ✅ |
| Real-time suspicion scoring (0–100) | ✅ |
| NORMAL / WATCH / HIGH_SUSPICION levels | ✅ |
| Snapshot & clip capture on alert | ✅ |
| WebSocket real-time push to dashboard | ✅ |
| Staff vs Customer classification | ✅ |
| SQLite persistent storage (8 tables) | ✅ |

## ✅ Phase 2 Features
| Feature | Status |
|---|---|
| Store heatmap (50×40 grid, Canvas render) | ✅ |
| Hourly traffic filter on heatmap | ✅ |
| Repeat visitor detection (colour clustering, no face recognition) | ✅ |
| Smart alerts — 4 severity tiers (LOW/MEDIUM/HIGH/CRITICAL) | ✅ |
| Daily Intelligence Report (PDF via ReportLab) | ✅ |
| Person timeline replay (events + score chart) | ✅ |
| Top Incidents panel | ✅ |
| Notification stubs (SMS/Email — wire up Twilio/SendGrid) | ✅ |

---

## 🗄️ Database Schema
| Table | Purpose |
|---|---|
| `persons` | Tracked individual sessions |
| `events` | All detected events with timestamps + bbox |
| `suspicion_scores` | Score snapshot history per person |
| `media` | Snapshot/clip file references |
| `heatmap_points` | Grid-based positional data |
| `repeat_visitors` | Appearance cluster tracking |
| `alerts` | Alert log with severity + acknowledgement |
| `daily_reports` | Aggregated daily KPI reports |

---

## 🚀 Quick Start

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

Or use PM2:
```bash
pm2 start ecosystem.config.cjs
```

---

## ⚙️ Configuration (`backend/.env`)
```
DATABASE_URL=sqlite+aiosqlite:///./rbis.db
NUM_CAMERAS=5
THRESHOLD_WATCH=31
THRESHOLD_HIGH=61
# Add Twilio/SendGrid/S3 credentials for full notifications + cloud storage
```

---

## 🔒 Privacy & Compliance
- ❌ No facial recognition
- ❌ No identity matching with external databases
- ✅ Behavior-based analytics only
- ✅ Appearance clustering without biometric identity
