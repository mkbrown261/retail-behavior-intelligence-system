import React, { useEffect, useState } from 'react'
import { personAPI } from '../../utils/api'
import { ScoreBadge, LevelBadge, ScoreBar, PersonTypeBadge, ColorDot, Spinner } from '../dashboard/Badges'
import { User, Clock, Camera, TrendingUp, ChevronRight } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

function PersonRow({ person, onClick }) {
  const age = person.entry_time
    ? formatDistanceToNow(new Date(person.entry_time), { addSuffix: true })
    : ''

  const scoreColor =
    person.suspicion_level === 'HIGH_SUSPICION' ? 'text-red-400' :
    person.suspicion_level === 'WATCH' ? 'text-yellow-400' : 'text-green-400'

  return (
    <button
      onClick={() => onClick && onClick(person)}
      className={`w-full text-left flex items-center gap-3 p-3 rounded border transition-all hover:bg-rbis-700/50 ${
        person.suspicion_level === 'HIGH_SUSPICION' ? 'border-red-800/70 bg-red-950/20' :
        person.suspicion_level === 'WATCH'          ? 'border-yellow-800/50 bg-yellow-950/10' :
        'border-rbis-600/50 bg-rbis-800/30'
      } ${!person.is_active ? 'opacity-60' : ''}`}
    >
      {/* Color indicator */}
      <div className="flex flex-col items-center gap-1 flex-shrink-0">
        <ColorDot color={person.dominant_color || '#888'} />
        {person.is_active && (
          <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
        )}
      </div>

      {/* Main info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono font-bold text-sm text-rbis-100">{person.session_id}</span>
          <PersonTypeBadge type={person.person_type} />
          {person.is_flagged && (
            <span className="text-xs text-red-400 font-semibold">⚑ FLAGGED</span>
          )}
        </div>
        <ScoreBar score={person.current_suspicion_score || 0} />
        <div className="flex items-center gap-3 mt-1 text-xs text-rbis-500">
          <span className="flex items-center gap-1">
            <Clock size={10} />
            {age}
          </span>
          {person.last_camera_id !== null && person.last_camera_id !== undefined && (
            <span className="flex items-center gap-1">
              <Camera size={10} />
              CAM {person.last_camera_id + 1}
            </span>
          )}
          {person.cameras_seen?.length > 1 && (
            <span className="text-rbis-500">{person.cameras_seen.length} cams</span>
          )}
        </div>
      </div>

      {/* Score */}
      <div className={`flex-shrink-0 text-right ${scoreColor}`}>
        <div className="text-lg font-bold font-mono leading-none">
          {(person.current_suspicion_score || 0).toFixed(0)}
        </div>
        <div className="text-xs opacity-60">/100</div>
      </div>

      <ChevronRight size={14} className="text-rbis-500 flex-shrink-0" />
    </button>
  )
}

export default function PersonTracker({ liveScores = [], onSelectPerson }) {
  const [persons, setPersons] = useState([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('active')

  const load = async () => {
    try {
      const params = tab === 'active'
        ? { active_only: true, limit: 30 }
        : tab === 'flagged'
        ? { flagged_only: true, limit: 30 }
        : { limit: 30 }
      const res = await personAPI.list(params)
      setPersons(res.data?.persons || [])
    } catch (e) {
      console.error('PersonTracker load error:', e)
      setPersons([])
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [tab])

  // Merge live scores
  useEffect(() => {
    if (liveScores.length > 0) {
      setPersons(prev =>
        prev.map(p => {
          const live = liveScores.find(s => s.person_id === p.id)
          if (live) return {
            ...p,
            current_suspicion_score: live.score,
            suspicion_level: live.level,
          }
          return p
        })
      )
    }
  }, [liveScores])

  // Periodic refresh
  useEffect(() => {
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [tab])

  // Sort: high suspicion first, then by score
  const sorted = [...persons].sort((a, b) => {
    const order = { HIGH_SUSPICION: 3, WATCH: 2, NORMAL: 1 }
    const diff = (order[b.suspicion_level] || 0) - (order[a.suspicion_level] || 0)
    return diff || (b.current_suspicion_score || 0) - (a.current_suspicion_score || 0)
  })

  const counts = {
    active: persons.filter(p => p.is_active).length,
    flagged: persons.filter(p => p.is_flagged).length,
  }

  return (
    <div className="card h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <User size={16} className="text-accent-blue" />
          <span className="font-semibold text-sm">Tracked Persons</span>
        </div>
        <button onClick={load} className="text-xs text-rbis-400 hover:text-rbis-200">↻ Refresh</button>
      </div>

      <div className="flex gap-1">
        {[
          { key: 'active',  label: `Active (${counts.active})` },
          { key: 'flagged', label: `Flagged (${counts.flagged})` },
          { key: 'all',     label: 'All' },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-2 py-0.5 text-xs rounded ${tab === t.key ? 'bg-accent-blue text-rbis-900 font-semibold' : 'bg-rbis-700 text-rbis-300 hover:bg-rbis-600'}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto space-y-1.5 pr-1" style={{ maxHeight: 420 }}>
        {loading ? (
          <div className="flex justify-center py-8"><Spinner /></div>
        ) : sorted.length === 0 ? (
          <div className="text-center py-8 text-rbis-500 text-sm">No persons tracked yet</div>
        ) : (
          sorted.map(p => (
            <PersonRow key={p.id} person={p} onClick={onSelectPerson} />
          ))
        )}
      </div>
    </div>
  )
}
