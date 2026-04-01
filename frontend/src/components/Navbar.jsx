import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../context/AuthContext'
import { getAlerts, markAlertRead } from '../api'

export default function Navbar() {
  const { user, logout } = useAuth()
  const [alerts, setAlerts] = useState([])
  const [alertsOpen, setAlertsOpen] = useState(false)
  const [userOpen, setUserOpen] = useState(false)
  const navRef = useRef(null)

  useEffect(() => {
    getAlerts().catch(() => setAlerts([]))
  }, [])

  // Close dropdowns when clicking outside the navbar
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (navRef.current && !navRef.current.contains(e.target)) {
        setAlertsOpen(false)
        setUserOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const unread = alerts.filter(a => !a.is_read).length

  const handleRead = async (id) => {
    await markAlertRead(id).catch(() => {})
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, is_read: true } : a))
  }

  return (
    <nav className="navbar" ref={navRef}>
      <div className="navbar-brand">
        <span className="brand-mark">S</span>
        <span className="brand-name">SubsTrack</span>
      </div>

      <div className="navbar-actions">
        {/* Alerts bell */}
        <button className="bell-btn" onClick={() => { setAlertsOpen(o => !o); setUserOpen(false) }}>
          <BellIcon />
          {unread > 0 && <span className="badge">{unread}</span>}
        </button>

        {alertsOpen && (
          <div className="alerts-dropdown">
            <p className="alerts-title">Upcoming Charges</p>
            {alerts.length === 0 ? (
              <p className="alerts-empty">No upcoming alerts</p>
            ) : (
              alerts.map(alert => (
                <div key={alert.id} className={`alert-item ${alert.is_read ? 'read' : ''}`}>
                  <span>{alert.message}</span>
                  {!alert.is_read && (
                    <button onClick={() => handleRead(alert.id)} className="dismiss-btn">✕</button>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {/* User menu */}
        <button className="user-btn" onClick={() => { setUserOpen(o => !o); setAlertsOpen(false) }}>
          <span className="user-avatar">{user?.email?.[0]?.toUpperCase() ?? 'U'}</span>
        </button>

        {userOpen && (
          <div className="user-dropdown">
            <p className="user-email">{user?.email}</p>
            <button className="logout-btn" onClick={logout}>Sign out</button>
          </div>
        )}
      </div>
    </nav>
  )
}

function BellIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
      <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
    </svg>
  )
}