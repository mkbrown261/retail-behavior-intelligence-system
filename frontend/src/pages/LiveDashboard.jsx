import React, { useEffect, useState, useRef } from 'react'
import { systemAPI, personAPI } from '../utils/api'
import { useWebSocket } from '../hooks/useWebSocket'
import CameraGrid from '../components/cameras/CameraGrid'
import PersonTracker from '../components/dashboard/PersonTracker'
import AlertsPanel from '../components/alerts/AlertsPanel'
import TopIncidentsPanel from '../components/alerts/TopIncidentsPanel'
import PersonTimeline from '../components/dashboard/PersonTimeline'
import {
  Users, AlertTriangle, Eye, Wifi, WifiOff, Activity,
  TrendingUp, Clock
} from 'lucide-react'

function StatCard({ icon: Icon, label, value, color = 'text-accent-blue', sub }) {
  return (
    <div className="stat-card">
      <Icon size={14} className={color} />
      <div className={`stat-value ${color}`}>{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="text-xs text-rbis-500 mt-0.5">{sub}</div>}
    </div>
  )
}

// Live event ticker
function EventTicker({ events }) {
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center gap-2 mb-2">
        <Activity size={14} className="text-accent-green" />
        <span className="text-xs font-semibold text-rbis-200 uppercase tracking-wider">Live Events</span>
      </div>
      <div className="space-y-1 max-h-28 overflow-y-auto pr-1">
        {events.length === 0 ? (
          <p className="text-xs text-rbis-500">Awaiting detections...</p>
        ) : (
          events.slice(0, 10).map((e, i) => (
            <div key={i} className="flex items-center gap-2 text-xs animate-fade-in">
              <span className="text-rbis-500 font-mono flex-shrink-0">{e.time}</span>
              <span className="font-mono text-rbis-300 flex-shrink-0">{e.session_id}</span>
              <span className={`flex-shrink-0 ${
                e.event_type === 'BYPASS_REGISTER' || e.event_type === 'EXIT_AFTER_PICK'
                  ? 'text-red-400 font-bold'
                  : e.event_type === 'PICK_ITEM' || e.event_type === 'HOLD_ITEM'
                  ? 'text-yellow-400'
                  : 'text-rbis-400'
              }`}>{e.event_type}</span>
              <span className="text-rbis-600 text-xs">CAM{e.camera_id + 1}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default function LiveDashboard() {
  const { connected, lastDetection, lastAlert, lastScore } = useWebSocket()
  const [stats, setStats] = useState({ total: 0, active: 0, flagged: 0, staff: 0 })
  const [systemStatus, setSystemStatus] = useState({})
  const [livePersons, setLivePersons] = useState([])
  const [selectedPersonId, setSelectedPersonId] = useState(null)
  const [recentEvents, setRecentEvents] = useState([])
  const eventsRef = useRef([])

  // Load stats periodically
  useEffect(() => {
    const load = async () => {
      try {
        const [statsRes, statusRes] = await Promise.all([
          personAPI.stats(),
          systemAPI.status(),
        ])
        setStats(statsRes.data)
        setSystemStatus(statusRes.data)
      } catch (_) {}
    }
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])

  // Handle live detections
  useEffect(() => {
    if (!lastDetection) return
    // Add to event ticker
    const evt = {
      time: new Date().toLocaleTimeString('en', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      session_id: lastDetection.session_id,
      event_type: lastDetection.event_type,
      camera_id: lastDetection.camera_id,
      score: lastDetection.score,
      level: lastDetection.level,
    }
    eventsRef.current = [evt, ...eventsRef.current].slice(0, 20)
    setRecentEvents([...eventsRef.current])

    // Update live persons for camera grid
    setLivePersons(prev => {
      const idx = prev.findIndex(p => p.session_id === lastDetection.session_id)
      const updated = {
        session_id: lastDetection.session_id,
        camera_id: lastDetection.camera_id,
        bbox: lastDetection.bbox,
        score: lastDetection.score,
        level: lastDetection.level,
        is_staff: lastDetection.is_staff,
      }
      if (idx >= 0) {
        const next = [...prev]
        next[idx] = { ...next[idx], ...updated }
        return next
      }
      return [updated, ...prev].slice(0, 30)
    })
  }, [lastDetection])

  // Score updates
  useEffect(() => {
    if (!lastScore) return
    setLivePersons(prev =>
      prev.map(p =>
        p.session_id === lastScore.session_id
          ? { ...p, score: lastScore.score, level: lastScore.level }
          : p
      )
    )
  }, [lastScore])

  return (
    <div className="flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-rbis-100 flex items-center gap-2">
            <span className="text-accent-blue">⬡</span>
            Live Surveillance Dashboard
          </h1>
          <p className="text-xs text-rbis-500 mt-0.5">Real-time multi-camera behavioral tracking</p>
        </div>
        <div className="flex items-center gap-2">
          {connected ? (
            <span className="flex items-center gap-1.5 text-xs text-accent-green font-semibold">
              <Wifi size={13} />
              Live
              <span className="w-1.5 h-1.5 bg-accent-green rounded-full animate-pulse" />
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-xs text-accent-red">
              <WifiOff size={13} />
              Reconnecting…
            </span>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatCard icon={Users}        label="Total Persons"  value={stats.total || 0}   color="text-accent-blue"   />
        <StatCard icon={Eye}          label="Active Now"     value={stats.active || 0}  color="text-accent-green"  sub={`${systemStatus.active_persons || 0} tracked`} />
        <StatCard icon={AlertTriangle} label="Flagged"       value={stats.flagged || 0} color="text-accent-red"    />
        <StatCard icon={Users}        label="Staff"          value={stats.staff || 0}   color="text-accent-blue"   />
        <StatCard icon={Activity}     label="Pipeline"       value={systemStatus.pipeline_running ? 'Active' : 'Off'} color={systemStatus.pipeline_running ? 'text-accent-green' : 'text-rbis-400'} />
        <StatCard icon={Wifi}         label="WS Clients"     value={systemStatus.connected_clients || 0} color="text-accent-cyan" />
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Camera feeds — 2/3 width */}
        <div className="lg:col-span-2 space-y-3">
          <CameraGrid livePersons={livePersons} />
          <EventTicker events={recentEvents} />
        </div>

        {/* Right panel — 1/3 width */}
        <div className="space-y-3">
          <PersonTracker
            liveScores={systemStatus.live_scores || []}
            onSelectPerson={(p) => setSelectedPersonId(p.id)}
          />
        </div>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <AlertsPanel
          newAlert={lastAlert}
          onSelectPerson={(pid) => setSelectedPersonId(pid)}
        />
        <TopIncidentsPanel
          onSelectPerson={(pid) => setSelectedPersonId(pid)}
        />
      </div>

      {/* Person timeline modal */}
      {selectedPersonId && (
        <PersonTimeline
          personId={selectedPersonId}
          onClose={() => setSelectedPersonId(null)}
        />
      )}
    </div>
  )
}
