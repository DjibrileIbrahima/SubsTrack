import { useState } from 'react'
import { resetPassword } from '../../api'

export default function ResetPassword({ token, onSuccess }) {
  const [form, setForm] = useState({ password: '', confirm: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const set = (field) => (e) => setForm(p => ({ ...p, [field]: e.target.value }))

  const handleSubmit = async () => {
    if (!form.password || !form.confirm) { setError('All fields required'); return }
    if (form.password.length < 8) { setError('Password must be at least 8 characters'); return }
    if (form.password !== form.confirm) { setError('Passwords do not match'); return }
    try {
      setLoading(true)
      setError(null)
      await resetPassword(token, form.password)
      onSuccess()
    } catch (e) {
      setError(e.response?.data?.detail || 'Invalid or expired reset link.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-card">
      <div className="auth-brand">
        <span className="brand-mark">S</span>
        <span className="brand-name">SubsTrack</span>
      </div>
      <h1 className="auth-title">Set new password</h1>
      <p className="auth-subtitle">Choose a strong password for your account.</p>
      {error && <p className="auth-error">{error}</p>}
      <div className="auth-fields">
        <input
          className="form-input"
          type="password"
          placeholder="New password"
          value={form.password}
          onChange={set('password')}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          autoFocus
        />
        <input
          className="form-input"
          type="password"
          placeholder="Confirm new password"
          value={form.confirm}
          onChange={set('confirm')}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
        />
      </div>
      <button className="btn-primary auth-btn" onClick={handleSubmit} disabled={loading}>
        {loading ? 'Saving...' : 'Set new password'}
      </button>
    </div>
  )
}
