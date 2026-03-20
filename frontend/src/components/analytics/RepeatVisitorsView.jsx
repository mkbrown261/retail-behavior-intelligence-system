import React, { useEffect, useState } from 'react'
import { analyticsAPI } from '../../utils/api'
import { ColorDot, Spinner } from '../dashboard/Badges'
import { Users, Flag, TrendingUp } from 'lucide-react'

function ClusterRow({ cluster }) {
  const riskColor =
    cluster.avg_suspicion_score >= 61 ? 'text-red-400' :
    cluster.avg_suspicion_score >= 31 ? 'text-yellow-400' : 'text-green-400'

  return (
    <div className={`p-3 rounded border transition-colors ${
      cluster.is_flagged_pattern
        ? 'border-red-800/70 bg-red-950/20'
        : 'border-rbis-600 bg-rbis-800/50'
    }`}>
      <div className="flex items-center gap-3">
        <ColorDot color={cluster.dominant_color || '#888'} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs text-rbis-300">{cluster.cluster_id}</span>
            {cluster.is_flagged_pattern && (
              <span className="flex items-center gap-1 text-xs text-red-400 font-semibold">
                <Flag size={10} />
                Flagged Pattern
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-1 text-xs text-rbis-400 flex-wrap">
            <span className="flex items-center gap-1">
              <Users size={10} />
              {cluster.visit_count} visit{cluster.visit_count !== 1 ? 's' : ''}
            </span>
            <span className={`flex items-center gap-1 font-mono font-semibold ${riskColor}`}>
              <TrendingUp size={10} />
              Avg: {(cluster.avg_suspicion_score || 0).toFixed(1)}
            </span>
            <span className="text-rbis-500">
              Max: {(cluster.max_suspicion_score || 0).toFixed(1)}
            </span>
            {cluster.total_incidents > 0 && (
              <span className="text-red-400">
                {cluster.total_incidents} incident{cluster.total_incidents !== 1 ? 's' : ''}
              </span>
            )}
          </div>
          {/* Score bar */}
          <div className="mt-1.5 w-full bg-rbis-700 rounded-full h-1 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${Math.min(100, cluster.avg_suspicion_score || 0)}%`,
                backgroundColor:
                  cluster.avg_suspicion_score >= 61 ? '#f85149' :
                  cluster.avg_suspicion_score >= 31 ? '#d29922' : '#3fb950',
              }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function RepeatVisitorsView() {
  const [clusters, setClusters] = useState([])
  const [flagged, setFlagged] = useState([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('flagged')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [allRes, flaggedRes] = await Promise.all([
          analyticsAPI.repeatVisitors(),
          analyticsAPI.flaggedVisitors(),
        ])
        setClusters(allRes.data?.clusters || [])
        setFlagged(flaggedRes.data?.flagged_visitors || [])
      } catch (e) {
        console.error('RepeatVisitorsView load error:', e)
        setClusters([])
        setFlagged([])
      }
      setLoading(false)
    }
    load()
  }, [])

  const displayed = tab === 'flagged' ? flagged : clusters

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users size={16} className="text-accent-blue" />
          <span className="font-semibold">Repeat Visitor Detection</span>
        </div>
        <span className="text-xs text-rbis-400">{clusters.length} appearance clusters</span>
      </div>

      <div className="bg-rbis-900/50 border border-rbis-700 rounded p-3 text-xs text-rbis-400 leading-relaxed">
        🔍 <strong className="text-rbis-200">Non-identity matching</strong> — visitors are clustered by clothing
        colour histogram and body shape. No facial recognition is used.
        Flagged patterns indicate 3+ visits with avg suspicion ≥ 50 or 2+ incidents.
      </div>

      <div className="flex gap-1">
        <button
          onClick={() => setTab('flagged')}
          className={`px-3 py-1 text-xs rounded ${tab === 'flagged' ? 'bg-red-900/50 text-red-400 border border-red-800' : 'btn-ghost'}`}
        >
          ⚑ Flagged ({flagged.length})
        </button>
        <button
          onClick={() => setTab('all')}
          className={`px-3 py-1 text-xs rounded ${tab === 'all' ? 'bg-accent-blue text-rbis-900 font-semibold' : 'btn-ghost'}`}
        >
          All Clusters ({clusters.length})
        </button>
      </div>

      <div className="space-y-2 overflow-y-auto" style={{ maxHeight: 420 }}>
        {loading ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : displayed.length === 0 ? (
          <div className="text-center py-8 text-rbis-500 text-sm">
            {tab === 'flagged' ? 'No flagged patterns detected' : 'No visitor clusters yet'}
          </div>
        ) : (
          displayed.map(c => <ClusterRow key={c.cluster_id} cluster={c} />)
        )}
      </div>
    </div>
  )
}
