import React, { useEffect, useState, useRef, useCallback } from 'react'
import { cameraAPI } from '../../utils/api'
import api from '../../utils/api'

const CAMERA_NAMES = ['Entrance', 'Aisle A', 'Aisle B', 'Aisle C', 'Checkout/Exit']
const LEVEL_COLORS = { NORMAL: '#3fb950', WATCH: '#d29922', HIGH_SUSPICION: '#f85149' }

const STATUS_COLOR = {
  CONNECTED:    'bg-green-500',
  CONNECTING:   'bg-yellow-500 animate-pulse',
  RECONNECTING: 'bg-yellow-400 animate-pulse',
  DISCONNECTED: 'bg-red-500',
  ERROR:        'bg-red-600',
  STOPPED:      'bg-gray-500',
  IDLE:         'bg-gray-500',
}

// ── Simulated-pipeline canvas feed ──────────────────────────────────────────

function CameraFeed({ feed, livePersons = [] }) {
  const canvasRef = useRef(null)
  const persons   = livePersons.filter(p => p.camera_id === feed.camera_id)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width, H = canvas.height

    ctx.fillStyle = '#0d1117'
    ctx.fillRect(0, 0, W, H)

    ctx.strokeStyle = '#21262d'; ctx.lineWidth = 0.5
    for (let x = 0; x < W; x += W / 6) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke() }
    for (let y = 0; y < H; y += H / 4) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke() }
    for (let y = 0; y < H; y += 4)     { ctx.fillStyle = 'rgba(0,0,0,0.08)'; ctx.fillRect(0,y,W,2) }

    ctx.fillStyle = 'rgba(88,166,255,0.08)'
    ctx.font = 'bold 48px monospace'; ctx.textAlign = 'center'
    ctx.fillText(`CAM ${feed.camera_id + 1}`, W / 2, H / 2 + 16)

    persons.forEach(p => {
      if (!p.bbox) return
      const [x1,y1,x2,y2] = p.bbox
      const px=x1*W, py=y1*H, pw=(x2-x1)*W, ph=(y2-y1)*H
      const color = p.is_staff ? '#3b82f6' : (LEVEL_COLORS[p.level] || '#3fb950')
      ctx.strokeStyle = color; ctx.lineWidth = 2
      ctx.strokeRect(px,py,pw,ph)
      const cLen=8; ctx.lineWidth=3
      ;[[px,py],[px+pw,py],[px,py+ph],[px+pw,py+ph]].forEach(([cx,cy],i)=>{
        const dx=i%2===1?-cLen:cLen, dy=i>=2?-cLen:cLen
        ctx.beginPath(); ctx.moveTo(cx,cy); ctx.lineTo(cx+dx,cy)
        ctx.moveTo(cx,cy); ctx.lineTo(cx,cy+dy); ctx.stroke()
      })
      const label = p.is_staff ? 'STAFF' : `${p.session_id} ${p.score?p.score.toFixed(0):0}%`
      ctx.font='bold 11px monospace'
      const tw=ctx.measureText(label).width+8
      ctx.fillStyle='rgba(13,17,23,0.85)'; ctx.fillRect(px,py-18,tw,16)
      ctx.fillStyle=color; ctx.fillText(label,px+4,py-5)
      if (!p.is_staff && p.score) {
        const barW=pw*(Math.min(100,p.score)/100)
        ctx.fillStyle='rgba(0,0,0,0.5)'; ctx.fillRect(px,py+ph-4,pw,4)
        ctx.fillStyle=color;              ctx.fillRect(px,py+ph-4,barW,4)
      }
    })

    ctx.fillStyle='rgba(88,166,255,0.7)'; ctx.font='10px monospace'
    ctx.textAlign='left';  ctx.fillText(new Date().toLocaleTimeString(),6,H-6)
    ctx.textAlign='right'; ctx.fillText(`${persons.length} tracked`,W-6,H-6)
  }, [feed, persons])

  return (
    <div className="camera-feed group">
      <canvas ref={canvasRef} width={320} height={180} className="w-full h-full object-cover"/>
      <div className="camera-label absolute bottom-0 left-0 right-0 px-2 py-1.5 flex justify-between items-center">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 bg-accent-green rounded-full animate-pulse"/>
          <span className="text-xs font-semibold text-white">
            CAM {feed.camera_id+1} — {CAMERA_NAMES[feed.camera_id]||'Camera'}
          </span>
        </div>
        <span className="text-xs text-rbis-400">{persons.length} person{persons.length!==1?'s':''}</span>
      </div>
      {persons.some(p=>p.level==='HIGH_SUSPICION') && (
        <div className="absolute inset-0 border-2 border-red-500 rounded pointer-events-none animate-pulse"/>
      )}
    </div>
  )
}

// ── Real-camera status card ─────────────────────────────────────────────────

function RealCameraCard({ cam, onRemove, onRestart }) {
  const statusDot = STATUS_COLOR[cam.status] || 'bg-gray-500'
  const isLive    = cam.status === 'CONNECTED'

  return (
    <div className="card p-3 flex flex-col gap-2 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDot}`}/>
          <span className="text-sm font-semibold text-rbis-100 truncate">{cam.camera_id}</span>
          <span className="badge-outline text-xs px-1">{cam.cam_type}</span>
        </div>
        <div className="flex gap-1 flex-shrink-0">
          <button
            onClick={() => onRestart(cam.camera_id)}
            title="Restart stream"
            className="btn-ghost text-xs px-2 py-0.5"
          >↺</button>
          <button
            onClick={() => onRemove(cam.camera_id)}
            title="Remove camera"
            className="btn-ghost text-xs px-2 py-0.5 text-red-400 hover:text-red-300"
          >✕</button>
        </div>
      </div>
      <div className="flex justify-between text-xs text-rbis-400">
        <span>{cam.resolution?`${cam.resolution[0]}×${cam.resolution[1]}`:'—'}</span>
        <span>{isLive ? `${cam.fps_actual} fps · ${cam.frames_total} frames` : cam.status}</span>
      </div>
      {isLive && (
        <img
          src={`${import.meta.env.VITE_API_URL||''}/api/cameras/${cam.camera_id}/snapshot?quality=50&t=${Date.now()}`}
          alt={cam.camera_id}
          className="w-full rounded border border-rbis-700 object-cover"
          style={{ height: 90 }}
          onError={e => { e.target.style.display='none' }}
        />
      )}
    </div>
  )
}

// ── Add-camera modal ────────────────────────────────────────────────────────

function AddCameraModal({ onAdd, onClose }) {
  const [form, setForm] = useState({
    camera_id:'', cam_type:'MOCK', source:'mock://0',
    width:1280, height:720, fps:15, username:'', password:''
  })
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault(); setError('')
    try {
      await api.post('/api/cameras', form)
      onAdd()
      onClose()
    } catch(err) {
      setError(err.response?.data?.detail || 'Failed to add camera')
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="card p-6 w-full max-w-md">
        <h3 className="text-lg font-bold mb-4">Add Camera</h3>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="flex gap-2">
            <input required className="input flex-1" placeholder="camera_id" value={form.camera_id}
              onChange={e=>setForm({...form,camera_id:e.target.value})}/>
            <select className="input w-28" value={form.cam_type}
              onChange={e=>setForm({...form,cam_type:e.target.value})}>
              {['MOCK','USB','RTSP','HTTP','ONVIF','FILE'].map(t=><option key={t}>{t}</option>)}
            </select>
          </div>
          <input required className="input" placeholder="source  (e.g. 0 / rtsp://...)" value={form.source}
            onChange={e=>setForm({...form,source:e.target.value})}/>
          <div className="flex gap-2">
            <input className="input flex-1" type="number" placeholder="width"  value={form.width}
              onChange={e=>setForm({...form,width:+e.target.value})}/>
            <input className="input flex-1" type="number" placeholder="height" value={form.height}
              onChange={e=>setForm({...form,height:+e.target.value})}/>
            <input className="input w-20"   type="number" placeholder="fps"    value={form.fps}
              onChange={e=>setForm({...form,fps:+e.target.value})}/>
          </div>
          <div className="flex gap-2">
            <input className="input flex-1" placeholder="username (optional)" value={form.username}
              onChange={e=>setForm({...form,username:e.target.value})}/>
            <input className="input flex-1" type="password" placeholder="password" value={form.password}
              onChange={e=>setForm({...form,password:e.target.value})}/>
          </div>
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <div className="flex gap-2 justify-end pt-1">
            <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-primary">Add Camera</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Main CameraGrid ─────────────────────────────────────────────────────────

export default function CameraGrid({ livePersons = [], cameraFrame }) {
  const [feeds, setFeeds]         = useState(() =>
    Array.from({length:5},(_,i)=>({camera_id:i,persons:[],person_count:0}))
  )
  const [realCams, setRealCams]   = useState([])
  const [showAdd,  setShowAdd]    = useState(false)
  const [showReal, setShowReal]   = useState(false)

  const refreshFeeds = useCallback(async () => {
    try {
      const res = await cameraAPI.feeds()
      if (res.data?.feeds)       setFeeds(res.data.feeds)
      if (res.data?.real_cameras) setRealCams(res.data.real_cameras)
    } catch (_) {}
  }, [])

  const refreshReal = useCallback(async () => {
    try {
      const res = await api.get('/api/cameras')
      setRealCams(res.data?.cameras || [])
    } catch (_) {}
  }, [])

  useEffect(() => {
    refreshFeeds()
    const t = setInterval(refreshFeeds, 3000)
    return () => clearInterval(t)
  }, [refreshFeeds])

  // Auto-refresh real-camera snapshots every 2 s when panel is open
  useEffect(() => {
    if (!showReal) return
    refreshReal()
    const t = setInterval(refreshReal, 2000)
    return () => clearInterval(t)
  }, [showReal, refreshReal])

  const handleRemove = async (id) => {
    try { await api.delete(`/api/cameras/${id}`); refreshReal() } catch(_) {}
  }
  const handleRestart = async (id) => {
    try { await api.post(`/api/cameras/${id}/restart`); refreshReal() } catch(_) {}
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Simulated pipeline grid */}
      <div className="grid grid-cols-3 gap-2">
        {feeds.map(feed => (
          <CameraFeed key={feed.camera_id} feed={feed} livePersons={livePersons}/>
        ))}
      </div>

      {/* Real cameras panel toggle */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => setShowReal(v => !v)}
          className="btn-ghost text-xs flex items-center gap-1.5"
        >
          <span className={`w-2 h-2 rounded-full ${realCams.length > 0 ? 'bg-green-500' : 'bg-gray-500'}`}/>
          Real Cameras ({realCams.length})
          <span className="ml-1 text-rbis-500">{showReal ? '▲' : '▼'}</span>
        </button>
        {showReal && (
          <button onClick={() => setShowAdd(true)} className="btn-primary text-xs px-3 py-1">
            + Add Camera
          </button>
        )}
      </div>

      {showReal && (
        <div className="grid grid-cols-2 gap-2">
          {realCams.length === 0 ? (
            <p className="text-rbis-500 text-sm col-span-2 text-center py-4">
              No cameras configured. Add one or edit cameras.yaml on the server.
            </p>
          ) : (
            realCams.map(cam => (
              <RealCameraCard
                key={cam.camera_id}
                cam={cam}
                onRemove={handleRemove}
                onRestart={handleRestart}
              />
            ))
          )}
        </div>
      )}

      {showAdd && (
        <AddCameraModal onAdd={refreshReal} onClose={() => setShowAdd(false)}/>
      )}
    </div>
  )
}
