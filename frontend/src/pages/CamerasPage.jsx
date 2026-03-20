import React, { useState, useEffect } from 'react'
import CameraWizard from '../components/cameras/CameraWizard'
import { cameraAPI } from '../utils/api'
import api from '../utils/api'

const STATUS_COLOR = {
  CONNECTED:    'text-green-400',
  CONNECTING:   'text-yellow-400',
  RECONNECTING: 'text-yellow-400',
  DISCONNECTED: 'text-red-400',
  ERROR:        'text-red-500',
  STOPPED:      'text-gray-400',
}

function QRCode({ url }) {
  // Use a free QR API — no server-side needed
  const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(url)}`
  return (
    <div className="flex flex-col items-center gap-2">
      <img src={qrUrl} alt="QR code" className="rounded border border-rbis-700 w-32 h-32" />
      <p className="text-xs text-rbis-400 text-center break-all max-w-xs">{url}</p>
    </div>
  )
}

function CameraRow({ cam, onRemove, onRestart }) {
  const [snapshot, setSnapshot] = useState(null)

  useEffect(() => {
    if (cam.status !== 'CONNECTED') return
    cameraAPI.snapshotB64(cam.camera_id, 40)
      .then(r => setSnapshot(r.data?.frame_b64))
      .catch(() => {})
    const t = setInterval(() => {
      cameraAPI.snapshotB64(cam.camera_id, 40)
        .then(r => setSnapshot(r.data?.frame_b64))
        .catch(() => {})
    }, 3000)
    return () => clearInterval(t)
  }, [cam.camera_id, cam.status])

  return (
    <div className="card p-4 flex gap-4">
      {/* Snapshot thumbnail */}
      <div className="w-32 h-20 rounded overflow-hidden bg-rbis-800 flex-shrink-0 flex items-center justify-center">
        {snapshot
          ? <img src={`data:image/jpeg;base64,${snapshot}`} alt={cam.camera_id} className="w-full h-full object-cover" />
          : <span className="text-rbis-600 text-xs">No frame</span>
        }
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-semibold text-rbis-100">{cam.camera_id}</span>
          <span className="badge-outline text-xs">{cam.cam_type}</span>
          <span className={`text-xs font-medium ${STATUS_COLOR[cam.status] || 'text-gray-400'}`}>
            ● {cam.status}
          </span>
        </div>
        <p className="text-xs text-rbis-400 truncate mb-1">{cam.source}</p>
        <p className="text-xs text-rbis-500">
          {cam.resolution?.[0]}×{cam.resolution?.[1]} · {cam.fps_actual} fps · {cam.frames_total} frames
        </p>
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-1 flex-shrink-0">
        <button onClick={() => onRestart(cam.camera_id)}
          className="btn-ghost text-xs px-3 py-1">↺ Restart</button>
        <button onClick={() => onRemove(cam.camera_id)}
          className="btn-ghost text-xs px-3 py-1 text-red-400 hover:text-red-300">✕ Remove</button>
      </div>
    </div>
  )
}

export default function CamerasPage() {
  const [cameras, setCameras]       = useState([])
  const [loading, setLoading]       = useState(true)
  const [showWizard, setShowWizard] = useState(false)
  const [networkInfo, setNetworkInfo] = useState(null)
  const [tab, setTab]               = useState('cameras') // cameras | connect

  const refresh = async () => {
    try {
      const res = await cameraAPI.list()
      setCameras(res.data?.cameras || [])
    } catch (_) {}
    setLoading(false)
  }

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    api.get('/api/network-info')
      .then(r => setNetworkInfo(r.data))
      .catch(() => {})
  }, [])

  const handleRemove = async (id) => {
    await cameraAPI.remove(id).catch(() => {})
    refresh()
  }
  const handleRestart = async (id) => {
    await cameraAPI.restart(id).catch(() => {})
    refresh()
  }

  const connected = cameras.filter(c => c.status === 'CONNECTED').length

  return (
    <div className="flex flex-col gap-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-rbis-100">Cameras</h1>
          <p className="text-rbis-400 text-sm mt-0.5">
            {cameras.length} registered · {connected} live
          </p>
        </div>
        <button onClick={() => { setShowWizard(true); setTab('cameras') }}
          className="btn-primary flex items-center gap-2">
          + Add Camera
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-rbis-700 pb-0">
        {['cameras', 'connect'].map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px
              ${tab === t ? 'border-accent-blue text-accent-blue' : 'border-transparent text-rbis-400 hover:text-rbis-200'}`}>
            {t === 'cameras' ? '📷 My Cameras' : '📱 Connect from Phone'}
          </button>
        ))}
      </div>

      {/* Camera list tab */}
      {tab === 'cameras' && (
        <div className="flex flex-col gap-3">
          {loading && <p className="text-rbis-400 text-sm">Loading…</p>}
          {!loading && cameras.length === 0 && (
            <div className="card p-8 text-center">
              <p className="text-4xl mb-3">📷</p>
              <p className="text-rbis-300 font-semibold mb-1">No cameras connected yet</p>
              <p className="text-rbis-500 text-sm mb-4">
                Add a USB webcam, RTSP IP camera, or ONVIF camera to get started
              </p>
              <button onClick={() => setShowWizard(true)} className="btn-primary">
                + Add Your First Camera
              </button>
            </div>
          )}
          {cameras.map(cam => (
            <CameraRow
              key={cam.camera_id}
              cam={cam}
              onRemove={handleRemove}
              onRestart={handleRestart}
            />
          ))}
        </div>
      )}

      {/* Connect from phone tab */}
      {tab === 'connect' && (
        <div className="flex flex-col gap-6">
          <div className="card p-6">
            <h2 className="font-bold text-rbis-100 mb-1">Open on your phone</h2>
            <p className="text-rbis-400 text-sm mb-4">
              Make sure your phone is on the <strong>same WiFi network</strong> as this computer,
              then scan the QR code or type the URL into your phone's browser.
            </p>
            {networkInfo?.urls?.length > 0 ? (
              <div className="flex flex-wrap gap-6 items-start">
                {networkInfo.urls.map(url => (
                  <QRCode key={url} url={url} />
                ))}
              </div>
            ) : (
              <p className="text-rbis-500 text-sm">
                Could not detect local IP. Try opening{' '}
                <code className="bg-rbis-800 px-1 rounded">http://&lt;this-computer-ip&gt;:8000</code>{' '}
                on your phone.
              </p>
            )}
          </div>

          <div className="card p-6">
            <h2 className="font-bold text-rbis-100 mb-3">How to add cameras from your phone</h2>
            <ol className="flex flex-col gap-3">
              {[
                { n: 1, text: 'Open the URL above on your phone browser' },
                { n: 2, text: 'Tap "Cameras" in the navigation menu' },
                { n: 3, text: 'Tap "+ Add Camera" and follow the wizard' },
                { n: 4, text: 'For IP cameras: enter the RTSP URL shown in your camera\'s app' },
                { n: 5, text: 'For USB cameras: they must be plugged into this computer' },
              ].map(step => (
                <li key={step.n} className="flex items-start gap-3">
                  <span className="w-6 h-6 rounded-full bg-accent-blue text-white text-xs font-bold
                    flex items-center justify-center flex-shrink-0 mt-0.5">{step.n}</span>
                  <span className="text-rbis-300 text-sm">{step.text}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="card p-6 border-rbis-600">
            <h2 className="font-bold text-rbis-100 mb-2">💡 Finding your camera's RTSP URL</h2>
            <p className="text-rbis-400 text-sm mb-3">
              Most IP cameras show the RTSP URL in their mobile app or web interface.
              Common formats:
            </p>
            <div className="flex flex-col gap-1">
              {[
                { brand: 'Hikvision', url: 'rtsp://admin:pass@192.168.1.x:554/Streaming/Channels/101' },
                { brand: 'Dahua',    url: 'rtsp://admin:pass@192.168.1.x:554/cam/realmonitor?channel=1' },
                { brand: 'Reolink',  url: 'rtsp://admin:pass@192.168.1.x:554/h264Preview_01_main' },
                { brand: 'Generic',  url: 'rtsp://admin:pass@192.168.1.x:554/stream1' },
              ].map(r => (
                <div key={r.brand} className="flex gap-3 items-baseline">
                  <span className="text-xs text-rbis-400 w-20 flex-shrink-0">{r.brand}</span>
                  <code className="text-xs bg-rbis-800 px-2 py-0.5 rounded text-accent-blue break-all">{r.url}</code>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Wizard modal */}
      {showWizard && (
        <div className="fixed inset-0 bg-black/70 flex items-start justify-center z-50 p-4 pt-12 overflow-y-auto">
          <div className="card p-6 w-full max-w-lg">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-lg font-bold">Add Camera</h2>
              <button onClick={() => setShowWizard(false)} className="btn-ghost text-xl leading-none">×</button>
            </div>
            <CameraWizard onDone={() => { setShowWizard(false); refresh() }} />
          </div>
        </div>
      )}
    </div>
  )
}
