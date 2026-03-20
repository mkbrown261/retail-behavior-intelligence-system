import React, { useState, useEffect, useCallback } from 'react'
import AddCameraModal from '../components/cameras/AddCameraModal'
import { cameraAPI } from '../utils/api'
import api from '../utils/api'

const API_BASE    = import.meta.env.VITE_API_URL || ''
const IS_DEMO     = !API_BASE          // no backend configured → demo mode

const STATUS_DOT = {
  CONNECTED:    { color: '#3fb950', pulse: true,  label: 'Live'          },
  CONNECTING:   { color: '#d29922', pulse: true,  label: 'Connecting…'   },
  RECONNECTING: { color: '#d29922', pulse: true,  label: 'Reconnecting…' },
  DISCONNECTED: { color: '#f85149', pulse: false, label: 'Offline'       },
  ERROR:        { color: '#f85149', pulse: false, label: 'Error'         },
  STOPPED:      { color: '#6e7681', pulse: false, label: 'Stopped'       },
}

/* ─── Camera card ──────────────────────────────────────────────── */
function CameraCard({ cam, onRemove, onRestart }) {
  const [snap, setSnap] = useState(null)
  const dot      = STATUS_DOT[cam.status] || STATUS_DOT.STOPPED
  const name     = cam.extra?.display_name || cam.camera_id
  const location = cam.extra?.location || '—'

  useEffect(() => {
    if (cam.status !== 'CONNECTED') return
    const load = () =>
      cameraAPI.snapshotB64(cam.camera_id, 45)
        .then(r => setSnap(r.data?.frame_b64))
        .catch(() => {})
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [cam.camera_id, cam.status])

  return (
    <div className="rounded-2xl overflow-hidden flex flex-col"
      style={{ background: '#1a1d2e', border: '1px solid rgba(255,255,255,0.07)' }}>

      {/* Snapshot */}
      <div className="relative w-full bg-black" style={{ paddingTop: '56.25%' }}>
        {snap
          ? <img src={`data:image/jpeg;base64,${snap}`} alt={name}
              className="absolute inset-0 w-full h-full object-cover" />
          : <div className="absolute inset-0 flex items-center justify-center"
              style={{ background: '#0d1117' }}>
              <span className="text-4xl opacity-20">📷</span>
            </div>
        }
        {/* Status badge */}
        <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium"
          style={{ background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(4px)' }}>
          <span className={`w-1.5 h-1.5 rounded-full ${dot.pulse ? 'animate-pulse' : ''}`}
            style={{ background: dot.color }} />
          <span style={{ color: dot.color }}>{dot.label}</span>
        </div>
        {/* FPS */}
        {cam.status === 'CONNECTED' && (
          <div className="absolute top-2 right-2 px-2 py-1 rounded-full text-xs"
            style={{ background: 'rgba(0,0,0,0.65)', color: '#8b949e' }}>
            {(cam.fps_actual || 0).toFixed(0)} fps
          </div>
        )}
      </div>

      {/* Info */}
      <div className="p-4 flex flex-col gap-3">
        <div>
          <p className="font-semibold text-white text-sm">{name}</p>
          <p className="text-xs mt-0.5" style={{ color: '#6e7681' }}>{location}</p>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs px-2 py-0.5 rounded-full"
            style={{ background: 'rgba(124,58,237,0.15)', color: '#a78bfa', border: '1px solid rgba(124,58,237,0.3)' }}>
            {cam.cam_type}
          </span>
          <span className="text-xs" style={{ color: '#6e7681' }}>
            {cam.resolution?.[0] ? `${cam.resolution[0]}×${cam.resolution[1]}` : ''}
          </span>
        </div>
        <div className="flex gap-2">
          <button onClick={() => onRestart(cam.camera_id)}
            className="flex-1 py-1.5 rounded-lg text-xs font-medium transition-all"
            style={{ background: 'rgba(255,255,255,0.06)', color: '#8b949e', border: '1px solid rgba(255,255,255,0.08)' }}>
            ↺ Restart
          </button>
          <button onClick={() => onRemove(cam.camera_id)}
            className="flex-1 py-1.5 rounded-lg text-xs font-medium transition-all"
            style={{ background: 'rgba(248,81,73,0.08)', color: '#f85149', border: '1px solid rgba(248,81,73,0.2)' }}>
            Remove
          </button>
        </div>
      </div>
    </div>
  )
}

/* ─── QR panel ─────────────────────────────────────────────────── */
function PhoneConnectPanel({ networkInfo }) {
  const hasUrls = networkInfo?.urls?.length > 0

  return (
    <div className="flex flex-col gap-4 max-w-lg">
      <div className="rounded-2xl p-6"
        style={{ background: '#1a1d2e', border: '1px solid rgba(255,255,255,0.07)' }}>
        <h2 className="font-bold text-white mb-1 flex items-center gap-2">
          📱 Open dashboard on your phone
        </h2>
        <p className="text-sm mb-5" style={{ color: '#6e7681' }}>
          Make sure your phone is on the same Wi-Fi as this computer, then scan below.
        </p>

        {hasUrls ? (
          <div className="flex flex-wrap gap-6 justify-center">
            {networkInfo.urls.map(u => (
              <div key={u} className="flex flex-col items-center gap-2">
                <img
                  src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&color=ffffff&bgcolor=1a1d2e&data=${encodeURIComponent(u)}`}
                  alt="QR"
                  className="rounded-xl"
                  style={{ width: 150, height: 150 }}
                />
                <code className="text-xs px-2 py-1 rounded-lg"
                  style={{ background: '#252838', color: '#a78bfa' }}>{u}</code>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-xl p-4" style={{ background: '#252838' }}>
            <p className="text-sm" style={{ color: '#6e7681' }}>
              Could not auto-detect IP. On your phone, open:
            </p>
            <code className="block mt-2 text-sm" style={{ color: '#a78bfa' }}>
              http://&lt;your-computer-ip&gt;:8000
            </code>
            <p className="text-xs mt-2" style={{ color: '#6e7681' }}>
              To find your IP: on Windows run <code className="px-1 rounded" style={{ background: '#1a1d2e' }}>ipconfig</code>,
              on Mac/Linux run <code className="px-1 rounded" style={{ background: '#1a1d2e' }}>ifconfig</code>.
            </p>
          </div>
        )}
      </div>

      <div className="rounded-2xl p-6"
        style={{ background: '#1a1d2e', border: '1px solid rgba(255,255,255,0.07)' }}>
        <h2 className="font-bold text-white mb-3">Common RTSP URLs by brand</h2>
        <p className="text-xs mb-3" style={{ color: '#6e7681' }}>
          Replace <code className="px-1 rounded" style={{ background: '#252838' }}>admin:pass</code> and
          <code className="mx-1 px-1 rounded" style={{ background: '#252838' }}>IP</code> with your camera's credentials and address.
        </p>
        <div className="flex flex-col gap-2">
          {[
            { brand: 'Hikvision', url: 'rtsp://admin:pass@IP:554/Streaming/Channels/101'   },
            { brand: 'Dahua',     url: 'rtsp://admin:pass@IP:554/cam/realmonitor?channel=1' },
            { brand: 'Reolink',   url: 'rtsp://admin:pass@IP:554/h264Preview_01_main'       },
            { brand: 'Amcrest',   url: 'rtsp://admin:pass@IP:554/cam/realmonitor?channel=1' },
            { brand: 'Generic',   url: 'rtsp://admin:pass@IP:554/stream1'                   },
          ].map(r => (
            <div key={r.brand} className="flex gap-3 items-center">
              <span className="text-xs w-20 flex-shrink-0" style={{ color: '#8b949e' }}>{r.brand}</span>
              <code className="text-xs px-2 py-1 rounded-lg flex-1 overflow-x-auto"
                style={{ background: '#252838', color: '#a78bfa', whiteSpace: 'nowrap' }}>{r.url}</code>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ─── Demo / no-backend guide ──────────────────────────────────── */
function DemoGuide() {
  const steps = [
    {
      icon: '💻',
      title: 'Install the RBIS backend',
      desc: 'On the computer connected to your cameras, clone and start the backend.',
      code: 'git clone https://github.com/mkbrown261/retail-behavior-intelligence-system\ncd retail-behavior-intelligence-system\nbash run.sh',
    },
    {
      icon: '🌐',
      title: 'Open the dashboard on your phone',
      desc: 'The backend serves the dashboard on port 8000. On any device on the same Wi-Fi:',
      code: 'http://<your-computer-ip>:8000',
    },
    {
      icon: '📷',
      title: 'Add your cameras',
      desc: 'Click "Add Camera", enter your RTSP URL, test the connection, then save.',
      code: null,
    },
    {
      icon: '🐳',
      title: 'Or use Docker (easiest)',
      desc: 'One command — no Python needed:',
      code: 'docker-compose up',
    },
  ]

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      {/* Hero */}
      <div className="rounded-2xl p-6 flex flex-col gap-3"
        style={{ background: 'rgba(124,58,237,0.08)', border: '1px solid rgba(124,58,237,0.2)' }}>
        <div className="flex items-center gap-3">
          <span className="text-3xl">📡</span>
          <div>
            <h2 className="text-lg font-bold text-white">No backend connected</h2>
            <p className="text-sm mt-0.5" style={{ color: '#a78bfa' }}>
              You're viewing the demo version. To connect real cameras, start the backend.
            </p>
          </div>
        </div>
        <a
          href="https://github.com/mkbrown261/retail-behavior-intelligence-system"
          target="_blank" rel="noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold text-white self-start transition-all"
          style={{ background: '#7c3aed' }}>
          View Setup Guide on GitHub →
        </a>
      </div>

      {/* Steps */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {steps.map((s, i) => (
          <div key={i} className="rounded-2xl p-5 flex flex-col gap-3"
            style={{ background: '#1a1d2e', border: '1px solid rgba(255,255,255,0.07)' }}>
            <div className="flex items-center gap-2">
              <span className="text-xl">{s.icon}</span>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs px-1.5 py-0.5 rounded-full font-bold"
                    style={{ background: 'rgba(124,58,237,0.2)', color: '#a78bfa' }}>
                    Step {i + 1}
                  </span>
                </div>
                <p className="font-semibold text-white text-sm mt-0.5">{s.title}</p>
              </div>
            </div>
            <p className="text-xs" style={{ color: '#8b949e' }}>{s.desc}</p>
            {s.code && (
              <pre className="text-xs p-3 rounded-lg overflow-x-auto"
                style={{ background: '#0d1117', color: '#a78bfa', border: '1px solid rgba(255,255,255,0.06)' }}>
                {s.code}
              </pre>
            )}
          </div>
        ))}
      </div>

      {/* System requirements */}
      <div className="rounded-2xl p-5"
        style={{ background: '#1a1d2e', border: '1px solid rgba(255,255,255,0.07)' }}>
        <h3 className="font-semibold text-white text-sm mb-3">System Requirements</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { icon: '🐍', label: 'Python 3.10+', note: 'or Docker' },
            { icon: '📷', label: 'IP/USB Camera', note: 'RTSP, ONVIF, USB' },
            { icon: '🌐', label: 'Local Network', note: 'Same Wi-Fi' },
            { icon: '💾', label: '4 GB RAM', note: 'Recommended' },
          ].map(r => (
            <div key={r.label} className="flex flex-col items-center gap-1 py-3 rounded-xl text-center"
              style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.05)' }}>
              <span className="text-xl">{r.icon}</span>
              <p className="text-xs font-medium text-white">{r.label}</p>
              <p className="text-xs" style={{ color: '#6e7681' }}>{r.note}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ─── Main page ─────────────────────────────────────────────────── */
export default function CamerasPage() {
  const [cameras, setCameras] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [networkInfo, setNet] = useState(null)
  const [tab, setTab]         = useState(IS_DEMO ? 'setup' : 'cameras')
  const [backendOk, setBackendOk] = useState(!IS_DEMO)

  const refresh = useCallback(async () => {
    try {
      const res = await cameraAPI.list()
      setCameras(res.data?.cameras || [])
      setBackendOk(true)
    } catch (_) {
      setBackendOk(false)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [refresh])

  useEffect(() => {
    if (backendOk) {
      api.get('/api/network-info').then(r => setNet(r.data)).catch(() => {})
    }
  }, [backendOk])

  const handleRemove  = async (id) => { await cameraAPI.remove(id).catch(() => {}); refresh() }
  const handleRestart = async (id) => { await cameraAPI.restart(id).catch(() => {}); refresh() }

  const live = cameras.filter(c => c.status === 'CONNECTED').length

  // Determine available tabs
  const tabs = [
    ...( backendOk ? [
      { key: 'cameras', label: '📷 My Cameras' },
      { key: 'phone',   label: '📱 Open on Phone' },
    ] : []),
    { key: 'setup', label: backendOk ? '⚙️ Setup Guide' : '🚀 Get Started' },
  ]

  return (
    <div className="flex flex-col gap-6 max-w-5xl mx-auto">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Cameras</h1>
          <p className="text-sm mt-0.5" style={{ color: '#6e7681' }}>
            {backendOk
              ? `${cameras.length} camera${cameras.length !== 1 ? 's' : ''} configured · ${live} live`
              : 'Connect your cameras to start monitoring'}
          </p>
        </div>
        {backendOk && (
          <button onClick={() => setShowAdd(true)}
            className="px-5 py-2.5 rounded-xl text-sm font-bold text-white transition-all"
            style={{ background: '#7c3aed' }}>
            + Add Camera
          </button>
        )}
      </div>

      {/* Stats (only when cameras exist) */}
      {backendOk && cameras.length > 0 && (
        <div className="flex gap-3">
          {[
            { label: 'Total',   value: cameras.length },
            { label: 'Live',    value: live,                          color: '#3fb950' },
            { label: 'Offline', value: cameras.length - live,         color: live < cameras.length ? '#f85149' : '#6e7681' },
          ].map(s => (
            <div key={s.label} className="flex-1 rounded-xl px-4 py-3"
              style={{ background: '#1a1d2e', border: '1px solid rgba(255,255,255,0.07)' }}>
              <p className="text-2xl font-bold" style={{ color: s.color || '#fff' }}>{s.value}</p>
              <p className="text-xs mt-0.5" style={{ color: '#6e7681' }}>{s.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className="px-4 py-2.5 text-sm font-medium transition-colors"
            style={{
              borderBottom: tab === t.key ? '2px solid #7c3aed' : '2px solid transparent',
              color: tab === t.key ? '#a78bfa' : '#6e7681',
              marginBottom: -1,
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Cameras tab ── */}
      {tab === 'cameras' && backendOk && (
        <>
          {loading && (
            <div className="flex items-center justify-center py-16">
              <span className="animate-spin text-2xl text-purple-400">⟳</span>
            </div>
          )}

          {!loading && cameras.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <span className="text-6xl opacity-20">📷</span>
              <div className="text-center">
                <p className="font-semibold text-white mb-1">No cameras connected</p>
                <p className="text-sm" style={{ color: '#6e7681' }}>
                  Add your first camera to start monitoring
                </p>
              </div>
              <button onClick={() => setShowAdd(true)}
                className="mt-2 px-6 py-2.5 rounded-xl text-sm font-bold text-white"
                style={{ background: '#7c3aed' }}>
                + Add Camera
              </button>
            </div>
          )}

          {cameras.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {cameras.map(cam => (
                <CameraCard
                  key={cam.camera_id}
                  cam={cam}
                  onRemove={handleRemove}
                  onRestart={handleRestart}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* ── Open on Phone tab ── */}
      {tab === 'phone' && backendOk && (
        <PhoneConnectPanel networkInfo={networkInfo} />
      )}

      {/* ── Setup / Get Started tab ── */}
      {tab === 'setup' && (
        <DemoGuide />
      )}

      {/* Add camera modal */}
      {showAdd && (
        <AddCameraModal
          onClose={() => setShowAdd(false)}
          onAdded={() => { setShowAdd(false); refresh() }}
        />
      )}
    </div>
  )
}
