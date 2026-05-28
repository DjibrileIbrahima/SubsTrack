import { useState } from 'react'
import { requestPasswordReset } from '../../api'

export default function ForgotPassword({ onBack }) {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async () => {
    if (!email) { setError('Email is required'); return }
    try {
      setLoading(true)
      setError(null)
      await requestPasswordReset(email)
      setSent(true)
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  if (sent) {
    return (
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark">S</span>
          <span className="brand-name">SubsTrack</span>
        </div>
        <h1 className="auth-title">Check your email</h1>
        <p className="auth-subtitle">
          If an account exists for <strong>{email}</strong>, we sent a password reset link. Check your inbox.
        </p>
        <button className="btn-primary auth-btn" onClick={onBack}>Back to sign in</button>
      </div>
    )
  }

  return (
    <div className="auth-card">
      <div className="auth-brand">
        <span className="brand-mark">S</span>
        <span className="brand-name">SubsTrack</span>
      </div>
      <h1 className="auth-title">Forgot password?</h1>
      <p className="auth-subtitle">Enter your email and we'll send you a reset link.</p>
      {error && <p className="auth-error">{error}</p>}
      <div className="auth-fields">
        <input
          className="form-input"
          type="email"
          placeholder="Email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSubmit()}
          autoFocus
        />
      </div>
      <button className="btn-primary auth-btn" onClick={handleSubmit} disabled={loading}>
        {loading ? 'Sending...' : 'Send reset link'}
      </button>
      <p className="auth-switch">
        <button className="link-btn" onClick={onBack}>← Back to sign in</button>
      </p>
    </div>
  )
}
