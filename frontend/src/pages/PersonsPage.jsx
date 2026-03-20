import React, { useEffect, useState } from 'react'
import { personAPI } from '../utils/api'
import PersonTimeline from '../components/dashboard/PersonTimeline'
import {
  ScoreBadge, ScoreBar, PersonTypeBadge, ColorDot, LevelBadge, Spinner
} from '../components/dashboard/Badges'
import { Search, User, Camera, Clock } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

export default function PersonsPage() {
  const [persons, setPersons] = useState([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [stats, setStats] = useState({})

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const params = filter === 'active'  ? { active_only: true,  limit: 100 }
                     : filter === 'flagged' ? { flagged_only: true, limit: 100 }
                     : filter === 'staff'   ? { person_type: 'STAFF', limit: 100 }
                     : { limit: 100 }
        const [persRes, statsRes] = await Promise.all([
          personAPI.list(params),
          personAPI.stats(),
        ])
        setPersons(persRes.data.persons)
        setStats(statsRes.data)
      } catch (e) { console.error(e) }
      setLoading(false)
    }
    load()
  }, [filter])

  const filtered = persons.filter(p =>
    !search || p.session_id.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-rbis-100">Person Registry</h1>
          <p className="text-xs text-rbis-500">All tracked individuals — click to view full timeline</p>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        {[
          { label: 'Total',     value: stats.total    || 0, color: 'text-rbis-200' },
          { label: 'Active',    value: stats.active   || 0, color: 'text-accent-green' },
          { label: 'Flagged',   value: stats.flagged  || 0, color: 'text-accent-red' },
          { label: 'Staff',     value: stats.staff    || 0, color: 'text-accent-blue' },
          { label: 'Customers', value: stats.customers|| 0, color: 'text-rbis-300' },
        ].map(s => (
          <div key={s.label} className="stat-card">
            <div className={`stat-value ${s.color}`}>{s.value}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-2.5 text-rbis-500" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by ID…"
            className="bg-rbis-700 border border-rbis-600 text-rbis-200 text-xs rounded pl-7 pr-3 py-2 w-40 focus:outline-none focus:border-accent-blue"
          />
        </div>
        {['all', 'active', 'flagged', 'staff'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 text-xs rounded capitalize ${
              filter === f ? 'bg-accent-blue text-rbis-900 font-semibold' : 'btn-ghost'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-rbis-600 text-rbis-400 text-xs uppercase tracking-wider">
              <th className="text-left pb-2 pr-3">ID</th>
              <th className="text-left pb-2 pr-3">Type</th>
              <th className="text-left pb-2 pr-3">Score</th>
              <th className="text-left pb-2 pr-3">Level</th>
              <th className="text-left pb-2 pr-3">Entry</th>
              <th className="text-left pb-2 pr-3">Camera</th>
              <th className="text-left pb-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rbis-700/50">
            {loading ? (
              <tr><td colSpan={7} className="py-8 text-center"><Spinner /></td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={7} className="py-8 text-center text-rbis-500 text-xs">No persons found</td></tr>
            ) : (
              filtered.map(p => (
                <tr
                  key={p.id}
                  onClick={() => setSelected(p.id)}
                  className="hover:bg-rbis-700/40 cursor-pointer transition-colors"
                >
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <ColorDot color={p.dominant_color || '#888'} />
                      <span className="font-mono font-bold text-rbis-100">{p.session_id}</span>
                      {p.is_flagged && <span className="text-red-400 text-xs">⚑</span>}
                    </div>
                  </td>
                  <td className="py-2 pr-3"><PersonTypeBadge type={p.person_type} /></td>
                  <td className="py-2 pr-3">
                    <ScoreBadge
                      score={p.current_suspicion_score || 0}
                      level={p.suspicion_level || 'NORMAL'}
                      size="sm"
                    />
                  </td>
                  <td className="py-2 pr-3"><LevelBadge level={p.suspicion_level || 'NORMAL'} /></td>
                  <td className="py-2 pr-3 text-xs text-rbis-400">
                    {p.entry_time ? formatDistanceToNow(new Date(p.entry_time), { addSuffix: true }) : '—'}
                  </td>
                  <td className="py-2 pr-3 text-xs text-rbis-400">
                    {p.last_camera_id !== null && p.last_camera_id !== undefined
                      ? `CAM ${p.last_camera_id + 1}`
                      : '—'}
                  </td>
                  <td className="py-2">
                    {p.is_active
                      ? <span className="text-xs text-green-400 flex items-center gap-1"><span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />Active</span>
                      : <span className="text-xs text-rbis-500">Exited</span>}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <PersonTimeline personId={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
