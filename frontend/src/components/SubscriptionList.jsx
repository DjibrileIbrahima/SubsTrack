import { useState } from 'react'
import { deleteSubscription, updateSubscription } from '../api'

const FREQ_COLORS = {
  monthly: '#3b82f6',
  weekly: '#10b981',
  biweekly: '#14b8a6',
  quarterly: '#8b5cf6',
  yearly: '#f59e0b',
}

const FREQS = ['weekly', 'biweekly', 'monthly', 'quarterly', 'yearly']

export default function SubscriptionList({ subscriptions = [], onRefresh, hasAccounts = false, onSync, syncing = false }) {
  const [deleting, setDeleting] = useState(null)
  const [deleteError, setDeleteError] = useState('')
  const [editing, setEditing] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState('')

  const handleDelete = async (id) => {
    setDeleting(id)
    setDeleteError('')
    try {
      await deleteSubscription(id)
      await onRefresh?.()
    } catch {
      setDeleteError('Failed to delete subscription.')
    } finally {
      setDeleting(null)
    }
  }

  const startEdit = (sub) => {
    setEditing(sub.id)
    setEditError('')
    setEditForm({
      merchant: sub.merchant || '',
      amount: sub.amount ?? '',
      frequency: sub.frequency || 'monthly',
      next_expected: sub.next_expected || '',
      category: sub.category || '',
    })
  }

  const setField = (field) => (e) => setEditForm(prev => ({ ...prev, [field]: e.target.value }))

  const handleSave = async (id) => {
    setSaving(true)
    setEditError('')
    try {
      const payload = {
        merchant: editForm.merchant,
        amount: Number(editForm.amount),
        frequency: editForm.frequency,
        category: editForm.category || null,
        ...(editForm.next_expected ? { next_expected: editForm.next_expected } : {}),
      }
      await updateSubscription(id, payload)
      await onRefresh?.()
      setEditing(null)
    } catch (e) {
      setEditError(e.response?.data?.detail || 'Failed to save changes.')
    } finally {
      setSaving(false)
    }
  }

  if (!subscriptions.length) {
    return (
      <div className="empty-state">
        <p>{hasAccounts ? 'No subscriptions detected yet.' : 'No bank account connected.'}</p>
        <p className="empty-sub">
          {hasAccounts
            ? <>Try syncing your transactions or add a subscription manually.<br />
                <button
                  className="btn-ghost"
                  style={{ marginTop: 12 }}
                  onClick={onSync}
                  disabled={syncing}
                >
                  {syncing ? 'Syncing...' : '↻ Sync Now'}
                </button>
              </>
            : 'Connect a bank account above to detect subscriptions automatically.'}
        </p>
      </div>
    )
  }

  return (
    <>
      {deleteError && (
        <p style={{ color: 'var(--danger)', fontSize: 13, marginBottom: 12 }}>
          {deleteError}
        </p>
      )}

      <div className="sub-list">
        {subscriptions.map((sub) => (
          <div key={sub.id || `${sub.merchant}-${sub.next_expected}`} className="sub-card">
            {editing === sub.id ? (
              <div style={{ width: '100%' }}>
                {editError && <p className="form-error">{editError}</p>}
                <div className="form-grid">
                  <input
                    className="form-input"
                    placeholder="Merchant"
                    value={editForm.merchant}
                    onChange={setField('merchant')}
                    disabled={saving}
                  />
                  <input
                    className="form-input"
                    type="number"
                    step="0.01"
                    placeholder="Amount"
                    value={editForm.amount}
                    onChange={setField('amount')}
                    disabled={saving}
                  />
                  <select
                    className="form-input"
                    value={editForm.frequency}
                    onChange={setField('frequency')}
                    disabled={saving}
                  >
                    {FREQS.map(f => (
                      <option key={f} value={f}>{f.charAt(0).toUpperCase() + f.slice(1)}</option>
                    ))}
                  </select>
                  <input
                    className="form-input"
                    type="date"
                    value={editForm.next_expected}
                    onChange={setField('next_expected')}
                    disabled={saving}
                  />
                  <input
                    className="form-input"
                    placeholder="Category"
                    value={editForm.category}
                    onChange={setField('category')}
                    disabled={saving}
                  />
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button
                    className="btn-primary"
                    style={{ padding: '6px 16px', fontSize: 13 }}
                    onClick={() => handleSave(sub.id)}
                    disabled={saving}
                  >
                    {saving ? 'Saving...' : 'Save'}
                  </button>
                  <button
                    className="btn-ghost"
                    style={{ padding: '6px 16px', fontSize: 13 }}
                    onClick={() => setEditing(null)}
                    disabled={saving}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                <div className="sub-left">
                  <div className="sub-avatar">
                    {sub.merchant?.[0]?.toUpperCase() || '?'}
                  </div>

                  <div>
                    <p className="sub-merchant">{sub.merchant}</p>
                    <p className="sub-meta">
                      {sub.category || 'Unknown'} · next {sub.next_expected || '—'}
                    </p>

                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                      <span className="mini-badge">
                        {sub.source === 'manual' ? 'Manual' : 'Bank'}
                      </span>

                      {typeof sub.confidence === 'number' && (
                        <span className="mini-badge">
                          {Math.round(sub.confidence * 100)}% confidence
                        </span>
                      )}

                      {sub.detection_method && (
                        <span className="mini-badge">
                          {sub.detection_method}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <div className="sub-right">
                  <span
                    className="freq-badge"
                    style={{ '--badge-color': FREQ_COLORS[sub.frequency] || '#6b7280' }}
                  >
                    {sub.frequency}
                  </span>

                  <p className="sub-amount">${Number(sub.amount || 0).toFixed(2)}</p>

                  {sub.id && (
                    <>
                      <button
                        className="edit-btn"
                        onClick={() => startEdit(sub)}
                        title="Edit subscription"
                        aria-label="Edit subscription"
                      >
                        ✎
                      </button>
                      <button
                        className="delete-btn"
                        onClick={() => handleDelete(sub.id)}
                        disabled={deleting === sub.id}
                        title="Remove subscription"
                      >
                        {deleting === sub.id ? '...' : '✕'}
                      </button>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </>
  )
}
