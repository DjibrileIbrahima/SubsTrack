import { useState } from 'react'
import { deleteSubscription } from '../api'

const FREQ_COLORS = {
  monthly: '#3b82f6',
  weekly: '#10b981',
  yearly: '#f59e0b',
  quarterly: '#8b5cf6',
}

export default function SubscriptionList({ subscriptions, onRefresh }) {
  const [deleting, setDeleting] = useState(null)

  const handleDelete = async (id) => {
    setDeleting(id)
    await deleteSubscription(id).catch(() => {})
    onRefresh?.()
    setDeleting(null)
  }

  if (!subscriptions?.length) {
    return (
      <div className="empty-state">
        <p>No subscriptions detected yet.</p>
        <p className="empty-sub">Connect a bank account or add one manually.</p>
      </div>
    )
  }

  return (
    <div className="sub-list">
      {subscriptions.map((sub, i) => (
        <div key={i} className="sub-card">
          <div className="sub-left">
            <div className="sub-avatar">{sub.merchant[0].toUpperCase()}</div>
            <div>
              <p className="sub-merchant">{sub.merchant}</p>
              <p className="sub-meta">{sub.category} · next {sub.next_expected}</p>
            </div>
          </div>

          <div className="sub-right">
            <span
              className="freq-badge"
              style={{ '--badge-color': FREQ_COLORS[sub.frequency] || '#6b7280' }}
            >
              {sub.frequency}
            </span>
            <p className="sub-amount">${sub.amount.toFixed(2)}</p>
            {sub.source === 'manual' && (
              <button
                className="delete-btn"
                onClick={() => handleDelete(sub.id)}
                disabled={deleting === sub.id}
              >
                {deleting === sub.id ? '...' : '✕'}
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
