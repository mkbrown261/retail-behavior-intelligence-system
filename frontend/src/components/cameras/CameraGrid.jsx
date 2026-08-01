import React, { useEffect, useState, useRef, useCallback } from 'react'
import { cameraAPI } from '../../utils/api'

const BACKEND = import.meta.env.VITE_API_URL || ''
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

// COCO keypoint indices (yolov8-pose): 5/6 shoulders, 7/8 elbows, 9/10 wrists, 11/12 hips
const SKELETON_EDGES = [[5,7],[7,9],[6,8],[8,10],[5,6],[5,11],[6,12],[11,12]]
const WRIST_INDICES  = [9, 10]
const KP_CONF_MIN     = 0.3

// ── Pose skeleton overlay — visible proof the model is tracking hands, not
// just a body box. Draws shoulder→elbow→wrist limbs with wrists highlighted
// as large dots, from live keypoints broadcast every processed frame. ──────

function PoseSkeletonOverlay({ poses, imgSize }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !imgSize.w) return
    canvas.width = imgSize.w
    canvas.height = imgSize.h
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, imgSize.w, imgSize.h)

    if (!poses || poses.length === 0) return

    for (const person of poses) {
      const kp = person.keypoints
      if (!kp) continue
      const pt = i => (kp[i] && kp[i][2] >= KP_CONF_MIN)
        ? [kp[i][0] * imgSize.w, kp[i][1] * imgSize.h]
        : null

      // Limbs
      ctx.strokeStyle = '#58a6ff'
      ctx.lineWidth = 2
      for (const [a, b] of SKELETON_EDGES) {
        const pa = pt(a), pb = pt(b)
        if (pa && pb) {
          ctx.beginPath()
          ctx.moveTo(pa[0], pa[1])
          ctx.lineTo(pb[0], pb[1])
          ctx.stroke()
        }
      }

      // Joints (small)
      ctx.fillStyle = '#58a6ff'
      for (let i = 5; i <= 12; i++) {
        const p = pt(i)
        if (p) {
          ctx.beginPath()
          ctx.arc(p[0], p[1], 3, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      // Wrists — large highlighted dots, the whole point of this overlay
      for (const idx of WRIST_INDICES) {
        const p = pt(idx)
        if (p) {
          ctx.fillStyle = '#3fb950'
          ctx.beginPath()
          ctx.arc(p[0], p[1], 7, 0, Math.PI * 2)
          ctx.fill()
          ctx.strokeStyle = '#0d1117'
          ctx.lineWidth = 1.5
          ctx.stroke()
        }
      }
    }
  }, [poses, imgSize])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full pointer-events-none"
    />
  )
}

// ── Real camera card: live snapshot + bbox + pose skeleton overlay ──────────

function RealCameraCard({ cam, livePersons, poses, onRemove, onRestart }) {
  const statusDot = STATUS_COLOR[cam.status] || 'bg-gray-500'
  const isLive    = cam.status === 'CONNECTED'
  const imgRef    = useRef(null)
  const [imgSize, setImgSize] = useState({ w: 0, h: 0 })

  const persons = livePersons.filter(p => p.camera_id === cam.camera_id)

  // Measure the rendered image box on mount/resize — MJPEG multipart streams
  // don't reliably re-fire onLoad per frame, but the box itself is CSS-sized
  // (fixed height, w-full) so it's stable regardless of stream content.
  useEffect(() => {
    if (!isLive) return
    const measure = () => {
      if (imgRef.current) {
        setImgSize({ w: imgRef.current.clientWidth, h: imgRef.current.clientHeight })
      }
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [isLive])

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
        <span>{persons.length} person{persons.length!==1?'s':''}</span>
      </div>
      {isLive && (
        <div className="relative w-full rounded border border-rbis-700 overflow-hidden" style={{ height: 220 }}>
          <img
            ref={imgRef}
            src={`${BACKEND}/api/cameras/${cam.camera_id}/mjpeg`}
            alt={cam.camera_id}
            className="w-full h-full object-cover"
            onLoad={e => setImgSize({ w: e.target.clientWidth, h: e.target.clientHeight })}
            onError={e => { e.target.style.display='none' }}
          />
          <PoseSkeletonOverlay poses={poses} imgSize={imgSize} />
          {imgSize.w > 0 && persons.map(p => {
            if (!p.bbox) return null
            const [x1,y1,x2,y2] = p.bbox
            const left = x1 * imgSize.w, top = y1 * imgSize.h
            const w = (x2-x1) * imgSize.w, h = (y2-y1) * imgSize.h
            const color = p.is_staff ? '#3b82f6' : (LEVEL_COLORS[p.level] || '#3fb950')
            return (
              <div
                key={p.session_id}
                className="absolute pointer-events-none"
                style={{ left, top, width: w, height: h, border: `2px solid ${color}` }}
              >
                <span
                  className="absolute -top-5 left-0 px-1 text-[10px] font-mono font-bold whitespace-nowrap"
                  style={{ background: 'rgba(13,17,23,0.85)', color }}
                >
                  {p.is_staff ? 'STAFF' : `${p.session_id} ${p.score ? Math.round(p.score) : 0}%`}
                </span>
              </div>
            )
          })}
        </div>
      )}
      {persons.some(p=>p.level==='HIGH_SUSPICION') && (
        <div className="absolute inset-0 border-2 border-red-500 rounded pointer-events-none animate-pulse"/>
      )}
    </div>
  )
}

// ── Add-camera modal ────────────────────────────────────────────────────────

function AddCameraModal({ onAdd, onClose }) {
  const [form, setForm] = useState({
    camera_id:'', cam_type:'USB', source:'0',
    width:1280, height:720, fps:15, username:'', password:''
  })
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault(); setError('')
    try {
      await cameraAPI.add(form)
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
              {['USB','RTSP','HTTP','ONVIF','FILE'].map(t=><option key={t}>{t}</option>)}
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

export default function CameraGrid({ livePersons = [], posesByCamera = {} }) {
  const [realCams, setRealCams] = useState([])
  const [showAdd,  setShowAdd]  = useState(false)

  const refreshReal = useCallback(async () => {
    try {
      const res = await cameraAPI.list()
      setRealCams(res.data?.cameras || [])
    } catch (_) {}
  }, [])

  useEffect(() => {
    refreshReal()
    const t = setInterval(refreshReal, 2000)
    return () => clearInterval(t)
  }, [refreshReal])

  const handleRemove = async (id) => {
    try { await cameraAPI.remove(id); refreshReal() } catch(_) {}
  }
  const handleRestart = async (id) => {
    try { await cameraAPI.restart(id); refreshReal() } catch(_) {}
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-rbis-200 uppercase tracking-wider flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${realCams.length > 0 ? 'bg-green-500' : 'bg-gray-500'}`}/>
          Cameras ({realCams.length})
        </span>
        <button onClick={() => setShowAdd(true)} className="btn-primary text-xs px-3 py-1">
          + Add Camera
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {realCams.length === 0 ? (
          <p className="text-rbis-500 text-sm col-span-2 text-center py-4">
            No cameras configured. Add one above or edit cameras.yaml on the server.
          </p>
        ) : (
          realCams.map(cam => (
            <RealCameraCard
              key={cam.camera_id}
              cam={cam}
              livePersons={livePersons}
              poses={posesByCamera[cam.camera_id] || []}
              onRemove={handleRemove}
              onRestart={handleRestart}
            />
          ))
        )}
      </div>

      {showAdd && (
        <AddCameraModal onAdd={refreshReal} onClose={() => setShowAdd(false)}/>
      )}
    </div>
  )
}
