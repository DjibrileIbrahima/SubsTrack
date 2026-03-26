import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

const USER_ID = 'default_user'

// Auth
export const getLinkToken = () =>
  api.get(`/auth/link-token?user_id=${USER_ID}`).then(r => r.data.link_token)

export const exchangeToken = (public_token, institution_name) =>
  api.post('/auth/exchange-token', { public_token, institution_name, user_id: USER_ID })

export const getAccounts = () =>
  api.get(`/auth/accounts?user_id=${USER_ID}`).then(r => r.data.accounts)

// Subscriptions
export const getSubscriptions = () =>
  api.get(`/subscriptions?user_id=${USER_ID}`).then(r => r.data)

export const addManualSubscription = (data) =>
  api.post(`/subscriptions/manual?user_id=${USER_ID}`, data).then(r => r.data)

export const deleteSubscription = (id) =>
  api.delete(`/subscriptions/${id}`).then(r => r.data)

// Summary
export const getSummary = () =>
  api.get(`/summary?user_id=${USER_ID}`).then(r => r.data.monthly_summary)

// Alerts
export const getAlerts = () =>
  api.get(`/alerts?user_id=${USER_ID}`).then(r => r.data.alerts)

export const markAlertRead = (id) =>
  api.patch(`/alerts/${id}/read`).then(r => r.data)
