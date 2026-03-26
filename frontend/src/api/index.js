import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// Auth
export const getLinkToken = () =>
  fetch('/api/auth/link-token', { method: 'POST' })
    .then(r => r.json())
    .then(d => d.link_token)

export const exchangeToken = (public_token, institution_name) =>
  api.post('/auth/exchange-token', { public_token, institution_name })

export const getAccounts = () =>
  api.get('/auth/accounts').then(r => r.data.accounts)

// Subscriptions — reads from DB (fast, no Plaid call)
export const getSavedSubscriptions = () =>
  api.get('/subscriptions/saved').then(r => r.data)

// Sync — calls Plaid and updates DB
export const syncSubscriptions = () =>
  api.get('/subscriptions').then(r => r.data)

export const addManualSubscription = (data) =>
  api.post('/subscriptions/manual', data).then(r => r.data)

export const deleteSubscription = (id) =>
  api.delete(`/subscriptions/${id}`).then(r => r.data)

// Summary
export const getSummary = () =>
  api.get('/summary').then(r => r.data.monthly_summary)

// Alerts
export const getAlerts = () =>
  api.get('/alerts').then(r => r.data.alerts)

export const markAlertRead = (id) =>
  api.patch(`/alerts/${id}/read`).then(r => r.data)