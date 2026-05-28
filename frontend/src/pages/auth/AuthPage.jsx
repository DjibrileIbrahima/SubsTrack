import { useState } from 'react'
import Login from './Login'
import Register from './Register'
import ForgotPassword from './ForgotPassword'
import ResetPassword from './ResetPassword'

function getResetToken() {
  return new URLSearchParams(window.location.search).get('token')
}

function clearToken() {
  window.history.replaceState({}, '', window.location.pathname)
}

export default function AuthPage() {
  const [view, setView] = useState(() => getResetToken() ? 'reset' : 'login')
  const [token] = useState(getResetToken)
  const [resetDone, setResetDone] = useState(false)

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
        />
      )}
      {view === 'register' && <Register onSwitch={() => setView('login')} />}
      {view === 'forgot' && <ForgotPassword onBack={() => setView('login')} />}
      {view === 'reset' && <ResetPassword token={token} onSuccess={handleResetSuccess} />}
    </div>
  )
}
