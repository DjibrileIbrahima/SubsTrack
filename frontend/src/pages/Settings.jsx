import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { updateMe, getAccounts } from '../api'
import { useEffect } from 'react'

export default function Settings({ onNavigate }) {
  const { user, updateUser } = useAuth()

  const [alertEmail, setAlertEmail] = useState(user?.alert_email ?? false)
  const [alertSms, setAlertSms] = useState(user?.alert_sms ?? false)
  const [phone, setPhone] = useState(user?.phone ?? '')
  const [saving, setSaving] = useState(false)
  const [success, setSuccess] = useState('')
  const [error, setError] = useState('')

  const [accounts, setAccounts] = useState([])
  useEffect(() => {
    getAccounts().then(setAccounts).catch(() => {})
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setSuccess('')
    setError('')
    try {
      const data = await updateMe({
        alert_email: alertEmail,
        alert_sms: alertSms,
        phone: alertSms ? (phone || null) : null,
      })
      updateUser(data)
      setSuccess('Settings saved.')
    } catch {
      setError('Failed to save settings.')
    } finally {
      setSaving(false)
    }
  }

  const isDirty =
    alertEmail !== (user?.alert_email ?? false) ||
    alertSms !== (user?.alert_sms ?? false) ||
    phone !== (user?.phone ?? '')

  return (
    <main className="dashboard">
      <div className="section-header" style={{ marginBottom: 24 }}>
        <h2 className="section-title">Settings</h2>
        <button className="btn-ghost" onClick={() => onNavigate('dashboard')}>
          ← Back
        </button>
      </div>

      {/* Profile */}
      <div className="settings-card">
        <p className="settings-card-title">Profile</p>
        <div className="settings-row">
          <span className="settings-label">Email</span>
          <span className="settings-value">{user?.email}</span>
        </div>
        {accounts.length > 0 && (
          <div className="settings-row">
            <span className="settings-label">Linked bank</span>
            <span className="settings-value">
              {accounts.map(a => a.institution_name).join(', ')}
            </span>
          </div>
        )}
      </div>

      {/* Notifications */}
      <div className="settings-card">
        <p className="settings-card-title">Notifications</p>

        <div className="settings-row">
          <div className="settings-row-text">
            <span className="settings-label">Email alerts</span>
            <span className="settings-hint">Receive an email when a subscription is due</span>
          </div>
          <label className="toggle">
            <input
              type="checkbox"
              checked={alertEmail}
              onChange={e => setAlertEmail(e.target.checked)}
            />
            <span className="toggle-track" />
          </label>
        </div>

        <div className="settings-row">
          <div className="settings-row-text">
            <span className="settings-label">SMS alerts</span>
            <span className="settings-hint">Receive a text message reminder</span>
          </div>
          <label className="toggle">
            <input
              type="checkbox"
              checked={alertSms}
              onChange={e => setAlertSms(e.target.checked)}
            />
            <span className="toggle-track" />
          </label>
        </div>

        {alertSms && (
          <div className="settings-phone-row">
            <label className="settings-label" htmlFor="phone">Phone number</label>
            <input
              id="phone"
              className="form-input"
              type="tel"
              placeholder="+1 555 000 0000"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              maxLength={20}
            />
          </div>
        )}
      </div>

      {/* Save */}
      <div className="settings-actions">
        {success && <span className="settings-success">{success}</span>}
        {error && <span className="form-error">{error}</span>}
        <button
          className="btn-primary"
          onClick={handleSave}
          disabled={saving || !isDirty}
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </div>
    </main>
  )
}
