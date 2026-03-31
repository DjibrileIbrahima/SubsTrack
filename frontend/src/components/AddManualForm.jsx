import { useState } from 'react'
import { addManualSubscription } from '../api'

const DEFAULT = {
  merchant: '',
  amount: '',
  frequency: 'monthly',
  next_expected: '',
}

export default function AddManualForm({ onAdded }) {
  const [form, setForm] = useState(DEFAULT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const set = (field) => (e) => {
    setForm((prev) => ({ ...prev, [field]: e.target.value }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()

    const merchant = form.merchant.trim()
    const amount = Number(form.amount)

    if (!merchant) {
      setError('Merchant is required')
      return
    }

    if (!Number.isFinite(amount) || amount <= 0) {
      setError('Enter a valid amount greater than 0')
      return
    }

    try {
      setLoading(true)
      setError('')

      const payload = {
        merchant,
        amount,
        frequency: form.frequency,
        ...(form.next_expected ? { next_expected: form.next_expected } : {}),
      }

      await addManualSubscription(payload)
      setForm(DEFAULT)
      onAdded?.()
    } catch {
      setError('Failed to add subscription')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="manual-form" onSubmit={handleSubmit}>
      <h3 className="form-title">Add Manually</h3>

      {error && <p className="form-error">{error}</p>}

      <div className="form-grid">
        <input
          className="form-input"
          placeholder="Merchant (e.g. Netflix)"
          value={form.merchant}
          onChange={set('merchant')}
          disabled={loading}
        />

        <input
          className="form-input"
          placeholder="Amount (e.g. 15.99)"
          type="number"
          step="0.01"
          min="0.01"
          value={form.amount}
          onChange={set('amount')}
          disabled={loading}
        />

        <select
          className="form-input"
          value={form.frequency}
          onChange={set('frequency')}
          disabled={loading}
        >
          <option value="weekly">Weekly</option>
          <option value="biweekly">Biweekly</option>
          <option value="monthly">Monthly</option>
          <option value="quarterly">Quarterly</option>
          <option value="yearly">Yearly</option>
        </select>

        <input
          className="form-input"
          type="date"
          value={form.next_expected}
          onChange={set('next_expected')}
          disabled={loading}
        />
      </div>

      <button className="btn-primary" type="submit" disabled={loading}>
        {loading ? 'Adding...' : '+ Add Subscription'}
      </button>
    </form>
  )
}