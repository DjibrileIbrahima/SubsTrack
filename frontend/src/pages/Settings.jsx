import { useState, useEffect } from 'react'
import QRCode from 'react-qr-code'
import { useAuth } from '../context/AuthContext'
import { usePlaid } from '../hooks/usePlaid'
import { updateMe, getAccounts, unlinkAccount, setupMfa, enableMfa, disableMfa, deleteAccount } from '../api'

const ACCOUNT_STATUS_LABELS = {
  login_required: 'Reconnect required',
  pending_expiration: 'Access expiring soon',
  revoked: 'Access revoked',
}

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

  // Delete-account state
  const [deleteStep, setDeleteStep] = useState('idle') // 'idle' | 'confirm'
  const [deletePassword, setDeletePassword] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  useEffect(() => {
    getAccounts().then(setAccounts).catch(() => {})
  }, [])

  const { openUpdate, error: plaidError } = usePlaid(() => {
    getAccounts().then(setAccounts).catch(() => {})
  })

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

  const handleDeleteAccount = async () => {
    if (user?.has_password && !deletePassword) {
      setDeleteError('Enter your password to confirm.')
      return
    }
    setDeleting(true)
    setDeleteError('')
    try {
      await deleteAccount(user?.has_password ? deletePassword : undefined)
      // Cookies are cleared server-side; drop the user so the app returns to auth.
      updateUser(null)
    } catch (e) {
      setDeleteError(e.response?.data?.detail || 'Failed to delete account.')
      setDeleting(false)
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
            {plaidError && <p className="form-error" style={{ marginBottom: 8 }}>{plaidError}</p>}
            {accounts.map(a => (
              <div key={a.id} className="settings-row settings-account-row">
                <span className="settings-value">{a.institution || a.institution_name}</span>
                {a.status && a.status !== 'active' && (
                  <span className="settings-hint" style={{ color: 'var(--danger)' }}>
                    {ACCOUNT_STATUS_LABELS[a.status] || a.status}
                  </span>
                )}
                {(a.status === 'login_required' || a.status === 'pending_expiration') && (
                  <button
                    className="btn-ghost"
                    style={{ fontSize: 13 }}
                    onClick={() => openUpdate(a.id)}
                    aria-label={`Reconnect ${a.institution || a.institution_name}`}
                  >
                    Reconnect
                  </button>
                )}
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

      {/* Danger zone */}
      <div className="settings-card" style={{ borderColor: 'var(--danger)' }}>
        <p className="settings-card-title">Delete account</p>

        {deleteStep === 'idle' && (
          <div className="settings-row">
            <div className="settings-row-text">
              <span className="settings-hint">
                Permanently delete your account, disconnect your banks, and erase all
                subscription data. This can't be undone.
              </span>
            </div>
            <button
              className="unlink-btn"
              onClick={() => { setDeleteStep('confirm'); setDeletePassword(''); setDeleteError('') }}
            >
              Delete account
            </button>
          </div>
        )}

        {deleteStep === 'confirm' && (
          <div>
            <p className="settings-hint" style={{ marginBottom: 12 }}>
              This permanently deletes your account and disconnects your banks.
              This action cannot be undone.
            </p>
            {user?.has_password && (
              <input
                className="form-input"
                type="password"
                placeholder="Enter your password to confirm"
                value={deletePassword}
                onChange={e => setDeletePassword(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleDeleteAccount()}
                style={{ marginBottom: 12 }}
                autoFocus
              />
            )}
            {deleteError && <p className="form-error" style={{ marginBottom: 8 }}>{deleteError}</p>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                className="btn-primary"
                style={{ fontSize: 13, padding: '6px 16px', background: 'var(--danger)' }}
                onClick={handleDeleteAccount}
                disabled={deleting}
              >
                {deleting ? 'Deleting…' : 'Permanently delete'}
              </button>
              <button
                className="btn-ghost"
                style={{ fontSize: 13, padding: '6px 16px' }}
                onClick={() => { setDeleteStep('idle'); setDeleteError('') }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
