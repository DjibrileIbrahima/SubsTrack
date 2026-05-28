import { useState } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import AuthPage from './pages/auth/AuthPage'
import OAuthCallback from './pages/auth/OAuthCallback'
import ResetPassword from './pages/auth/ResetPassword'
import Navbar from './components/Navbar'
import Dashboard from './pages/Dashboard'
import Settings from './pages/Settings'
import './index.css'

function AppContent() {
  const { isAuthenticated, loading } = useAuth()
  const [page, setPage] = useState('dashboard')

  if (window.location.pathname === '/auth/callback') {
    return <OAuthCallback />
  }

  const resetToken = new URLSearchParams(window.location.search).get('token')
  if (resetToken) {
    return (
      <div className="auth-bg">
        <ResetPassword token={resetToken} onSuccess={() => {
          window.history.replaceState({}, '', '/')
          window.location.reload()
        }} />
      </div>
    )
  }

  if (loading) {
    return (
      <div className="auth-bg">
        <div className="auth-card" style={{ textAlign: 'center' }}>
          <div className="auth-brand">
            <span className="brand-mark">S</span>
            <span className="brand-name">SubsTrack</span>
          </div>
          <p style={{ color: 'var(--text-muted)', marginTop: 16 }}>Loading...</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return <AuthPage />
  }

  return (
    <div className="app">
      <Navbar onNavigate={setPage} currentPage={page} />
      {page === 'settings'
        ? <Settings onNavigate={setPage} />
        : <Dashboard />
      }
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
