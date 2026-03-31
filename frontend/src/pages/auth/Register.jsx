import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import axios from 'axios'

export default function Register({ onSwitch }) {
  const { login } = useAuth()
  const [form, setForm] = useState({ email: '', password: '', confirm: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const set = (field) => (e) => setForm(p => ({ ...p, [field]: e.target.value }))

  const handleSubmit = async () => {
    if (!form.email || !form.password) { setError('All fields required'); return }
    if (form.password.length < 8) { setError('Password must be at least 8 characters'); return }
    if (form.password !== form.confirm) { setError('Passwords do not match'); return }
    try {
      setLoading(true)
      setError(null)
      const { data } = await axios.post('/api/auth/register', {
        email: form.email,
        password: form.password,
      })
      login(data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  const handleGoogle = () => {
    window.location.href = '/api/auth/google'
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSubmit()
  }

  return (
    <div className="auth-card">
      <div className="auth-brand">
        <span className="brand-mark">S</span>
        <span className="brand-name">SubsTrack</span>
      </div>

      <h1 className="auth-title">Create account</h1>
      <p className="auth-subtitle">Start tracking your subscriptions</p>

      {error && <p className="auth-error">{error}</p>}

      <div className="auth-fields">
        <input
          className="form-input"
          type="email"
          placeholder="Email"
          value={form.email}
          onChange={set('email')}
          onKeyDown={handleKeyDown}
          autoFocus
        />
        <input
          className="form-input"
          type="password"
          placeholder="Password (min 8 characters)"
          value={form.password}
          onChange={set('password')}
          onKeyDown={handleKeyDown}
        />
        <input
          className="form-input"
          type="password"
          placeholder="Confirm password"
          value={form.confirm}
          onChange={set('confirm')}
          onKeyDown={handleKeyDown}
        />
      </div>

      <button className="btn-primary auth-btn" onClick={handleSubmit} disabled={loading}>
        {loading ? 'Creating account...' : 'Create account'}
      </button>

      <div className="auth-divider"><span>or</span></div>

      <button className="btn-google" onClick={handleGoogle}>
        <GoogleIcon />
        Continue with Google
      </button>

      <p className="auth-switch">
        Already have an account?{' '}
        <button className="link-btn" onClick={onSwitch}>Sign in</button>
      </p>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
    </svg>
  )
}
