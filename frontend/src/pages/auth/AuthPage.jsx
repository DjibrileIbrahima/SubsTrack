import { useState } from 'react'
import Login from './Login'
import Register from './Register'

export default function AuthPage() {
  const [view, setView] = useState('login')

  return (
    <div className="auth-bg">
      {view === 'login'
        ? <Login onSwitch={() => setView('register')} />
        : <Register onSwitch={() => setView('login')} />
      }
    </div>
  )
}
