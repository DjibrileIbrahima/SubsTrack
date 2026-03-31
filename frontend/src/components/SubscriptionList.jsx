import { useState } from 'react'
import { deleteSubscription } from '../api'

const FREQ_COLORS = {
  monthly: '#3b82f6',
  weekly: '#10b981',
  biweekly: '#14b8a6',
  quarterly: '#8b5cf6',
  yearly: '#f59e0b',
}

export default function SubscriptionList({ subscriptions = [], onRefresh }) {
  const [deleting, setDeleting] = useState(null)
  const [error, setError] = useState('')

  const handleDelete = async (id) => {
    setDeleting(id)
    setError('')

    try {
      await deleteSubscription(id)
      await onRefresh?.()
    } catch {
      setError('Failed to delete subscription.')
    } finally {
      setDeleting(null)
    }
  }

  if (!subscriptions.length) {
    return (
      <div className="empty-state">
        <p>No subscriptions detected yet.</p>
        <p className="empty-sub">Connect a bank account or add one manually.</p>
      </div>
    )
  }

  return (
    <>
      {error && (
        <p style={{ color: 'var(--danger)', fontSize: 13, marginBottom: 12 }}>
          {error}
        </p>
      )}

      <div className="sub-list">
        {subscriptions.map((sub) => (
          <div key={sub.id || `${sub.merchant}-${sub.next_expected}`} className="sub-card">
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
                <button
                  className="delete-btn"
                  onClick={() => handleDelete(sub.id)}
                  disabled={deleting === sub.id}
                  title="Remove subscription"
                >
                  {deleting === sub.id ? '...' : '✕'}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}