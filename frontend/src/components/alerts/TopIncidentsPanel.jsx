import React, { useEffect, useState } from 'react'
import { alertAPI } from '../../utils/api'
import { SeverityBadge, ScoreBadge, Spinner } from '../dashboard/Badges'
import { Siren, Eye, RefreshCw } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export default function TopIncidentsPanel({ onSelectPerson }) {
  const [incidents, setIncidents] = useState([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const res = await alertAPI.topIncidents()
      setIncidents(res.data?.incidents || [])
    } catch (e) {
      console.error('TopIncidentsPanel load error:', e)
      setIncidents([])
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  return (
    <div className="card flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Siren size={16} className="text-accent-red animate-pulse" />
          <span className="font-semibold text-sm">Top Incidents</span>
        </div>
        <button onClick={load} className="text-xs text-rbis-400 hover:text-rbis-200">
          <RefreshCw size={12} />
        </button>
      </div>

      <div className="space-y-2">
        {loading ? (
          <div className="flex justify-center py-4"><Spinner /></div>
        ) : incidents.length === 0 ? (
          <p className="text-center text-rbis-500 text-xs py-4">No incidents recorded</p>
        ) : (
          incidents.slice(0, 8).map((inc, i) => (
            <div
              key={inc.id}
              className={`flex items-center gap-3 p-2.5 rounded border ${
                inc.severity === 'CRITICAL' ? 'border-red-800/70 bg-red-950/20' :
                inc.severity === 'HIGH'     ? 'border-red-900/40 bg-red-950/10' :
                'border-rbis-600 bg-rbis-800/30'
              }`}
            >
              <span className="w-5 text-xs text-rbis-500 text-right font-mono flex-shrink-0">
                #{i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <SeverityBadge severity={inc.severity} />
                  <span className="text-xs text-rbis-200 truncate flex-1">{inc.title}</span>
                </div>
                <div className="flex items-center gap-2 mt-1 text-xs text-rbis-500">
                  <span>{inc.timestamp ? formatDistanceToNow(new Date(inc.timestamp), { addSuffix: true }) : ''}</span>
                  {inc.camera_id !== null && inc.camera_id !== undefined && (
                    <span>CAM {inc.camera_id + 1}</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <ScoreBadge score={inc.suspicion_score} level={
                  inc.suspicion_score >= 61 ? 'HIGH_SUSPICION' :
                  inc.suspicion_score >= 31 ? 'WATCH' : 'NORMAL'
                } size="sm" />
                <button
                  onClick={() => onSelectPerson && onSelectPerson(inc.person_id)}
                  className="p-1 rounded hover:bg-rbis-600 text-rbis-400 hover:text-rbis-100"
                  title="View timeline"
                >
                  <Eye size={13} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
