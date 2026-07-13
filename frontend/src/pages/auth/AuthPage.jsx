import { useState, useEffect } from 'react'
import Login from './Login'
import Register from './Register'
import ForgotPassword from './ForgotPassword'
import ResetPassword from './ResetPassword'

function getParam(name) {
  return new URLSearchParams(window.location.search).get(name)
}

function clearToken() {
  window.history.replaceState({}, '', window.location.pathname)
}

export default function AuthPage() {
  const [view, setView] = useState(() => getParam('token') ? 'reset' : 'login')
  const [token] = useState(() => getParam('token'))
  // One-time second-factor token from the Google OAuth redirect (?mfa_token=...)
  const [mfaToken] = useState(() => getParam('mfa_token'))
  const [resetDone, setResetDone] = useState(false)

  useEffect(() => {
    // Scrub the one-time token from the address bar and history once captured
    if (mfaToken) clearToken()
  }, [mfaToken])

  const handleResetSuccess = () => {
    clearToken()
    setResetDone(true)
    setView('login')
  }

  return (
    <div className="auth-bg">
      {view === 'login' && (
        <Login
          onSwitch={() => setView('register')}
          onForgot={() => setView('forgot')}
          successMessage={resetDone ? 'Password updated — sign in with your new password.' : null}
          initialMfaToken={mfaToken}
        />
      )}
      {view === 'register' && <Register onSwitch={() => setView('login')} />}
      {view === 'forgot' && <ForgotPassword onBack={() => setView('login')} />}
      {view === 'reset' && <ResetPassword token={token} onSuccess={handleResetSuccess} />}
    </div>
  )
}
