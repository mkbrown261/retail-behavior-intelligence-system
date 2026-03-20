import { useEffect, useRef, useReducer, useCallback } from 'react'

const MAX_PERSONS = 50
const MAX_ALERTS  = 30

function reducer(state, action) {
  switch (action.type) {
    case 'UPSERT_PERSON': {
      const existing = state.persons.findIndex(p => p.session_id === action.payload.session_id)
      const persons = [...state.persons]
      if (existing >= 0) {
        persons[existing] = { ...persons[existing], ...action.payload }
      } else {
        persons.unshift(action.payload)
        if (persons.length > MAX_PERSONS) persons.pop()
      }
      return { ...state, persons }
    }
    case 'UPDATE_SCORE': {
      const { session_id, score, level } = action.payload
      const persons = state.persons.map(p =>
        p.session_id === session_id
          ? { ...p, current_suspicion_score: score, suspicion_level: level }
          : p
      )
      return { ...state, persons }
    }
    case 'ADD_ALERT': {
      const alerts = [action.payload, ...state.alerts].slice(0, MAX_ALERTS)
      return { ...state, alerts }
    }
    case 'SET_ALERTS': {
      return { ...state, alerts: action.payload }
    }
    case 'SET_PERSONS': {
      return { ...state, persons: action.payload }
    }
    case 'SET_STATS': {
      return { ...state, stats: action.payload }
    }
    case 'SET_CONNECTED': {
      return { ...state, connected: action.payload }
    }
    default:
      return state
  }
}

const initialState = {
  persons: [],
  alerts: [],
  stats: {},
  connected: false,
}

export function useStore() {
  const [state, dispatch] = useReducer(reducer, initialState)

  const upsertPerson = useCallback((p) => dispatch({ type: 'UPSERT_PERSON', payload: p }), [])
  const updateScore  = useCallback((s) => dispatch({ type: 'UPDATE_SCORE',  payload: s }), [])
  const addAlert     = useCallback((a) => dispatch({ type: 'ADD_ALERT',     payload: a }), [])
  const setAlerts    = useCallback((a) => dispatch({ type: 'SET_ALERTS',    payload: a }), [])
  const setPersons   = useCallback((p) => dispatch({ type: 'SET_PERSONS',   payload: p }), [])
  const setStats     = useCallback((s) => dispatch({ type: 'SET_STATS',     payload: s }), [])

  return { state, upsertPerson, updateScore, addAlert, setAlerts, setPersons, setStats }
}
