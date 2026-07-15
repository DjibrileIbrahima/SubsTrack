import axios from 'axios'

// All requests send the HttpOnly session cookie automatically.
// No Authorization header needed — auth is handled server-side via cookie.
const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

// Access tokens are short-lived; on a 401 we transparently rotate the refresh
// token via POST /auth/refresh and replay the original request once. Endpoints
// where a 401 is a legitimate business response (bad login, expired reset link,
// the refresh call itself) must NOT trigger a refresh attempt.
const NO_REFRESH_PATHS = [
  '/auth/refresh',
  '/auth/login',
  '/auth/register',
  '/auth/mfa/verify',
  '/auth/forgot-password',
  '/auth/reset-password',
]

let refreshPromise = null

// Guarded so the unit test's mocked axios instance (no interceptors) is a no-op.
if (api.interceptors) {
  api.interceptors.response.use(
    (response) => response,
    async (error) => {
      const { response, config } = error
      const url = config?.url || ''
      const skip = NO_REFRESH_PATHS.some((p) => url.includes(p))

      if (response?.status === 401 && config && !config._retry && !skip) {
        config._retry = true
        try {
          // De-dupe concurrent refreshes so a burst of 401s makes one call.
          refreshPromise = refreshPromise || api.post('/auth/refresh')
          await refreshPromise
          return api(config) // replay the original request with fresh cookies
        } catch (refreshError) {
          return Promise.reject(refreshError)
        } finally {
          refreshPromise = null
        }
      }
      return Promise.reject(error)
    }
  )
}

export default api

// Auth
export const getLinkToken = () =>
  api.post('/auth/link-token').then(r => r.data.link_token)

export const getUpdateLinkToken = (account_id) =>
  api.post('/auth/link-token/update', { account_id }).then(r => r.data.link_token)

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
  api.post('/subscriptions/sync').then(r => r.data)

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