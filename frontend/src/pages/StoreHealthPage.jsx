import React, { useEffect, useState, useCallback } from 'react'
import { analyticsAPI, cameraAPI } from '../utils/api'
import { HeartPulse, TrendingDown, TrendingUp, Clock, AlertTriangle, MapPin, Pencil, Check, X } from 'lucide-react'

function scoreColor(score) {
  if (score >= 80) return '#3fb950'
  if (score >= 50) return '#d29922'
  return '#f85149'
}

function BigScore({ score }) {
  const color = scoreColor(score)
  return (
    <div className="card flex flex-col items-center justify-center py-8">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-rbis-500 mb-2">
        <HeartPulse size={14} />
        Store Health Score
      </div>
      <div className="text-6xl font-bold" style={{ color }}>{score}</div>
      <div className="text-sm text-rbis-500 mt-1">out of 100</div>
    </div>
  )
}

function StatCard({ icon: Icon, label, value, sub, color = '#58a6ff' }) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 text-xs text-rbis-500 uppercase tracking-wider mb-2">
        <Icon size={13} style={{ color }} />
        {label}
      </div>
      <div className="text-2xl font-bold text-rbis-100">{value}</div>
      {sub && <div className="text-xs text-rbis-500 mt-1">{sub}</div>}
    </div>
  )
}

function HighRiskZones({ zones, cameraId, onLabelsChanged }) {
  const [editing, setEditing] = useState(null)
  const [draft, setDraft] = useState('')

  const startEdit = (zone, currentLabel) => {
    setEditing(zone)
    setDraft(currentLabel === zone ? '' : currentLabel)
  }

  const save = async (zone) => {
    try {
      const res = await cameraAPI.getZoneLabels(cameraId)
      const labels = { ...(res.data?.labels || {}), [zone]: draft || zone }
      await cameraAPI.saveZoneLabels(cameraId, labels)
      setEditing(null)
      onLabelsChanged()
    } catch (_) {}
  }

  return (
    <div className="card">
      <p className="text-sm font-semibold text-rbis-200 mb-3 flex items-center gap-2">
        <MapPin size={14} className="text-accent-red" />
        High Risk Areas
      </p>
      {zones.length === 0 ? (
        <p className="text-xs text-rbis-500 py-4 text-center">No suspicious activity recorded in this period</p>
      ) : (
        <div className="space-y-2">
          {zones.map((z, i) => (
            <div key={z.zone} className="flex items-center gap-3">
              <span className="text-xs font-mono text-rbis-600 w-5">{i + 1}</span>
              {editing === z.zone ? (
                <div className="flex-1 flex items-center gap-1">
                  <input
                    autoFocus
                    className="input flex-1 text-xs py-1"
                    placeholder={z.zone}
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && save(z.zone)}
                  />
                  <button onClick={() => save(z.zone)} className="btn-ghost p-1"><Check size={13} className="text-green-400" /></button>
                  <button onClick={() => setEditing(null)} className="btn-ghost p-1"><X size={13} className="text-rbis-500" /></button>
                </div>
              ) : (
                <>
                  <span className="text-sm text-rbis-200 flex-1">{z.label}</span>
                  <button onClick={() => startEdit(z.zone, z.label)} className="btn-ghost p-1" title="Rename zone">
                    <Pencil size={11} className="text-rbis-500" />
                  </button>
                </>
              )}
              <div className="w-24 h-1.5 bg-rbis-700 rounded overflow-hidden flex-shrink-0">
                <div
                  className="h-full bg-red-500 rounded"
                  style={{ width: `${Math.min(100, (z.suspicious_events / zones[0].suspicious_events) * 100)}%` }}
                />
              </div>
              <span className="text-xs font-mono text-rbis-400 w-8 text-right">{z.suspicious_events}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function StoreHealthPage() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(7)
  const cameraId = 'webcam' // TODO: multi-camera selector once multi-camera is live-verified

  const load = useCallback(async () => {
    try {
      const res = await analyticsAPI.storeHealth({ days, camera_id: cameraId })
      setData(res.data)
    } catch (_) {
      setData(null)
    }
    setLoading(false)
  }, [days])

  useEffect(() => { load() }, [load])

  if (loading) {
    return <div className="flex justify-center py-20"><span className="animate-spin text-2xl text-accent-blue">⟳</span></div>
  }
  if (!data) {
    return <p className="text-rbis-500 text-sm text-center py-20">Could not load store health data.</p>
  }

  const trendUp = data.risk_trend_pct > 0
  const trendLabel = data.risk_trend_pct === 0
    ? 'No change'
    : `${trendUp ? '+' : ''}${data.risk_trend_pct}% vs prior ${days}d`

  return (
    <div className="flex flex-col gap-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-rbis-100">Store Health</h1>
          <p className="text-xs text-rbis-500 mt-0.5">Business intelligence, not just theft alerts — built from the same data, a different lens.</p>
        </div>
        <select
          className="input text-xs w-32"
          value={days}
          onChange={e => setDays(Number(e.target.value))}
        >
          <option value={7}>Last 7 days</option>
          <option value={14}>Last 14 days</option>
          <option value={30}>Last 30 days</option>
        </select>
      </div>

      <BigScore score={data.health_score} />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard
          icon={trendUp ? TrendingUp : TrendingDown}
          label="Risk Trend"
          value={trendLabel}
          color={trendUp ? '#f85149' : '#3fb950'}
        />
        <StatCard
          icon={Clock}
          label="Avg Response Time"
          value={data.avg_response_seconds != null ? `${Math.round(data.avg_response_seconds)}s` : '—'}
          sub={data.avg_response_seconds == null ? 'No acknowledged alerts yet' : undefined}
        />
        <StatCard
          icon={AlertTriangle}
          label="Critical Alerts"
          value={data.critical_alerts}
          color={data.critical_alerts > 0 ? '#f85149' : '#3fb950'}
        />
        <StatCard
          icon={Clock}
          label="Peak Risk Hour"
          value={data.peak_risk_hour != null ? `${String(data.peak_risk_hour).padStart(2, '0')}:00` : '—'}
        />
      </div>

      <HighRiskZones zones={data.high_risk_zones} cameraId={cameraId} onLabelsChanged={load} />
    </div>
  )
}
