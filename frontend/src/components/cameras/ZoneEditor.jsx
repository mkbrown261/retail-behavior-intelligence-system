import React, { useEffect, useRef, useState, useCallback } from 'react'
import { cameraAPI } from '../../utils/api'

const BACKEND = import.meta.env.VITE_API_URL || ''

// The backend's ZoneConfig is threshold-based (x-ranges + a y-max), not
// arbitrary polygons — so this editor exposes draggable lines that match
// what the model actually supports, rather than a free-form polygon tool
// that would promise precision the underlying zones don't have.
const LINES = [
  { key: 'shelf_x0',     label: 'Shelf area — left edge',   axis: 'x', color: '#d29922', path: ['shelf_zone_x', 0] },
  { key: 'shelf_x1',     label: 'Shelf area — right edge',  axis: 'x', color: '#d29922', path: ['shelf_zone_x', 1] },
  { key: 'shelf_y',      label: 'Shelf area — bottom edge', axis: 'y', color: '#d29922', path: ['shelf_zone_y_max'] },
  { key: 'register_x0',  label: 'Register — left edge',     axis: 'x', color: '#bc8cff', path: ['register_zone_x', 0] },
  { key: 'register_x1',  label: 'Register — right edge',    axis: 'x', color: '#bc8cff', path: ['register_zone_x', 1] },
  { key: 'exit_x',       label: 'Exit boundary',            axis: 'x', color: '#f85149', path: ['exit_zone_x'] },
]

function getValue(zones, path) {
  return path.length === 2 ? zones[path[0]][path[1]] : zones[path[0]]
}
function setValue(zones, path, value) {
  const next = { ...zones, shelf_zone_x: [...zones.shelf_zone_x], register_zone_x: [...zones.register_zone_x] }
  if (path.length === 2) next[path[0]][path[1]] = Math.round(value * 1000) / 1000
  else next[path[0]] = Math.round(value * 1000) / 1000
  return next
}

export default function ZoneEditor({ camera, onClose }) {
  const [zones, setZones] = useState(null)
  const [dragging, setDragging] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const imgWrapRef = useRef(null)

  useEffect(() => {
    cameraAPI.getZones(camera.camera_id)
      .then(res => {
        const { camera_id, is_default, ...z } = res.data
        setZones(z)
      })
      .catch(() => setZones(null))
  }, [camera.camera_id])

  const handleMouseDown = (key) => (e) => {
    e.preventDefault()
    setDragging(key)
  }

  const handleMouseMove = useCallback((e) => {
    if (!dragging || !imgWrapRef.current) return
    const rect = imgWrapRef.current.getBoundingClientRect()
    const line = LINES.find(l => l.key === dragging)
    const frac = line.axis === 'x'
      ? (e.clientX - rect.left) / rect.width
      : (e.clientY - rect.top) / rect.height
    const clamped = Math.max(0, Math.min(1, frac))
    setZones(prev => setValue(prev, line.path, clamped))
  }, [dragging])

  const handleMouseUp = useCallback(() => setDragging(null), [])

  useEffect(() => {
    if (!dragging) return
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [dragging, handleMouseMove, handleMouseUp])

  const save = async () => {
    setSaving(true)
    try {
      await cameraAPI.saveZones(camera.camera_id, zones)
      setSaved(true)
    } catch (e) {
      console.error('save zones failed', e)
    }
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-rbis-800 border border-rbis-600 rounded-lg w-full max-w-3xl max-h-[90vh] flex flex-col shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-rbis-600">
          <div>
            <h3 className="font-bold text-lg">Zone Calibration — {camera.camera_id}</h3>
            <p className="text-xs text-rbis-400 mt-0.5">
              Drag each line to match your camera's actual layout. These thresholds drive PICK_ITEM zone gating, BYPASS_REGISTER, and EXIT_STORE.
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-rbis-600 rounded text-rbis-400 text-xl leading-none">✕</button>
        </div>

        <div className="p-4 flex-1 overflow-y-auto">
          {!zones ? (
            <p className="text-rbis-400 text-sm">Loading current zones…</p>
          ) : (
            <>
              <div
                ref={imgWrapRef}
                className="relative w-full rounded border border-rbis-700 overflow-hidden select-none"
                style={{ height: 360, cursor: dragging ? 'grabbing' : 'default' }}
              >
                <img
                  src={`${BACKEND}/api/cameras/${camera.camera_id}/mjpeg`}
                  alt={camera.camera_id}
                  className="w-full h-full object-cover pointer-events-none"
                  draggable={false}
                />
                {LINES.map(line => {
                  const value = getValue(zones, line.path)
                  const style = line.axis === 'x'
                    ? { left: `${value * 100}%`, top: 0, bottom: 0, width: 2, cursor: 'ew-resize' }
                    : { top: `${value * 100}%`, left: 0, right: 0, height: 2, cursor: 'ns-resize' }
                  return (
                    <div
                      key={line.key}
                      onMouseDown={handleMouseDown(line.key)}
                      className="absolute"
                      style={{ ...style, background: line.color, boxShadow: `0 0 4px ${line.color}` }}
                    >
                      <span
                        className="absolute px-1 text-[10px] font-mono font-bold whitespace-nowrap"
                        style={{
                          background: 'rgba(13,17,23,0.9)', color: line.color,
                          ...(line.axis === 'x' ? { top: 4, left: 4 } : { left: 4, top: -8 }),
                        }}
                      >
                        {line.label}
                      </span>
                    </div>
                  )
                })}
              </div>

              <div className="grid grid-cols-2 gap-2 mt-4 text-xs">
                {LINES.map(line => (
                  <div key={line.key} className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: line.color }} />
                    <span className="text-rbis-400 flex-1">{line.label}</span>
                    <span className="font-mono text-rbis-200">{getValue(zones, line.path).toFixed(2)}</span>
                  </div>
                ))}
              </div>

              {saved && (
                <p className="text-xs text-green-400 mt-3">
                  Saved. This takes effect on the next backend restart (the running AI processor doesn't hot-reload zones).
                </p>
              )}
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 p-4 border-t border-rbis-600">
          <button onClick={onClose} className="btn-ghost">Close</button>
          <button onClick={save} disabled={!zones || saving} className="btn-primary">
            {saving ? 'Saving…' : 'Save Calibration'}
          </button>
        </div>
      </div>
    </div>
  )
}
