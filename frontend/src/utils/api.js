import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 10000,
})

// Persons
export const personAPI = {
  list:       (params = {}) => api.get('/persons', { params }),
  get:        (id) => api.get(`/persons/${id}`),
  timeline:   (id) => api.get(`/persons/${id}/timeline`),
  confidence: (id) => api.get(`/persons/${id}/confidence`),
  events:     (id) => api.get(`/persons/${id}/events`),
  scores:     (id) => api.get(`/persons/${id}/score-history`),
  liveScores: ()  => api.get('/persons/live-scores'),
  stats:      ()  => api.get('/persons/stats'),
  updateType: (id, type) => api.patch(`/persons/${id}/type`, null, { params: { person_type: type } }),
}

// Alerts
export const alertAPI = {
  list:        (params = {}) => api.get('/alerts', { params }),
  stats:       () => api.get('/alerts/stats'),
  topIncidents:() => api.get('/alerts/top-incidents'),
  get:         (id) => api.get(`/alerts/${id}`),
  acknowledge: (id, by = 'operator') => api.post(`/alerts/${id}/acknowledge`, null, { params: { acknowledged_by: by } }),
}

// Analytics
export const analyticsAPI = {
  heatmap:        (params = {}) => api.get('/analytics/heatmap', { params }),
  heatmapHourly:  (day) => api.get('/analytics/heatmap/hourly', { params: { day } }),
  hotspots:       (day) => api.get('/analytics/heatmap/hotspots', { params: { day } }),
  repeatVisitors: () => api.get('/analytics/repeat-visitors'),
  flaggedVisitors:() => api.get('/analytics/repeat-visitors/flagged'),
  reports:        () => api.get('/analytics/reports'),
  getReport:      (date) => api.get(`/analytics/reports/${date}`),
  generateReport: (date) => api.post('/analytics/reports/generate', null, { params: { date } }),
  storeHealth:    (params = {}) => api.get('/analytics/store-health', { params }),
}

// Events
export const eventsAPI = {
  list:  (params = {}) => api.get('/events', { params }),
  get:   (id) => api.get(`/events/${id}`),
  media: (params = {}) => api.get('/media', { params }),
}

// Cameras
export const cameraAPI = {
  wsStatus:     ()              => api.get('/ws/status'),
  list:         ()              => api.get('/cameras'),
  get:          (id)            => api.get(`/cameras/${id}`),
  add:          (data)          => api.post('/cameras', data),
  remove:       (id)            => api.delete(`/cameras/${id}`),
  restart:      (id)            => api.post(`/cameras/${id}/restart`),
  snapshotB64:  (id, q = 70)    => api.get(`/cameras/${id}/snapshot.b64`, { params: { quality: q } }),
  intentStats:  ()              => api.get('/cameras/intent/stats'),
  getZones:     (id)            => api.get(`/cameras/${id}/zones`),
  saveZones:    (id, zones)     => api.put(`/cameras/${id}/zones`, zones),
  getZoneLabels: (id)           => api.get(`/cameras/${id}/zone-labels`),
  saveZoneLabels: (id, labels)  => api.put(`/cameras/${id}/zone-labels`, { labels }),
  discoverOnvif:(u = '', p = '') => api.post('/cameras/discover/onvif', { username: u, password: p }),
}

// System
export const systemAPI = {
  health:  () => api.get('/health'),
  status:  () => api.get('/system-status'),
}

export default api
