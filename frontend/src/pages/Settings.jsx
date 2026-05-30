import { useState, useEffect } from 'react'
import QRCode from 'react-qr-code'
import { useAuth } from '../context/AuthContext'
import { updateMe, getAccounts, unlinkAccount, setupMfa, enableMfa, disableMfa } from '../api'

export default function Settings({ onNavigate }) {
  const { user, updateUser } = useAuth()

  const [alertEmail, setAlertEmail] = useState(user?.alert_email ?? false)
  const [alertSms, setAlertSms] = useState(user?.alert_sms ?? false)
  const [phone, setPhone] = useState(user?.phone ?? '')
  const [saving, setSaving] = useState(false)
  const [success, setSuccess] = useState('')
  const [error, setError] = useState('')

  const [accounts, setAccounts] = useState([])
  const [unlinking, setUnlinking] = useState(null)
  const [unlinkError, setUnlinkError] = useState('')

  // MFA state
  const [mfaStep, setMfaStep] = useState('idle') // 'idle' | 'setup' | 'disable'
  const [mfaSetupData, setMfaSetupData] = useState(null) // { secret, uri }
  const [mfaCode, setMfaCode] = useState('')
  const [mfaLoading, setMfaLoading] = useState(false)
  const [mfaError, setMfaError] = useState('')
  const [mfaEnabled, setMfaEnabled] = useState(user?.mfa_enabled ?? false)

  useEffect(() => {
    getAccounts().then(setAccounts).catch(() => {})
  }, [])

  const handleMfaSetup = async () => {
    setMfaLoading(true)
    setMfaError('')
    try {
      const data = await setupMfa()
      setMfaSetupData(data)
      setMfaCode('')
      setMfaStep('setup')
    } catch (e) {
      setMfaError(e.response?.data?.detail || 'Failed to start MFA setup')
    } finally {
      setMfaLoading(false)
    }
  }

  const handleMfaEnable = async () => {
    if (mfaCode.length !== 6) { setMfaError('Enter the 6-digit code'); return }
    setMfaLoading(true)
    setMfaError('')
    try {
      await enableMfa(mfaSetupData.secret, mfaCode)
      setMfaEnabled(true)
      setMfaStep('idle')
      setMfaSetupData(null)
      setMfaCode('')
    } catch (e) {
      setMfaError(e.response?.data?.detail || 'Invalid code — try again')
    } finally {
      setMfaLoading(false)
    }
  }

  const handleMfaDisable = async () => {
    if (mfaCode.length !== 6) { setMfaError('Enter the 6-digit code'); return }
    setMfaLoading(true)
    setMfaError('')
    try {
      await disableMfa(mfaCode)
      setMfaEnabled(false)
      setMfaStep('idle')
      setMfaCode('')
    } catch (e) {
      setMfaError(e.response?.data?.detail || 'Invalid code — try again')
    } finally {
      setMfaLoading(false)
    }
  }

  const handleUnlink = async (id) => {
    setUnlinking(id)
    setUnlinkError('')
    try {
      await unlinkAccount(id)
      setAccounts(prev => prev.filter(a => a.id !== id))
    } catch {
      setUnlinkError('Failed to unlink account.')
    } finally {
      setUnlinking(null)
    }
  }

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
          <div>
            <div className="settings-row">
              <span className="settings-label">Linked banks</span>
            </div>
            {unlinkError && <p className="form-error" style={{ marginBottom: 8 }}>{unlinkError}</p>}
            {accounts.map(a => (
              <div key={a.id} className="settings-row settings-account-row">
                <span className="settings-value">{a.institution || a.institution_name}</span>
                <button
                  className="unlink-btn"
                  onClick={() => handleUnlink(a.id)}
                  disabled={unlinking === a.id}
                  aria-label={`Unlink ${a.institution || a.institution_name}`}
                >
                  {unlinking === a.id ? 'Unlinking…' : 'Unlink'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Security — MFA */}
      <div className="settings-card">
        <p className="settings-card-title">Two-Factor Authentication</p>

        {mfaStep === 'idle' && (
          <div className="settings-row">
            <div className="settings-row-text">
              <span className="settings-label">Authenticator app</span>
              <span className="settings-hint">
                {mfaEnabled ? 'Your account is protected with TOTP.' : 'Add an extra layer of security.'}
              </span>
            </div>
            {mfaEnabled ? (
              <button className="unlink-btn" onClick={() => { setMfaStep('disable'); setMfaCode(''); setMfaError('') }}>
                Disable
              </button>
            ) : (
              <button className="btn-ghost" style={{ fontSize: 13 }} onClick={handleMfaSetup} disabled={mfaLoading}>
                {mfaLoading ? 'Loading…' : 'Enable'}
              </button>
            )}
          </div>
        )}

        {mfaStep === 'setup' && mfaSetupData && (
          <div>
            <p className="settings-hint" style={{ marginBottom: 16 }}>
              Scan this QR code with Google Authenticator, Authy, or any TOTP app.
              Then enter the 6-digit code to confirm.
            </p>
            <div style={{ background: '#fff', padding: 12, borderRadius: 8, display: 'inline-block', marginBottom: 16 }}>
              <QRCode value={mfaSetupData.uri} size={180} />
            </div>
            <p className="settings-hint" style={{ marginBottom: 8 }}>
              Can't scan? Enter this key manually: <code style={{ userSelect: 'all' }}>{mfaSetupData.secret}</code>
            </p>
            {mfaError && <p className="form-error" style={{ marginBottom: 8 }}>{mfaError}</p>}
            <input
              className="form-input"
              type="text"
              inputMode="numeric"
              placeholder="6-digit code"
              maxLength={6}
              value={mfaCode}
              onChange={e => setMfaCode(e.target.value.replace(/\D/g, ''))}
              onKeyDown={e => e.key === 'Enter' && handleMfaEnable()}
              style={{ marginBottom: 12 }}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn-primary" style={{ fontSize: 13, padding: '6px 16px' }} onClick={handleMfaEnable} disabled={mfaLoading}>
                {mfaLoading ? 'Verifying…' : 'Confirm & enable'}
              </button>
              <button className="btn-ghost" style={{ fontSize: 13, padding: '6px 16px' }} onClick={() => { setMfaStep('idle'); setMfaError('') }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {mfaStep === 'disable' && (
          <div>
            <p className="settings-hint" style={{ marginBottom: 12 }}>
              Enter the current code from your authenticator app to disable MFA.
            </p>
            {mfaError && <p className="form-error" style={{ marginBottom: 8 }}>{mfaError}</p>}
            <input
              className="form-input"
              type="text"
              inputMode="numeric"
              placeholder="6-digit code"
              maxLength={6}
              value={mfaCode}
              onChange={e => setMfaCode(e.target.value.replace(/\D/g, ''))}
              onKeyDown={e => e.key === 'Enter' && handleMfaDisable()}
              style={{ marginBottom: 12 }}
              autoFocus
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn-primary" style={{ fontSize: 13, padding: '6px 16px', background: 'var(--danger)' }} onClick={handleMfaDisable} disabled={mfaLoading}>
                {mfaLoading ? 'Disabling…' : 'Disable MFA'}
              </button>
              <button className="btn-ghost" style={{ fontSize: 13, padding: '6px 16px' }} onClick={() => { setMfaStep('idle'); setMfaError('') }}>
                Cancel
              </button>
            </div>
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
