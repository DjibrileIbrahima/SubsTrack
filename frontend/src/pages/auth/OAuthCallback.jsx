import { useEffect } from 'react'

export default function OAuthCallback() {
  useEffect(() => { window.location.replace('/') }, [])

  return (
    <div className="auth-bg">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark">S</span>
          <span className="brand-name">SubsTrack</span>
        </div>
        <p style={{ textAlign: 'center', color: 'var(--text-muted)' }}>Signing you in...</p>
      </div>
    </div>
  )
}