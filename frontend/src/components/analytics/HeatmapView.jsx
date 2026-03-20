import React, { useEffect, useState, useRef } from 'react'
import { analyticsAPI } from '../../utils/api'
import { Layers } from 'lucide-react'

const W = 50  // grid columns
const H = 40  // grid rows

const ZONES = [
  { name: 'ENTRANCE',  x1: 0,  y1: 0,  x2: 10, y2: 40, color: 'rgba(88,166,255,0.15)' },
  { name: 'AISLE A',   x1: 10, y1: 0,  x2: 20, y2: 28, color: 'rgba(63,185,80,0.1)'  },
  { name: 'AISLE B',   x1: 20, y1: 0,  x2: 30, y2: 28, color: 'rgba(63,185,80,0.1)'  },
  { name: 'AISLE C',   x1: 30, y1: 0,  x2: 40, y2: 28, color: 'rgba(63,185,80,0.1)'  },
  { name: 'CHECKOUT',  x1: 10, y1: 28, x2: 40, y2: 40, color: 'rgba(189,128,255,0.1)' },
  { name: 'EXIT',      x1: 40, y1: 0,  x2: 50, y2: 40, color: 'rgba(248,81,73,0.1)'  },
]

function heatColor(norm) {
  // blue → green → yellow → red
  if (norm < 0.25) {
    const t = norm / 0.25
    return `rgba(${Math.floor(t * 63)}, ${Math.floor(t * 185)}, 255, ${0.2 + t * 0.5})`
  } else if (norm < 0.5) {
    const t = (norm - 0.25) / 0.25
    return `rgba(${Math.floor(63 + t * 192)}, ${Math.floor(185 - t * 120)}, ${Math.floor(255 - t * 255)}, ${0.55 + t * 0.2})`
  } else if (norm < 0.75) {
    const t = (norm - 0.5) / 0.25
    return `rgba(255, ${Math.floor(65 - t * 65)}, 0, ${0.65 + t * 0.25})`
  }
  return `rgba(248, 81, 73, ${0.8 + norm * 0.2})`
}

export default function HeatmapView({ day, filterType }) {
  const canvasRef = useRef(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selectedHour, setSelectedHour] = useState(null)
  const [hourlySummary, setHourlySummary] = useState([])

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const params = {}
        if (day) params.day = day
        if (selectedHour !== null) params.hour = selectedHour
        if (filterType) params.interaction_type = filterType
        const [hm, hourly] = await Promise.all([
          analyticsAPI.heatmap(params),
          analyticsAPI.heatmapHourly(day),
        ])
        setData(hm.data)
        setHourlySummary(hourly.data.summary || [])
      } catch (e) {
        console.error(e)
      }
      setLoading(false)
    }
    load()
  }, [day, selectedHour, filterType])

  useEffect(() => {
    if (!data || !canvasRef.current) return
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    const CW = canvas.width
    const CH = canvas.height
    const cellW = CW / W
    const cellH = CH / H

    ctx.clearRect(0, 0, CW, CH)

    // Background
    ctx.fillStyle = '#0d1117'
    ctx.fillRect(0, 0, CW, CH)

    // Zone overlays
    ZONES.forEach(z => {
      ctx.fillStyle = z.color
      ctx.fillRect(z.x1 * cellW, z.y1 * cellH, (z.x2 - z.x1) * cellW, (z.y2 - z.y1) * cellH)
      ctx.fillStyle = 'rgba(255,255,255,0.18)'
      ctx.font = `bold ${Math.min(cellW * 4, 12)}px monospace`
      ctx.textAlign = 'center'
      ctx.fillText(
        z.name,
        ((z.x1 + z.x2) / 2) * cellW,
        ((z.y1 + z.y2) / 2) * cellH + 4
      )
    })

    // Grid
    ctx.strokeStyle = '#21262d'
    ctx.lineWidth = 0.3
    for (let x = 0; x <= W; x++) {
      ctx.beginPath(); ctx.moveTo(x * cellW, 0); ctx.lineTo(x * cellW, CH); ctx.stroke()
    }
    for (let y = 0; y <= H; y++) {
      ctx.beginPath(); ctx.moveTo(0, y * cellH); ctx.lineTo(CW, y * cellH); ctx.stroke()
    }

    // Heatmap cells
    const maxW = data.max_weight || 1
    data.cells.forEach(cell => {
      const norm = Math.min(1, cell.weight / maxW)
      ctx.fillStyle = heatColor(norm)
      ctx.fillRect(
        cell.x * cellW, cell.y * cellH,
        cellW + 0.5, cellH + 0.5
      )
    })

    // Border
    ctx.strokeStyle = '#30363d'
    ctx.lineWidth = 1
    ctx.strokeRect(0, 0, CW, CH)

  }, [data])

  const maxHourlyCount = Math.max(...hourlySummary.map(h => h.count), 1)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-accent-blue font-semibold">
          <Layers size={18} />
          <span>Store Heatmap</span>
          {loading && <span className="text-rbis-400 text-xs">(loading...)</span>}
        </div>
        <div className="flex gap-1">
          <button
            onClick={() => setSelectedHour(null)}
            className={`px-2 py-1 text-xs rounded ${selectedHour === null ? 'bg-accent-blue text-rbis-900' : 'btn-ghost'}`}
          >
            All Day
          </button>
        </div>
      </div>

      {/* Canvas */}
      <div className="relative">
        <canvas
          ref={canvasRef}
          width={500}
          height={400}
          className="w-full rounded border border-rbis-600"
          style={{ imageRendering: 'pixelated' }}
        />
        {data && (
          <div className="absolute top-2 right-2 text-xs text-rbis-400 bg-rbis-900/80 px-2 py-1 rounded">
            {data.total_points.toLocaleString()} data points
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-2 text-xs text-rbis-400">
        <span>Low</span>
        <div className="flex-1 h-2 rounded" style={{
          background: 'linear-gradient(to right, rgba(88,166,255,0.4), rgba(63,185,80,0.7), rgba(255,165,0,0.8), rgba(248,81,73,0.95))'
        }} />
        <span>High</span>
      </div>

      {/* Hourly bar chart */}
      {hourlySummary.length > 0 && (
        <div>
          <p className="text-xs text-rbis-400 mb-2 uppercase tracking-wider">Hourly Traffic</p>
          <div className="flex items-end gap-0.5 h-12">
            {Array.from({ length: 24 }, (_, h) => {
              const entry = hourlySummary.find(r => r.hour === h)
              const count = entry?.count || 0
              const pct = count / maxHourlyCount
              return (
                <button
                  key={h}
                  onClick={() => setSelectedHour(selectedHour === h ? null : h)}
                  className={`flex-1 rounded-t transition-all ${selectedHour === h ? 'bg-accent-blue' : 'bg-rbis-600 hover:bg-rbis-500'}`}
                  style={{ height: `${Math.max(4, pct * 100)}%` }}
                  title={`${h}:00 — ${count} tracks`}
                />
              )
            })}
          </div>
          <div className="flex justify-between text-xs text-rbis-500 mt-1">
            <span>00:00</span>
            <span>12:00</span>
            <span>23:59</span>
          </div>
        </div>
      )}
    </div>
  )
}
