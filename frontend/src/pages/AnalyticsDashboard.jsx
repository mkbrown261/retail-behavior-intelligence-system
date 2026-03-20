import React, { useState } from 'react'
import HeatmapView from '../components/analytics/HeatmapView'
import ReportsView from '../components/analytics/ReportsView'
import RepeatVisitorsView from '../components/analytics/RepeatVisitorsView'
import { Layers, FileText, Users } from 'lucide-react'
import { format } from 'date-fns'

const TABS = [
  { key: 'heatmap',  label: 'Heatmap',          icon: Layers    },
  { key: 'reports',  label: 'Daily Reports',     icon: FileText  },
  { key: 'visitors', label: 'Repeat Visitors',   icon: Users     },
]

const INTERACTION_TYPES = ['', 'WALK', 'INTERACT']

export default function AnalyticsDashboard() {
  const [tab, setTab] = useState('heatmap')
  const [day, setDay] = useState(format(new Date(), 'yyyy-MM-dd'))
  const [filterType, setFilterType] = useState('')

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold text-rbis-100">Analytics & Intelligence</h1>
          <p className="text-xs text-rbis-500">Phase 2 — Advanced store analytics platform</p>
        </div>

        {tab === 'heatmap' && (
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={day}
              onChange={e => setDay(e.target.value)}
              className="bg-rbis-700 border border-rbis-600 text-rbis-200 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-accent-blue"
            />
            <select
              value={filterType}
              onChange={e => setFilterType(e.target.value)}
              className="bg-rbis-700 border border-rbis-600 text-rbis-200 text-xs rounded px-2 py-1.5 focus:outline-none focus:border-accent-blue"
            >
              <option value="">All Activity</option>
              <option value="WALK">Walk</option>
              <option value="INTERACT">Interactions</option>
            </select>
          </div>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-rbis-700 pb-0">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium transition-colors rounded-t ${
              tab === key
                ? 'bg-rbis-800 text-accent-blue border-b-2 border-accent-blue -mb-px'
                : 'text-rbis-400 hover:text-rbis-200'
            }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="card">
        {tab === 'heatmap' && (
          <HeatmapView day={day} filterType={filterType} />
        )}
        {tab === 'reports' && (
          <ReportsView />
        )}
        {tab === 'visitors' && (
          <RepeatVisitorsView />
        )}
      </div>
    </div>
  )
}
