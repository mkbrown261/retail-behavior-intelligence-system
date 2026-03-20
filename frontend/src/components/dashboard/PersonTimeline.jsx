import React, { useEffect, useState } from 'react'
import { personAPI } from '../../utils/api'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine
} from 'recharts'
import { ScoreBadge, LevelBadge, PersonTypeBadge, SeverityBadge, ColorDot, Spinner } from '../dashboard/Badges'
import { X, Camera, Clock, Zap, ChevronDown, ChevronRight } from 'lucide-react'
import { format } from 'date-fns'

const EVENT_ICONS = {
  ENTER_STORE:       '🚪',
  EXIT_STORE:        '🚶',
  PICK_ITEM:         '🛒',
  HOLD_ITEM:         '✋',
  RETURN_ITEM:       '↩️',
  APPROACH_REGISTER: '🏧',
  COMPLETE_CHECKOUT: '✅',
  BYPASS_REGISTER:   '🚨',
}

const EVENT_COLORS = {
  ENTER_STORE:       '#58a6ff',
  EXIT_STORE:        '#8b949e',
  PICK_ITEM:         '#d29922',
  HOLD_ITEM:         '#fb8c00',
  RETURN_ITEM:       '#3fb950',
  APPROACH_REGISTER: '#bc8cff',
  COMPLETE_CHECKOUT: '#3fb950',
  BYPASS_REGISTER:   '#f85149',
}

function TimelineItem({ item }) {
  const isEvent = item.kind === 'EVENT'
  const data = item.data
  const ts = data.timestamp ? format(new Date(data.timestamp), 'HH:mm:ss') : ''

  if (!isEvent) {
    return (
      <div className="flex items-center gap-2 pl-2 border-l border-rbis-600 py-1">
        <span className="w-2 h-2 bg-rbis-600 rounded-full flex-shrink-0" />
        <span className="text-xs text-rbis-500">{ts}</span>
        <span className="text-xs text-rbis-400">Score → {data.score?.toFixed(1)} ({data.reason})</span>
        <span className={`text-xs font-mono ${data.delta > 0 ? 'text-red-400' : 'text-green-400'}`}>
          {data.delta > 0 ? `+${data.delta}` : data.delta}
        </span>
      </div>
    )
  }

  const color = EVENT_COLORS[data.event_type] || '#8b949e'
  const icon  = EVENT_ICONS[data.event_type] || '📍'

  return (
    <div className="flex items-start gap-3 py-1.5">
      <div className="flex flex-col items-center flex-shrink-0">
        <div className="w-7 h-7 rounded flex items-center justify-center text-sm"
          style={{ background: `${color}22`, border: `1px solid ${color}55` }}>
          {icon}
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold" style={{ color }}>
            {data.event_type}
          </span>
          <span className="text-xs text-rbis-500">
            <Camera size={10} className="inline mr-0.5" />
            CAM {data.camera_id + 1}
          </span>
          {data.zone && (
            <span className="text-xs bg-rbis-700 text-rbis-400 px-1 rounded">{data.zone}</span>
          )}
          <span className="text-xs text-rbis-600">{ts}</span>
        </div>
        {data.duration_seconds && (
          <p className="text-xs text-rbis-500 mt-0.5">
            Duration: {data.duration_seconds.toFixed(1)}s
          </p>
        )}
        {data.confidence && (
          <p className="text-xs text-rbis-600 mt-0.5">
            Confidence: {(data.confidence * 100).toFixed(0)}%
          </p>
        )}
      </div>
    </div>
  )
}

export default function PersonTimeline({ personId, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showScores, setShowScores] = useState(true)

  useEffect(() => {
    if (!personId) return
    const load = async () => {
      setLoading(true)
      try {
        const res = await personAPI.timeline(personId)
        setData(res.data)
      } catch (e) { console.error(e) }
      setLoading(false)
    }
    load()
  }, [personId])

  if (!personId) return null

  const person = data?.person
  const timeline = data?.timeline || []

  // Build score chart data
  const scoreData = timeline
    .filter(t => t.kind === 'SCORE')
    .map((t, i) => ({
      index: i,
      score: t.data.score,
      reason: t.data.reason,
      time: t.data.timestamp ? format(new Date(t.data.timestamp), 'HH:mm:ss') : '',
    }))

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-rbis-800 border border-rbis-600 rounded-lg w-full max-w-3xl max-h-[90vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-rbis-600">
          <div className="flex items-center gap-3">
            {person && <ColorDot color={person.dominant_color || '#888'} />}
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold font-mono text-lg">{person?.session_id || '...'}</span>
                {person && <PersonTypeBadge type={person.person_type} />}
                {person?.is_flagged && <span className="text-xs text-red-400 font-semibold">⚑ FLAGGED</span>}
              </div>
              {person && (
                <div className="flex items-center gap-3 text-xs text-rbis-400 mt-0.5">
                  <span>Entry: {person.entry_time ? format(new Date(person.entry_time), 'HH:mm:ss') : '—'}</span>
                  <span>Exit: {person.exit_time ? format(new Date(person.exit_time), 'HH:mm:ss') : 'Active'}</span>
                  <span>Cameras: {person.cameras_seen?.join(', ') || '—'}</span>
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {person && (
              <ScoreBadge
                score={person.current_suspicion_score || 0}
                level={person.suspicion_level || 'NORMAL'}
              />
            )}
            <button onClick={onClose} className="p-1.5 hover:bg-rbis-600 rounded text-rbis-400">
              <X size={18} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {loading ? (
            <div className="flex justify-center py-12"><Spinner size={32} /></div>
          ) : (
            <>
              {/* Score chart */}
              {scoreData.length > 1 && (
                <div className="card">
                  <button
                    onClick={() => setShowScores(!showScores)}
                    className="flex items-center gap-2 text-sm font-semibold text-accent-blue w-full text-left"
                  >
                    <Zap size={14} />
                    Suspicion Score Timeline
                    {showScores ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                  {showScores && (
                    <div className="mt-3 h-32">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={scoreData}>
                          <XAxis dataKey="time" tick={{ fontSize: 9, fill: '#6e7681' }} />
                          <YAxis domain={[0, 100]} tick={{ fontSize: 9, fill: '#6e7681' }} width={28} />
                          <Tooltip
                            contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6, fontSize: 11 }}
                            formatter={(v, _, p) => [`${v.toFixed(1)} (${p.payload.reason})`, 'Score']}
                          />
                          <ReferenceLine y={61} stroke="#f85149" strokeDasharray="4 2" strokeWidth={1} />
                          <ReferenceLine y={31} stroke="#d29922" strokeDasharray="4 2" strokeWidth={1} />
                          <Line
                            type="monotone" dataKey="score" stroke="#58a6ff"
                            strokeWidth={2} dot={false} activeDot={{ r: 4 }}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>
              )}

              {/* Event timeline */}
              <div className="card">
                <p className="text-sm font-semibold text-rbis-200 mb-3 flex items-center gap-2">
                  <Clock size={14} className="text-accent-blue" />
                  Event Timeline ({data?.event_count || 0} events)
                </p>
                <div className="space-y-0.5 divide-y divide-rbis-700/50">
                  {timeline.filter(t => t.kind === 'EVENT').map((item, i) => (
                    <TimelineItem key={i} item={item} />
                  ))}
                  {timeline.filter(t => t.kind === 'EVENT').length === 0 && (
                    <p className="text-xs text-rbis-500 py-4 text-center">No events recorded</p>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
