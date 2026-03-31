import { useEffect } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import AuthPage from './pages/auth/AuthPage'
import OAuthCallback from './pages/auth/OAuthCallback'
import Navbar from './components/Navbar'
import Dashboard from './pages/Dashboard'
import './index.css'

function AppContent() {
  const { isAuthenticated, loading } = useAuth()

  // Handle Google OAuth callback
  if (window.location.pathname === '/auth/callback') {
    return <OAuthCallback />
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
      <Navbar />
      <Dashboard />
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
