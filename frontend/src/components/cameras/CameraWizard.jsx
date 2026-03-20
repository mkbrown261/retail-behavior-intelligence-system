import React, { useState, useEffect, useRef } from 'react'
import { cameraAPI } from '../../utils/api'
import api from '../../utils/api'

// ── Network scanner — pings common RTSP ports on the LAN ────────────────────

const COMMON_RTSP_PORTS = [554, 8554, 10554]
const ONVIF_PORT = 80

function CamTypeIcon({ type }) {
  const icons = { USB: '🔌', RTSP: '📡', HTTP: '🌐', ONVIF: '🔍', FILE: '📁', MOCK: '🎭' }
  return <span>{icons[type] || '📷'}</span>
}

// ── Step indicator ───────────────────────────────────────────────────────────

function Steps({ current }) {
  const steps = ['Choose Type', 'Configure', 'Test & Add']
  return (
    <div className="flex items-center gap-0 mb-6">
      {steps.map((s, i) => (
        <React.Fragment key={i}>
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium transition-all
            ${i === current ? 'bg-accent-blue text-white' :
              i < current  ? 'bg-green-600 text-white' :
                             'bg-rbis-700 text-rbis-400'}`}>
            <span className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold
              border border-current">
              {i < current ? '✓' : i + 1}
            </span>
            {s}
          </div>
          {i < steps.length - 1 && (
            <div className={`h-px w-6 ${i < current ? 'bg-green-500' : 'bg-rbis-700'}`} />
          )}
        </React.Fragment>
      ))}
    </div>
  )
}

// ── Camera type selector ─────────────────────────────────────────────────────

const CAM_TYPES = [
  {
    type: 'USB',
    icon: '🔌',
    title: 'USB / Webcam',
    desc: 'Plugged directly into this computer',
    fields: [{ key: 'source', label: 'Device index', placeholder: '0', hint: '0 = first webcam, 1 = second, etc.' }],
  },
  {
    type: 'RTSP',
    icon: '📡',
    title: 'IP Camera (RTSP)',
    desc: 'Security camera on your WiFi/LAN',
    fields: [
      { key: 'source',   label: 'RTSP URL',  placeholder: 'rtsp://192.168.1.x:554/stream1' },
      { key: 'username', label: 'Username',   placeholder: 'admin (leave blank if none)' },
      { key: 'password', label: 'Password',   placeholder: '••••••', type: 'password' },
    ],
  },
  {
    type: 'ONVIF',
    icon: '🔍',
    title: 'ONVIF Camera',
    desc: 'Auto-discover cameras on your network',
    action: 'discover',
    fields: [
      { key: 'username', label: 'Username', placeholder: 'admin (leave blank if none)' },
      { key: 'password', label: 'Password', placeholder: '••••••', type: 'password' },
    ],
  },
  {
    type: 'HTTP',
    icon: '🌐',
    title: 'MJPEG Stream',
    desc: 'HTTP camera or webcam stream URL',
    fields: [{ key: 'source', label: 'Stream URL', placeholder: 'http://192.168.1.x:8080/video' }],
  },
  {
    type: 'FILE',
    icon: '📁',
    title: 'Video File',
    desc: 'Pre-recorded .mp4 / .avi for testing',
    fields: [{ key: 'source', label: 'File path', placeholder: '/path/to/video.mp4' }],
  },
  {
    type: 'MOCK',
    icon: '🎭',
    title: 'Demo / Mock',
    desc: 'Synthetic test feed — no hardware needed',
    fields: [],
  },
]

// ── Main wizard ──────────────────────────────────────────────────────────────

export default function CameraWizard({ onDone }) {
  const [step, setStep]               = useState(0)
  const [selectedType, setType]       = useState(null)
  const [form, setForm]               = useState({})
  const [camId, setCamId]             = useState('')
  const [error, setError]             = useState('')
  const [testing, setTesting]         = useState(false)
  const [testResult, setTestResult]   = useState(null)  // null | 'ok' | 'fail'
  const [discovering, setDiscovering] = useState(false)
  const [discovered, setDiscovered]   = useState([])
  const [existing, setExisting]       = useState([])
  const [networkInfo, setNetworkInfo] = useState(null)

  useEffect(() => {
    // Load current cameras and network info
    cameraAPI.list().then(r => setExisting(r.data?.cameras || [])).catch(() => {})
    api.get('/api/network-info').then(r => setNetworkInfo(r.data)).catch(() => {})
  }, [])

  // Auto-generate a camera ID from the type
  useEffect(() => {
    if (!selectedType) return
    const base = selectedType.type.toLowerCase()
    const n = existing.filter(c => c.cam_type === selectedType.type).length + 1
    setCamId(`${base}_cam_${n}`)
  }, [selectedType])

  const typeDef = selectedType

  // ── Step 0: choose type ────────────────────────────────────────────────────

  if (step === 0) return (
    <div className="flex flex-col gap-4">
      <Steps current={0} />
      <p className="text-rbis-400 text-sm">What type of camera do you want to connect?</p>
      <div className="grid grid-cols-2 gap-3">
        {CAM_TYPES.map(ct => (
          <button
            key={ct.type}
            onClick={() => { setType(ct); setForm({}); setError(''); setStep(1) }}
            className="card p-4 text-left hover:border-accent-blue transition-all flex flex-col gap-1 cursor-pointer"
          >
            <div className="text-2xl">{ct.icon}</div>
            <div className="font-semibold text-rbis-100">{ct.title}</div>
            <div className="text-xs text-rbis-400">{ct.desc}</div>
          </button>
        ))}
      </div>
      {existing.length > 0 && (
        <div className="mt-2">
          <p className="text-rbis-400 text-xs mb-2">Already connected ({existing.length})</p>
          <div className="flex flex-wrap gap-2">
            {existing.map(c => (
              <span key={c.camera_id} className="badge-outline text-xs flex items-center gap-1">
                <CamTypeIcon type={c.cam_type} /> {c.camera_id}
                <span className={`w-1.5 h-1.5 rounded-full ml-1 ${c.status === 'CONNECTED' ? 'bg-green-500' : 'bg-red-500'}`} />
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )

  // ── Step 1: configure ──────────────────────────────────────────────────────

  const handleDiscover = async () => {
    setDiscovering(true); setDiscovered([]); setError('')
    try {
      const res = await cameraAPI.discoverOnvif(form.username || '', form.password || '')
      setDiscovered(res.data?.cameras || [])
      if (res.data?.cameras?.length === 0) setError('No ONVIF cameras found on the network. Try entering RTSP URL manually.')
    } catch (e) {
      setError('Discovery failed: ' + (e.response?.data?.detail || e.message))
    }
    setDiscovering(false)
  }

  const handleAddDiscovered = async (cam) => {
    setError('')
    try {
      await cameraAPI.add({ ...cam, fps: 15 })
      cameraAPI.list().then(r => setExisting(r.data?.cameras || [])).catch(() => {})
      setDiscovered(d => d.filter(c => c.camera_id !== cam.camera_id))
      if (onDone) onDone()
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to add')
    }
  }

  const handleNext = () => {
    setError('')
    if (!camId.trim()) { setError('Camera ID is required'); return }
    if (typeDef.fields.find(f => f.key === 'source') && !form.source?.toString().trim()) {
      setError('Source / URL is required'); return
    }
    setStep(2)
  }

  if (step === 1) return (
    <div className="flex flex-col gap-4">
      <Steps current={1} />
      <button onClick={() => setStep(0)} className="btn-ghost text-xs self-start">← Back</button>

      <div className="flex items-center gap-2 text-lg font-bold">
        <span>{typeDef.icon}</span> {typeDef.title}
      </div>

      {/* Camera ID */}
      <div>
        <label className="text-xs text-rbis-400 mb-1 block">Camera ID (unique name)</label>
        <input
          className="input w-full"
          value={camId}
          onChange={e => setCamId(e.target.value)}
          placeholder="e.g. entrance_cam"
        />
      </div>

      {/* Type-specific fields */}
      {typeDef.fields.map(f => (
        <div key={f.key}>
          <label className="text-xs text-rbis-400 mb-1 block">{f.label}</label>
          <input
            className="input w-full"
            type={f.type || 'text'}
            placeholder={f.placeholder}
            value={form[f.key] || ''}
            onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
          />
          {f.hint && <p className="text-xs text-rbis-500 mt-0.5">{f.hint}</p>}
        </div>
      ))}

      {/* Resolution / FPS */}
      <div className="flex gap-2">
        <div className="flex-1">
          <label className="text-xs text-rbis-400 mb-1 block">Width</label>
          <input className="input w-full" type="number" value={form.width || 1280}
            onChange={e => setForm(p => ({ ...p, width: +e.target.value }))} />
        </div>
        <div className="flex-1">
          <label className="text-xs text-rbis-400 mb-1 block">Height</label>
          <input className="input w-full" type="number" value={form.height || 720}
            onChange={e => setForm(p => ({ ...p, height: +e.target.value }))} />
        </div>
        <div className="w-20">
          <label className="text-xs text-rbis-400 mb-1 block">FPS</label>
          <input className="input w-full" type="number" value={form.fps || 15}
            onChange={e => setForm(p => ({ ...p, fps: +e.target.value }))} />
        </div>
      </div>

      {/* ONVIF: discover button + results */}
      {typeDef.action === 'discover' && (
        <div className="flex flex-col gap-2">
          <button onClick={handleDiscover} disabled={discovering}
            className="btn-primary flex items-center gap-2 justify-center">
            {discovering ? <span className="animate-spin">⟳</span> : '🔍'}
            {discovering ? 'Scanning network…' : 'Scan for ONVIF cameras'}
          </button>
          {discovered.length > 0 && (
            <div className="flex flex-col gap-2 mt-1">
              <p className="text-green-400 text-sm">Found {discovered.length} camera(s):</p>
              {discovered.map(cam => (
                <div key={cam.camera_id} className="card p-3 flex justify-between items-center">
                  <div>
                    <p className="text-sm font-semibold">{cam.camera_id}</p>
                    <p className="text-xs text-rbis-400">{cam.source}</p>
                  </div>
                  <button onClick={() => handleAddDiscovered(cam)} className="btn-primary text-xs px-3">
                    Add
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {typeDef.action !== 'discover' && (
        <button onClick={handleNext} className="btn-primary">
          Next → Test Connection
        </button>
      )}
    </div>
  )

  // ── Step 2: test & add ─────────────────────────────────────────────────────

  const handleTest = async () => {
    setTesting(true); setTestResult(null); setError('')
    // For MOCK type we skip actual test
    if (typeDef.type === 'MOCK') { setTestResult('ok'); setTesting(false); return }
    try {
      // Try adding temporarily, then check status
      const payload = {
        camera_id: `_test_${Date.now()}`,
        cam_type:  typeDef.type,
        source:    typeDef.type === 'USB' ? parseInt(form.source || 0) : (form.source || ''),
        width:     form.width  || 1280,
        height:    form.height || 720,
        fps:       form.fps    || 15,
        username:  form.username || '',
        password:  form.password || '',
      }
      const addRes = await cameraAPI.add(payload)
      const testId = addRes.data?.camera?.camera_id
      // Wait 2s then check status
      await new Promise(r => setTimeout(r, 2000))
      const info = await cameraAPI.get(testId)
      const status = info.data?.status
      // Clean up test camera
      await cameraAPI.remove(testId).catch(() => {})
      setTestResult(status === 'CONNECTED' ? 'ok' : 'fail')
      if (status !== 'CONNECTED') setError(`Camera opened but status is "${status}". Check URL/credentials.`)
    } catch (e) {
      setTestResult('fail')
      setError('Connection failed: ' + (e.response?.data?.detail || e.message))
    }
    setTesting(false)
  }

  const handleAdd = async () => {
    setError('')
    try {
      await cameraAPI.add({
        camera_id: camId,
        cam_type:  typeDef.type,
        source:    typeDef.type === 'USB' ? parseInt(form.source || 0) : (form.source || 'mock://0'),
        width:     form.width    || 1280,
        height:    form.height   || 720,
        fps:       form.fps      || 15,
        username:  form.username || '',
        password:  form.password || '',
      })
      if (onDone) onDone()
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to add camera')
    }
  }

  if (step === 2) return (
    <div className="flex flex-col gap-4">
      <Steps current={2} />
      <button onClick={() => setStep(1)} className="btn-ghost text-xs self-start">← Back</button>

      {/* Summary */}
      <div className="card p-4 flex flex-col gap-1">
        <div className="flex items-center gap-2 font-semibold">
          <CamTypeIcon type={typeDef.type} /> {camId}
          <span className="badge-outline text-xs">{typeDef.type}</span>
        </div>
        {form.source && <p className="text-xs text-rbis-400">{form.source}</p>}
        <p className="text-xs text-rbis-400">{form.width || 1280}×{form.height || 720} @ {form.fps || 15} fps</p>
      </div>

      {/* Test button */}
      {testResult === null && (
        <button onClick={handleTest} disabled={testing}
          className="btn-primary flex items-center gap-2 justify-center">
          {testing ? <><span className="animate-spin">⟳</span> Testing…</> : '🔌 Test Connection'}
        </button>
      )}

      {testResult === 'ok' && (
        <div className="card p-3 border border-green-600 bg-green-900/20 flex items-center gap-2">
          <span className="text-green-400 text-lg">✓</span>
          <span className="text-green-300 text-sm font-medium">Connection successful!</span>
        </div>
      )}

      {testResult === 'fail' && (
        <div className="card p-3 border border-red-600 bg-red-900/20 flex items-center gap-2">
          <span className="text-red-400 text-lg">✗</span>
          <span className="text-red-300 text-sm">Connection failed — check settings above</span>
        </div>
      )}

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {/* Add button — shown after test passes, or skip test for MOCK */}
      {(testResult === 'ok' || typeDef.type === 'MOCK') && (
        <button onClick={handleAdd} className="btn-primary text-base py-2">
          ✅ Add Camera to System
        </button>
      )}

      {testResult === 'fail' && (
        <button onClick={() => setStep(1)} className="btn-ghost">
          ← Edit Settings
        </button>
      )}

      {testResult === null && typeDef.type !== 'MOCK' && (
        <button onClick={handleAdd} className="btn-ghost text-sm">
          Skip test & add anyway
        </button>
      )}
    </div>
  )

  return null
}
