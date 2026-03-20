import { useEffect, useRef, useState, useCallback } from 'react'

// Read from env. For Cloudflare Pages with no backend, VITE_WS_URL will be empty
// → we derive from window.location, but only attempt WS if a backend URL is set
const API_BASE = import.meta.env.VITE_API_URL || ''
const WS_BASE = import.meta.env.VITE_WS_URL ||
  (API_BASE
    ? API_BASE.replace(/^http/, 'ws')
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`)

// Exponential backoff: 3s → 6s → 12s → ... max 30s
function getDelay(attempt) {
  return Math.min(3000 * Math.pow(2, attempt), 30000)
}

export function useWebSocket(topics = ['detections', 'alerts', 'scores', 'cameras']) {
  const wsRef = useRef(null)
  const [connected, setConnected] = useState(false)
  const [lastDetection, setLastDetection] = useState(null)
  const [lastAlert, setLastAlert] = useState(null)
  const [lastScore, setLastScore] = useState(null)
  const [cameraFrame, setCameraFrame] = useState(null)
  const reconnectTimer = useRef(null)
  const attemptRef = useRef(0)
  const unmountedRef = useRef(false)
  const clientId = useRef(`ui_${Math.random().toString(36).substring(2, 10)}`)

  const connect = useCallback(() => {
    if (unmountedRef.current) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const url = `${WS_BASE}/ws/${clientId.current}`

    let ws
    try {
      ws = new WebSocket(url)
    } catch (e) {
      // Invalid URL or blocked — don't crash
      return
    }
    wsRef.current = ws

    ws.onopen = () => {
      if (unmountedRef.current) { ws.close(); return }
      attemptRef.current = 0
      setConnected(true)
      try { ws.send(JSON.stringify({ action: 'subscribe', topics })) } catch (_) {}
    }

    ws.onclose = () => {
      if (unmountedRef.current) return
      setConnected(false)
      const delay = getDelay(attemptRef.current)
      attemptRef.current += 1
      reconnectTimer.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      // onclose fires right after; no extra action needed
    }

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        switch (msg.type) {
          case 'detection':
            setLastDetection(msg)
            if (topics.includes('cameras')) setCameraFrame(msg)
            break
          case 'score_update':
            setLastScore(msg)
            break
          case 'new_alert':
            setLastAlert(msg.alert)
            break
          default:
            break
        }
      } catch (_) {}
    }
  }, [topics.join(',')])

  useEffect(() => {
    unmountedRef.current = false
    connect()
    return () => {
      unmountedRef.current = true
      clearTimeout(reconnectTimer.current)
      if (wsRef.current) {
        wsRef.current.onclose = null  // prevent reconnect on intentional close
        wsRef.current.close()
      }
    }
  }, [connect])

  return { connected, lastDetection, lastAlert, lastScore, cameraFrame }
}
