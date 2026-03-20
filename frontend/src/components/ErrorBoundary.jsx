import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('RBIS ErrorBoundary caught:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: '100vh',
          background: '#0d1117',
          color: '#c9d1d9',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
          gap: '16px',
          fontFamily: 'monospace',
          padding: '24px',
          textAlign: 'center',
        }}>
          <div style={{ fontSize: 40 }}>⚠️</div>
          <h1 style={{ color: '#f85149', fontSize: 20, margin: 0 }}>Dashboard Error</h1>
          <p style={{ color: '#6e7681', fontSize: 13, maxWidth: 500, margin: 0 }}>
            A UI component crashed. This is usually caused by a missing backend connection.
            The dashboard needs a running FastAPI backend to display live data.
          </p>
          <div style={{
            background: '#161b22',
            border: '1px solid #30363d',
            borderRadius: 8,
            padding: '12px 20px',
            fontSize: 11,
            color: '#484f58',
            maxWidth: 500,
            wordBreak: 'break-all',
          }}>
            {String(this.state.error)}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{
              background: '#58a6ff',
              color: '#0d1117',
              border: 'none',
              borderRadius: 6,
              padding: '8px 20px',
              fontWeight: 700,
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
