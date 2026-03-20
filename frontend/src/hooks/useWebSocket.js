import { useEffect, useRef, useState, useCallback } from 'react'

const WS_BASE = import.meta.env.VITE_WS_URL ||
  `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

export function useWebSocket(topics = ['detections', 'alerts', 'scores', 'cameras']) {
  const wsRef = useRef(null)
  const [connected, setConnected] = useState(false)
  const [lastDetection, setLastDetection] = useState(null)
  const [lastAlert, setLastAlert] = useState(null)
  const [lastScore, setLastScore] = useState(null)
  const [cameraFrame, setCameraFrame] = useState(null)
  const reconnectTimer = useRef(null)
  const clientId = useRef(`ui_${Math.random().toString(36).substring(2, 10)}`)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const url = `${WS_BASE}/ws/${clientId.current}`
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      ws.send(JSON.stringify({ action: 'subscribe', topics }))
    }

    ws.onclose = () => {
      setConnected(false)
      reconnectTimer.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      ws.close()
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
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { connected, lastDetection, lastAlert, lastScore, cameraFrame }
}
