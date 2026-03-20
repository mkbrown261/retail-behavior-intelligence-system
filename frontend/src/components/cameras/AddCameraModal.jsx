import React, { useState } from 'react'
import { cameraAPI } from '../../utils/api'

const CAM_TYPES = [
  { label: 'IP Camera (RTSP)', value: 'RTSP',  icon: '🌐', placeholder: 'rtsp://192.168.1.100:554/stream1'  },
  { label: 'USB Webcam',       value: 'USB',   icon: '🖥️', placeholder: '0'                                },
  { label: 'ONVIF Camera',     value: 'ONVIF', icon: '📡', placeholder: 'rtsp://192.168.1.100:554/stream1'  },
  { label: 'MJPEG Stream',     value: 'HTTP',  icon: '📹', placeholder: 'http://192.168.1.100:8080/video'   },
  { label: 'Demo / Test Feed', value: 'MOCK',  icon: '🎭', placeholder: ''                                  },
]

const BRAND_URLS = [
  { brand: 'Hikvision', url: 'rtsp://admin:pass@IP:554/Streaming/Channels/101'  },
  { brand: 'Dahua',     url: 'rtsp://admin:pass@IP:554/cam/realmonitor?channel=1' },
  { brand: 'Reolink',   url: 'rtsp://admin:pass@IP:554/h264Preview_01_main'      },
  { brand: 'Generic',   url: 'rtsp://admin:pass@IP:554/stream1'                  },
]

export default function AddCameraModal({ onClose, onAdded }) {
  const [form, setForm] = useState({
    name:     '',
    location: '',
    type:     'RTSP',
    url:      '',
    username: '',
    password: '',
  })
  const [testState, setTestState] = useState('idle') // idle | testing | ok | fail
  const [testMsg,   setTestMsg]   = useState('')
  const [saving,    setSaving]    = useState(false)
  const [error,     setError]     = useState('')
  const [showBrands, setShowBrands] = useState(false)

  const set = (k, v) => { setForm(f => ({ ...f, [k]: v })); setTestState('idle'); setError('') }

  const selectedType = CAM_TYPES.find(t => t.value === form.type) || CAM_TYPES[0]
  const needsUrl  = form.type !== 'MOCK' && form.type !== 'USB'
  const needsAuth = form.type === 'RTSP' || form.type === 'ONVIF'
  const needsIdx  = form.type === 'USB'
  const isMock    = form.type === 'MOCK'

  // Build the camera_id from the name
  const camId = (form.name || 'camera')
    .toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') +
    '_' + Date.now().toString(36)

  // Test connection (add as MOCK, get snapshot, then remove)
  const handleTest = async () => {
    if (isMock) { setTestState('ok'); setTestMsg('Demo feed always works.'); return }
    if (needsUrl && !form.url.trim()) { setError('Please enter the stream URL first.'); return }

    setTestState('testing')
    setTestMsg('')
    setError('')

    // Temporarily add camera with a test ID, snapshot, then remove
    const testId = 'test_' + Date.now().toString(36)
    let source = form.url.trim() || selectedType.placeholder
    if (needsIdx) source = parseInt(source) || 0

    try {
      await cameraAPI.add({
        camera_id: testId,
        cam_type:  form.type,
        source,
        username: form.username,
        password: form.password,
        fps: 5,
        extra: { _test: true },
      })

      // Wait up to 4 s for first frame
      let frame = null
      for (let i = 0; i < 8; i++) {
        await new Promise(r => setTimeout(r, 500))
        try {
          const res = await cameraAPI.snapshotB64(testId, 30)
          if (res.data?.frame_b64) { frame = res.data.frame_b64; break }
        } catch (_) { /* keep trying */ }
      }

      await cameraAPI.remove(testId).catch(() => {})

      if (frame) {
        setTestState('ok')
        setTestMsg('Connection successful! Camera is online.')
      } else {
        setTestState('fail')
        setTestMsg('Connected but no video received. Check the stream URL.')
      }
    } catch (err) {
      await cameraAPI.remove(testId).catch(() => {})
      setTestState('fail')
      setTestMsg(err.response?.data?.detail || 'Could not reach the camera. Check IP, port and credentials.')
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.name.trim()) { setError('Camera name is required.'); return }
    setError('')
    setSaving(true)

    let source = form.url.trim() || selectedType.placeholder
    if (needsIdx) source = parseInt(source) || 0
    if (isMock)   source = `mock://${form.url || '0'}`

    try {
      await cameraAPI.add({
        camera_id: camId,
        cam_type:  form.type,
        source,
        username:  form.username,
        password:  form.password,
        extra: {
          display_name: form.name.trim(),
          location:     form.location.trim(),
        },
      })
      onAdded?.()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to add camera. Try testing the connection first.')
    }
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(6px)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose?.() }}>

      <div className="w-full max-w-md rounded-2xl flex flex-col overflow-hidden"
        style={{ background: '#1a1d2e', border: '1px solid rgba(255,255,255,0.1)', maxHeight: '90vh' }}>

        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center text-lg"
              style={{ background: 'rgba(124,58,237,0.2)', border: '1px solid rgba(124,58,237,0.3)' }}>
              📷
            </div>
            <div>
              <h2 className="text-lg font-bold text-white leading-none">Add Camera</h2>
              <p className="text-xs mt-0.5" style={{ color: '#6e7681' }}>Fill in the details below</p>
            </div>
          </div>
          <button onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-lg transition-all"
            style={{ color: '#6e7681', background: 'rgba(255,255,255,0.05)' }}>
            ×
          </button>
        </div>

        {/* Scrollable form body */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 px-6 pb-6 overflow-y-auto">

          {/* Camera Name */}
          <Field label="Camera Name" required>
            <input
              required autoFocus
              className="input"
              placeholder="Main Entrance"
              value={form.name}
              onChange={e => set('name', e.target.value)}
            />
          </Field>

          {/* Location */}
          <Field label="Location">
            <input
              className="input"
              placeholder="e.g. Entrance, Aisle 3, Checkout"
              value={form.location}
              onChange={e => set('location', e.target.value)}
            />
          </Field>

          {/* Camera Type — pill selector */}
          <Field label="Camera Type">
            <div className="flex flex-wrap gap-2">
              {CAM_TYPES.map(t => (
                <button key={t.value} type="button"
                  onClick={() => set('type', t.value)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                  style={{
                    background: form.type === t.value ? 'rgba(124,58,237,0.25)' : 'rgba(255,255,255,0.05)',
                    border: `1px solid ${form.type === t.value ? 'rgba(124,58,237,0.6)' : 'rgba(255,255,255,0.08)'}`,
                    color: form.type === t.value ? '#c4b5fd' : '#8b949e',
                  }}>
                  {t.icon} {t.label}
                </button>
              ))}
            </div>
          </Field>

          {/* Stream URL */}
          {needsUrl && (
            <Field label="Stream URL (RTSP)">
              <input
                className="input font-mono text-xs"
                placeholder={selectedType.placeholder}
                value={form.url}
                onChange={e => set('url', e.target.value)}
              />
              {/* Brand RTSP reference */}
              <button type="button" onClick={() => setShowBrands(v => !v)}
                className="text-xs mt-1" style={{ color: '#7c3aed' }}>
                {showBrands ? '▲ Hide' : '▼ Common RTSP URLs by brand'}
              </button>
              {showBrands && (
                <div className="flex flex-col gap-1 mt-1 p-3 rounded-xl"
                  style={{ background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.06)' }}>
                  {BRAND_URLS.map(r => (
                    <button key={r.brand} type="button"
                      onClick={() => { set('url', r.url.replace('IP', '192.168.1.100')); setShowBrands(false) }}
                      className="flex items-center gap-2 text-left hover:bg-white/5 rounded-lg px-2 py-1 transition-all">
                      <span className="text-xs w-16 flex-shrink-0" style={{ color: '#8b949e' }}>{r.brand}</span>
                      <code className="text-xs truncate" style={{ color: '#a78bfa' }}>{r.url}</code>
                    </button>
                  ))}
                </div>
              )}
            </Field>
          )}

          {/* USB device index */}
          {needsIdx && (
            <Field label="Device Index" hint="0 = first webcam, 1 = second…">
              <input
                type="number" min="0" max="9"
                className="input"
                placeholder="0"
                value={form.url}
                onChange={e => set('url', e.target.value)}
              />
            </Field>
          )}

          {/* Credentials (collapsible) */}
          {needsAuth && (
            <div className="flex gap-3">
              <Field label="Username" className="flex-1">
                <input className="input" placeholder="admin"
                  value={form.username} onChange={e => set('username', e.target.value)} />
              </Field>
              <Field label="Password" className="flex-1">
                <input className="input" type="password" placeholder="••••••"
                  value={form.password} onChange={e => set('password', e.target.value)} />
              </Field>
            </div>
          )}

          {/* Test connection */}
          {!isMock && (
            <div className="rounded-xl p-3 flex items-center gap-3"
              style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
              <button type="button" onClick={handleTest}
                disabled={testState === 'testing'}
                className="px-4 py-2 rounded-lg text-xs font-bold transition-all flex-shrink-0"
                style={{
                  background: testState === 'ok'   ? 'rgba(63,185,80,0.15)'   :
                               testState === 'fail' ? 'rgba(248,81,73,0.12)'   :
                               'rgba(124,58,237,0.2)',
                  border: `1px solid ${
                    testState === 'ok'   ? 'rgba(63,185,80,0.4)'  :
                    testState === 'fail' ? 'rgba(248,81,73,0.35)' :
                    'rgba(124,58,237,0.4)'}`,
                  color: testState === 'ok'   ? '#3fb950' :
                         testState === 'fail' ? '#f85149' : '#a78bfa',
                }}>
                {testState === 'testing' ? <span className="animate-spin inline-block">⟳</span> :
                 testState === 'ok'      ? '✓ Connected' :
                 testState === 'fail'    ? '✗ Failed'    : '⚡ Test Connection'}
              </button>
              <p className="text-xs leading-snug"
                style={{ color: testState === 'ok' ? '#3fb950' : testState === 'fail' ? '#f85149' : '#6e7681' }}>
                {testMsg || 'Optional — verify the camera is reachable before saving.'}
              </p>
            </div>
          )}

          {error && (
            <p className="text-sm px-1" style={{ color: '#f85149' }}>{error}</p>
          )}

          {/* Buttons */}
          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose}
              className="flex-1 py-2.5 rounded-xl text-sm font-medium transition-all"
              style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: '#8b949e' }}>
              Cancel
            </button>
            <button type="submit" disabled={saving}
              className="flex-1 py-2.5 rounded-xl text-sm font-bold text-white transition-all flex items-center justify-center gap-2"
              style={{ background: saving ? '#5b3fa8' : '#7c3aed' }}>
              {saving ? <><span className="animate-spin">⟳</span> Adding…</> : 'Add Camera'}
            </button>
          </div>
        </form>
      </div>

      <style>{`
        .input {
          width: 100%;
          padding: 10px 14px;
          border-radius: 10px;
          font-size: 13px;
          color: #e6edf3;
          outline: none;
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          transition: border-color 0.15s;
        }
        .input:focus { border-color: rgba(124,58,237,0.5); }
        .input::placeholder { color: #484f58; }
      `}</style>
    </div>
  )
}

function Field({ label, required, hint, children, className = '' }) {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label className="text-sm font-medium" style={{ color: '#c9d1d9' }}>
        {label}
        {required && <span className="ml-1" style={{ color: '#7c3aed' }}>*</span>}
        {hint && <span className="ml-2 font-normal text-xs" style={{ color: '#6e7681' }}>{hint}</span>}
      </label>
      {children}
    </div>
  )
}
