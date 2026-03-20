import React, { useEffect, useState } from 'react'
import { analyticsAPI } from '../../utils/api'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend
} from 'recharts'
import { FileText, RefreshCw, Download, TrendingUp, Users, AlertTriangle, Clock } from 'lucide-react'
import { Spinner } from '../dashboard/Badges'
import { format } from 'date-fns'

const SEVERITY_COLORS = {
  CRITICAL: '#f85149',
  HIGH:     '#fb8c00',
  MEDIUM:   '#d29922',
  LOW:      '#58a6ff',
}

export default function ReportsView() {
  const [reports, setReports] = useState([])
  const [selected, setSelected] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [loading, setLoading] = useState(true)

  const loadReports = async () => {
    setLoading(true)
    try {
      const res = await analyticsAPI.reports()
      const rpts = res.data.reports
      setReports(rpts)
      if (rpts.length > 0 && !selected) setSelected(rpts[0])
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  useEffect(() => { loadReports() }, [])

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res = await analyticsAPI.generateReport()
      setReports(prev => {
        const exists = prev.find(r => r.report_date === res.data.report_date)
        return exists
          ? prev.map(r => r.report_date === res.data.report_date ? res.data : r)
          : [res.data, ...prev]
      })
      setSelected(res.data)
    } catch (e) { console.error(e) }
    setGenerating(false)
  }

  const riskChartData = selected?.risk_time_windows?.map(w => ({
    hour: `${w.hour}:00`,
    alerts: w.alert_count,
  })) || []

  const topIncidentData = selected?.top_incidents?.slice(0, 5).map(inc => ({
    name: inc.person_id?.slice(-8) || '—',
    score: inc.score || 0,
    severity: inc.severity,
  })) || []

  return (
    <div className="flex gap-4 h-full">
      {/* Sidebar: report list */}
      <div className="w-48 flex-shrink-0 flex flex-col gap-2">
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="btn-primary flex items-center justify-center gap-2 w-full text-sm"
        >
          {generating ? <Spinner size={14} /> : <RefreshCw size={14} />}
          {generating ? 'Generating…' : 'Generate Today'}
        </button>
        <div className="space-y-1 overflow-y-auto">
          {loading ? (
            <div className="flex justify-center py-4"><Spinner /></div>
          ) : reports.length === 0 ? (
            <p className="text-xs text-rbis-500 text-center py-4">No reports yet</p>
          ) : (
            reports.map(r => (
              <button
                key={r.report_date}
                onClick={() => setSelected(r)}
                className={`w-full text-left px-3 py-2 rounded text-xs transition-colors ${
                  selected?.report_date === r.report_date
                    ? 'bg-accent-blue text-rbis-900 font-bold'
                    : 'bg-rbis-700 text-rbis-300 hover:bg-rbis-600'
                }`}
              >
                <div className="font-mono">{r.report_date}</div>
                <div className="opacity-70">{r.total_visitors} visitors</div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Main report view */}
      <div className="flex-1 overflow-y-auto">
        {!selected ? (
          <div className="flex items-center justify-center h-full text-rbis-500 text-sm">
            Select or generate a report
          </div>
        ) : (
          <div className="space-y-4">
            {/* Report header */}
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-rbis-100 flex items-center gap-2">
                  <FileText size={18} className="text-accent-blue" />
                  Report — {selected.report_date}
                </h2>
                <p className="text-xs text-rbis-500 mt-0.5">
                  Generated: {selected.created_at ? format(new Date(selected.created_at), 'MMM d, HH:mm') : '—'}
                </p>
              </div>
              {selected.pdf_path && (
                <a
                  href={`/media/${selected.pdf_path}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-ghost flex items-center gap-2 text-sm"
                >
                  <Download size={14} />
                  PDF
                </a>
              )}
            </div>

            {/* KPI cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: 'Total Visitors',    value: selected.total_visitors,    icon: Users,          color: 'text-accent-blue'   },
                { label: 'Suspicious Events', value: selected.suspicious_events,  icon: AlertTriangle,  color: 'text-accent-yellow' },
                { label: 'Total Alerts',      value: selected.total_alerts,       icon: AlertTriangle,  color: 'text-accent-orange' },
                { label: 'Critical Alerts',   value: selected.critical_alerts,    icon: AlertTriangle,  color: 'text-accent-red'    },
                { label: 'Avg Score',         value: `${(selected.avg_suspicion_score || 0).toFixed(1)}/100`, icon: TrendingUp, color: 'text-accent-purple' },
                { label: 'Peak Hour',         value: selected.peak_hour !== null ? `${selected.peak_hour}:00` : '—', icon: Clock, color: 'text-accent-cyan' },
                { label: 'Customers',         value: selected.unique_customers,   icon: Users,          color: 'text-accent-green'  },
                { label: 'Staff',             value: selected.staff_count,        icon: Users,          color: 'text-accent-blue'   },
              ].map(({ label, value, icon: Icon, color }) => (
                <div key={label} className="stat-card">
                  <Icon size={14} className={`${color} mb-1`} />
                  <div className={`stat-value ${color}`}>{value}</div>
                  <div className="stat-label">{label}</div>
                </div>
              ))}
            </div>

            {/* Risk time windows chart */}
            {riskChartData.length > 0 && (
              <div className="card">
                <p className="text-sm font-semibold mb-3 text-rbis-200">High-Risk Time Windows</p>
                <ResponsiveContainer width="100%" height={140}>
                  <BarChart data={riskChartData}>
                    <XAxis dataKey="hour" tick={{ fontSize: 10, fill: '#6e7681' }} />
                    <YAxis tick={{ fontSize: 10, fill: '#6e7681' }} width={24} />
                    <Tooltip
                      contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6, fontSize: 11 }}
                    />
                    <Bar dataKey="alerts" fill="#f85149" radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Top incidents */}
            {selected.top_incidents?.length > 0 && (
              <div className="card">
                <p className="text-sm font-semibold mb-3 text-rbis-200">Top Incidents</p>
                <div className="space-y-2">
                  {selected.top_incidents.slice(0, 10).map((inc, i) => (
                    <div key={i} className="flex items-center gap-3 text-sm">
                      <span className="w-5 text-rbis-500 text-xs text-right">#{i + 1}</span>
                      <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${
                        inc.severity === 'CRITICAL' ? 'bg-red-900 text-red-300' :
                        inc.severity === 'HIGH'     ? 'bg-orange-900/50 text-orange-300' :
                        'bg-yellow-900/50 text-yellow-300'
                      }`}>{inc.severity}</span>
                      <span className="flex-1 text-rbis-300 truncate text-xs">{inc.title}</span>
                      <span className="text-rbis-400 font-mono text-xs">{(inc.score || 0).toFixed(1)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
