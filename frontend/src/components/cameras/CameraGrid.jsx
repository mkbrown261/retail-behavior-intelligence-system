import React, { useEffect, useState, useRef } from 'react'
import { cameraAPI } from '../../utils/api'

const CAMERA_NAMES = ['Entrance', 'Aisle A', 'Aisle B', 'Aisle C', 'Checkout/Exit']
const LEVEL_COLORS = { NORMAL: '#3fb950', WATCH: '#d29922', HIGH_SUSPICION: '#f85149' }

function CameraFeed({ feed, livePersons = [] }) {
  const canvasRef = useRef(null)
  const persons = livePersons.filter(p => p.camera_id === feed.camera_id)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width
    const H = canvas.height

    // Background
    ctx.fillStyle = '#0d1117'
    ctx.fillRect(0, 0, W, H)

    // Grid lines (simulated store layout)
    ctx.strokeStyle = '#21262d'
    ctx.lineWidth = 0.5
    for (let x = 0; x < W; x += W / 6) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke()
    }
    for (let y = 0; y < H; y += H / 4) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke()
    }

    // Scanline effect
    for (let y = 0; y < H; y += 4) {
      ctx.fillStyle = 'rgba(0,0,0,0.08)'
      ctx.fillRect(0, y, W, 2)
    }

    // Camera watermark
    ctx.fillStyle = 'rgba(88,166,255,0.08)'
    ctx.font = 'bold 48px monospace'
    ctx.textAlign = 'center'
    ctx.fillText(`CAM ${feed.camera_id + 1}`, W / 2, H / 2 + 16)

    // Draw persons
    persons.forEach(p => {
      if (!p.bbox) return
      const [x1, y1, x2, y2] = p.bbox
      const px = x1 * W, py = y1 * H
      const pw = (x2 - x1) * W, ph = (y2 - y1) * H

      const color = p.is_staff ? '#3b82f6' : (LEVEL_COLORS[p.level] || '#3fb950')

      // Bounding box
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.strokeRect(px, py, pw, ph)

      // Corner accents
      const cLen = 8
      ctx.lineWidth = 3
      ;[[px,py],[px+pw,py],[px,py+ph],[px+pw,py+ph]].forEach(([cx,cy], i) => {
        const dx = i % 2 === 1 ? -cLen : cLen
        const dy = i >= 2    ? -cLen : cLen
        ctx.beginPath()
        ctx.moveTo(cx, cy); ctx.lineTo(cx + dx, cy)
        ctx.moveTo(cx, cy); ctx.lineTo(cx, cy + dy)
        ctx.stroke()
      })

      // Label background
      const label = p.is_staff ? `STAFF` : `${p.session_id} ${p.score ? p.score.toFixed(0) : 0}%`
      ctx.font = 'bold 11px monospace'
      const tw = ctx.measureText(label).width + 8
      ctx.fillStyle = 'rgba(13,17,23,0.85)'
      ctx.fillRect(px, py - 18, tw, 16)
      ctx.fillStyle = color
      ctx.fillText(label, px + 4, py - 5)

      // Score bar inside box
      if (!p.is_staff && p.score) {
        const barW = pw * (Math.min(100, p.score) / 100)
        ctx.fillStyle = 'rgba(0,0,0,0.5)'
        ctx.fillRect(px, py + ph - 4, pw, 4)
        ctx.fillStyle = color
        ctx.fillRect(px, py + ph - 4, barW, 4)
      }
    })

    // Timestamp
    ctx.fillStyle = 'rgba(88,166,255,0.7)'
    ctx.font = '10px monospace'
    ctx.textAlign = 'left'
    ctx.fillText(new Date().toLocaleTimeString(), 6, H - 6)

    // Person count
    ctx.textAlign = 'right'
    ctx.fillText(`${persons.length} tracked`, W - 6, H - 6)

  }, [feed, persons])

  return (
    <div className="camera-feed group">
      <canvas
        ref={canvasRef}
        width={320}
        height={180}
        className="w-full h-full object-cover"
      />
      <div className="camera-label absolute bottom-0 left-0 right-0 px-2 py-1.5 flex justify-between items-center">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 bg-accent-green rounded-full animate-pulse" />
          <span className="text-xs font-semibold text-white">
            CAM {feed.camera_id + 1} — {CAMERA_NAMES[feed.camera_id] || 'Camera'}
          </span>
        </div>
        <span className="text-xs text-rbis-400">{persons.length} person{persons.length !== 1 ? 's' : ''}</span>
      </div>
      {/* Alert flash */}
      {persons.some(p => p.level === 'HIGH_SUSPICION') && (
        <div className="absolute inset-0 border-2 border-red-500 rounded pointer-events-none animate-pulse" />
      )}
    </div>
  )
}

export default function CameraGrid({ livePersons = [], cameraFrame }) {
  const [feeds, setFeeds] = useState(() =>
    Array.from({ length: 5 }, (_, i) => ({
      camera_id: i, persons: [], person_count: 0
    }))
  )

  // Refresh feeds from API occasionally
  useEffect(() => {
    const refresh = async () => {
      try {
        const res = await cameraAPI.feeds()
        if (res.data?.feeds) setFeeds(res.data.feeds)
      } catch (_) {}
    }
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="grid grid-cols-3 gap-2">
      {feeds.map(feed => (
        <CameraFeed
          key={feed.camera_id}
          feed={feed}
          livePersons={livePersons}
        />
      ))}
    </div>
  )
}
