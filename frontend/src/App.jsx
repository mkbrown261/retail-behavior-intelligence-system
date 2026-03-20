import React from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import LiveDashboard from './pages/LiveDashboard'
import AnalyticsDashboard from './pages/AnalyticsDashboard'
import PersonsPage from './pages/PersonsPage'
import CamerasPage from './pages/CamerasPage'
import ErrorBoundary from './components/ErrorBoundary'
import {
  Monitor, BarChart2, Users, Shield, Eye, AlertTriangle, Camera
} from 'lucide-react'

const NAV = [
  { to: '/',          label: 'Live',       icon: Monitor  },
  { to: '/analytics', label: 'Analytics',  icon: BarChart2 },
  { to: '/persons',   label: 'Persons',    icon: Users    },
  { to: '/cameras',   label: 'Cameras',    icon: Camera   },
]

const API_BASE = import.meta.env.VITE_API_URL || ''
const IS_DEMO = !API_BASE
/* eslint-disable no-undef */
const _BUILD = typeof __BUILD_TS__ !== 'undefined' ? __BUILD_TS__ : 0

function NavItem({ to, label, icon: Icon }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-2 rounded text-sm font-medium transition-colors ${
          isActive
            ? 'bg-rbis-700 text-accent-blue border border-rbis-600'
            : 'text-rbis-400 hover:text-rbis-200 hover:bg-rbis-800'
        }`
      }
    >
      <Icon size={15} />
      <span className="hidden sm:inline">{label}</span>
    </NavLink>
  )
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col bg-rbis-900">
      {/* Top navbar */}
      <header className="sticky top-0 z-40 bg-rbis-800 border-b border-rbis-700 px-4 py-2">
        <div className="max-w-screen-2xl mx-auto flex items-center justify-between gap-4">
          {/* Brand */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <div className="w-7 h-7 rounded bg-accent-blue/20 border border-accent-blue/50 flex items-center justify-center">
              <Eye size={14} className="text-accent-blue" />
            </div>
            <div className="hidden sm:block">
              <div className="text-sm font-bold text-rbis-100 leading-none">RBIS</div>
              <div className="text-xs text-rbis-500 leading-none">Retail Intelligence v2.0</div>
            </div>
          </div>

          {/* Nav */}
          <nav className="flex items-center gap-1">
            {NAV.map(n => <NavItem key={n.to} {...n} />)}
          </nav>

          {/* System indicator */}
          <div className="flex items-center gap-2 text-xs text-rbis-500 flex-shrink-0">
            <Shield size={12} className="text-accent-green" />
            <span className="hidden md:inline">No Facial Recognition</span>
          </div>
        </div>
      </header>

      {/* Offline / Demo mode banner */}
      {IS_DEMO && (
        <div style={{
          background: 'rgba(210,153,34,0.12)',
          borderBottom: '1px solid rgba(210,153,34,0.35)',
          padding: '6px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: 12,
          color: '#d29922',
          flexWrap: 'wrap',
        }}>
          <AlertTriangle size={13} style={{ flexShrink: 0 }} />
          <span>
            <strong>Demo Mode</strong> — Running without a backend. To use live cameras, run the
            RBIS backend on your computer and open{' '}
            <code style={{ background: 'rgba(0,0,0,0.3)', padding: '1px 5px', borderRadius: 3 }}>http://&lt;your-ip&gt;:8000</code>
            {' '}on any device on your network.
          </span>
        </div>
      )}

      {/* Page content */}
      <main className="flex-1 max-w-screen-2xl w-full mx-auto px-4 py-4">
        <ErrorBoundary>
          <Routes>
            <Route path="/"          element={<LiveDashboard />} />
            <Route path="/analytics" element={<AnalyticsDashboard />} />
            <Route path="/persons"   element={<PersonsPage />} />
            <Route path="/cameras"   element={<CamerasPage />} />
          </Routes>
        </ErrorBoundary>
      </main>

      {/* Footer */}
      <footer className="border-t border-rbis-700 px-4 py-2 text-xs text-rbis-600 text-center">
        RBIS v2.0 — Behavior-Based Analytics · Privacy Compliant · No Facial Recognition
      </footer>
    </div>
  )
}
