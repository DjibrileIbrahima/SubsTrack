import axios from 'axios'

// All requests send the HttpOnly session cookie automatically.
// No Authorization header needed — auth is handled server-side via cookie.
const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

export default api

// Auth
export const getLinkToken = () =>
  api.post('/auth/link-token').then(r => r.data.link_token)

export const exchangeToken = (public_token, institution_name) =>
  api.post('/auth/exchange-token', { public_token, institution_name })

export const getAccounts = () =>
  api.get('/auth/accounts').then(r => r.data.accounts)

export const unlinkAccount = (id) =>
  api.delete(`/auth/accounts/${id}`).then(r => r.data)

export const updateMe = (data) =>
  api.patch('/auth/me', data).then(r => r.data)

export const requestPasswordReset = (email) =>
  api.post('/auth/forgot-password', { email }).then(r => r.data)

export const resetPassword = (token, password) =>
  api.post('/auth/reset-password', { token, password }).then(r => r.data)

// Subscriptions
export const getSavedSubscriptions = () =>
  api.get('/subscriptions/saved').then(r => r.data)

export const syncSubscriptions = () =>
  api.get('/subscriptions').then(r => r.data)

export const addManualSubscription = (data) =>
  api.post('/subscriptions/manual', data).then(r => r.data)

export const updateSubscription = (id, data) =>
  api.patch(`/subscriptions/${id}`, data).then(r => r.data)

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

export const deleteAlert = (id) =>
  api.delete(`/alerts/${id}`).then(r => r.data)

// MFA
export const setupMfa = () =>
  api.get('/auth/mfa/setup').then(r => r.data)

export const enableMfa = (secret, code) =>
  api.post('/auth/mfa/enable', { secret, code }).then(r => r.data)

export const disableMfa = (code) =>
  api.post('/auth/mfa/disable', { code }).then(r => r.data)

export const verifyMfa = (mfa_token, code) =>
  api.post('/auth/mfa/verify', { mfa_token, code }).then(r => r.data)