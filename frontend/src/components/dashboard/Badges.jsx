import React from 'react'

export function ScoreBadge({ score = 0, level = 'NORMAL', size = 'md' }) {
  const cls = {
    NORMAL:        'bg-green-900/50 text-green-400 border-green-800',
    WATCH:         'bg-yellow-900/50 text-yellow-400 border-yellow-800',
    HIGH_SUSPICION:'bg-red-900/50 text-red-400 border-red-800 animate-pulse',
  }[level] || 'bg-rbis-700 text-rbis-300 border-rbis-600'

  const sz = size === 'sm' ? 'text-xs px-1.5 py-0.5' : 'text-sm px-2 py-1'

  return (
    <span className={`inline-flex items-center gap-1 rounded border font-mono font-semibold ${cls} ${sz}`}>
      {level === 'HIGH_SUSPICION' && <span className="inline-block w-1.5 h-1.5 bg-red-400 rounded-full" />}
      {score.toFixed(0)}/100
    </span>
  )
}

export function LevelBadge({ level = 'NORMAL' }) {
  const map = {
    NORMAL:        { cls: 'badge-normal',  label: 'Normal' },
    WATCH:         { cls: 'badge-watch',   label: 'Watch'  },
    HIGH_SUSPICION:{ cls: 'badge-high',    label: '⚠ High' },
  }
  const { cls, label } = map[level] || { cls: 'badge-normal', label: level }
  return <span className={cls}>{label}</span>
}

export function SeverityBadge({ severity = 'LOW' }) {
  const map = {
    LOW:      'badge-low',
    MEDIUM:   'badge-medium',
    HIGH:     'badge-high',
    CRITICAL: 'badge-critical',
  }
  return <span className={map[severity] || 'badge-low'}>{severity}</span>
}

export function ScoreBar({ score = 0, animate = true }) {
  const pct = Math.min(100, Math.max(0, score))
  const color =
    pct >= 61 ? '#f85149' :
    pct >= 31 ? '#d29922' :
    '#3fb950'

  return (
    <div className="w-full bg-rbis-700 rounded-full h-1.5 overflow-hidden">
      <div
        className={`h-full rounded-full ${animate ? 'transition-all duration-500' : ''}`}
        style={{ width: `${pct}%`, backgroundColor: color }}
      />
    </div>
  )
}

export function PersonTypeBadge({ type = 'CUSTOMER' }) {
  if (type === 'STAFF') {
    return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-blue-900/50 text-blue-300 border border-blue-800">STAFF</span>
  }
  return <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-rbis-700 text-rbis-300 border border-rbis-600">CUSTOMER</span>
}

export function ColorDot({ color = '#888' }) {
  return (
    <span
      className="inline-block w-3 h-3 rounded-full border border-rbis-500 flex-shrink-0"
      style={{ backgroundColor: color }}
    />
  )
}

export function Spinner({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className="animate-spin text-accent-blue" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4" strokeDashoffset="10" />
    </svg>
  )
}

export function EmptyState({ icon, message }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 text-rbis-500 gap-2">
      {icon && <span className="text-3xl">{icon}</span>}
      <p className="text-sm">{message}</p>
    </div>
  )
}
