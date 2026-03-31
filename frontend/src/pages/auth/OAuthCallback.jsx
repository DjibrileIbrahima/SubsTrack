import { useEffect } from 'react'
import { useAuth } from '../../context/AuthContext'

export default function OAuthCallback() {
  const { login } = useAuth()

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const token = params.get('token')
    if (token) {
      login({ access_token: token, email: '' })
      // Fetch real email from /me after login
    } else {
      window.location.href = '/'
    }
  }, [])

  return (
    <div className="auth-bg">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark">S</span>
          <span className="brand-name">SubsTrack</span>
        </div>
        <p style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          Signing you in...
        </p>
      </div>
    </div>
  )
}
