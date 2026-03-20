import React, { useEffect, useState } from 'react'
import { alertAPI } from '../../utils/api'
import { SeverityBadge, ScoreBadge, Spinner } from '../dashboard/Badges'
import { Bell, Eye, CheckCircle, Siren } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

function AlertRow({ alert, onAcknowledge, onView }) {
  const age = alert.timestamp
    ? formatDistanceToNow(new Date(alert.timestamp), { addSuffix: true })
    : ''

  return (
    <div className={`flex gap-3 p-3 rounded border transition-all ${
      alert.severity === 'CRITICAL' ? 'border-red-800 bg-red-950/30' :
      alert.severity === 'HIGH'     ? 'border-red-900/60 bg-red-950/10' :
      'border-rbis-600 bg-rbis-800/50'
    } ${alert.is_acknowledged ? 'opacity-50' : ''}`}>

      {/* Icon */}
      <div className={`flex-shrink-0 mt-0.5 ${
        alert.severity === 'CRITICAL' ? 'text-red-400' :
        alert.severity === 'HIGH'     ? 'text-orange-400' :
        alert.severity === 'MEDIUM'   ? 'text-yellow-400' : 'text-blue-400'
      }`}>
        <Bell size={16} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <SeverityBadge severity={alert.severity} />
          <span className="text-sm font-semibold text-rbis-100 truncate">{alert.title}</span>
        </div>
        <p className="text-xs text-rbis-400 mt-0.5 truncate">{alert.description}</p>
        <div className="flex items-center gap-3 mt-1.5 flex-wrap">
          <span className="text-xs text-rbis-500">{age}</span>
          {alert.camera_id !== null && alert.camera_id !== undefined && (
            <span className="text-xs text-rbis-500">CAM {alert.camera_id + 1}</span>
          )}
          <ScoreBadge score={alert.suspicion_score} level={
            alert.suspicion_score >= 61 ? 'HIGH_SUSPICION' :
            alert.suspicion_score >= 31 ? 'WATCH' : 'NORMAL'
          } size="sm" />
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-1 flex-shrink-0">
        <button
          onClick={() => onView && onView(alert)}
          className="p-1.5 rounded hover:bg-rbis-600 text-rbis-400 hover:text-rbis-100"
          title="View details"
        >
          <Eye size={14} />
        </button>
        {!alert.is_acknowledged && (
          <button
            onClick={() => onAcknowledge && onAcknowledge(alert.id)}
            className="p-1.5 rounded hover:bg-green-900/50 text-rbis-400 hover:text-green-400"
            title="Acknowledge"
          >
            <CheckCircle size={14} />
          </button>
        )}
      </div>
    </div>
  )
}

export default function AlertsPanel({ newAlert, onSelectPerson }) {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState({})
  const [filter, setFilter] = useState('ALL')

  const load = async () => {
    try {
      const [alertsRes, statsRes] = await Promise.all([
        alertAPI.list({ limit: 30 }),
        alertAPI.stats(),
      ])
      setAlerts(alertsRes.data?.alerts || [])
      setStats(statsRes.data || {})
    } catch (e) {
      console.error('AlertsPanel load error:', e)
      setAlerts([])
      setStats({})
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  // Inject new alert from WS
  useEffect(() => {
    if (newAlert) {
      setAlerts(prev => [newAlert, ...prev].slice(0, 30))
    }
  }, [newAlert])

  const handleAcknowledge = async (id) => {
    await alertAPI.acknowledge(id)
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, is_acknowledged: true } : a))
  }

  const filtered = filter === 'ALL'
    ? alerts
    : alerts.filter(a => a.severity === filter)

  return (
    <div className="card h-full flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bell size={16} className="text-accent-red" />
          <span className="font-semibold text-sm">Alerts</span>
          {stats.critical > 0 && (
            <span className="px-1.5 py-0.5 bg-red-900 text-red-400 text-xs rounded-full font-bold animate-pulse">
              {stats.critical} CRITICAL
            </span>
          )}
        </div>
        <span className="text-xs text-rbis-400">{stats.total || 0} total</span>
      </div>

      {/* Filter pills */}
      <div className="flex gap-1 flex-wrap">
        {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map(s => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={`px-2 py-0.5 text-xs rounded transition-colors ${
              filter === s ? 'bg-accent-blue text-rbis-900 font-semibold' : 'bg-rbis-700 text-rbis-300 hover:bg-rbis-600'
            }`}
          >
            {s}
            {s !== 'ALL' && stats.by_severity?.[s] ? ` (${stats.by_severity[s]})` : ''}
          </button>
        ))}
      </div>

      {/* Alert list */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-1" style={{ maxHeight: 420 }}>
        {loading ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-8 text-rbis-500 text-sm">No alerts</div>
        ) : (
          filtered.map(alert => (
            <AlertRow
              key={alert.id}
              alert={alert}
              onAcknowledge={handleAcknowledge}
              onView={(a) => onSelectPerson && onSelectPerson(a.person_id)}
            />
          ))
        )}
      </div>
    </div>
  )
}
