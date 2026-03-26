import { useState } from 'react'
import { addManualSubscription } from '../api'

const DEFAULT = { merchant: '', amount: '', frequency: 'monthly', next_expected: '' }

export default function AddManualForm({ onAdded }) {
  const [form, setForm] = useState(DEFAULT)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const set = (field) => (e) => setForm(prev => ({ ...prev, [field]: e.target.value }))

  const handleSubmit = async () => {
    if (!form.merchant || !form.amount) {
      setError('Merchant and amount are required')
      return
    }
    try {
      setLoading(true)
      setError(null)
      await addManualSubscription({ ...form, amount: parseFloat(form.amount) })
      setForm(DEFAULT)
      onAdded?.()
    } catch (e) {
      setError('Failed to add subscription')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="manual-form">
      <h3 className="form-title">Add Manually</h3>

      {error && <p className="form-error">{error}</p>}

      <div className="form-grid">
        <input
          className="form-input"
          placeholder="Merchant (e.g. Netflix)"
          value={form.merchant}
          onChange={set('merchant')}
        />
        <input
          className="form-input"
          placeholder="Amount (e.g. 15.99)"
          type="number"
          step="0.01"
          value={form.amount}
          onChange={set('amount')}
        />
        <select className="form-input" value={form.frequency} onChange={set('frequency')}>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
          <option value="quarterly">Quarterly</option>
          <option value="yearly">Yearly</option>
        </select>
        <input
          className="form-input"
          type="date"
          value={form.next_expected}
          onChange={set('next_expected')}
        />
      </div>

      <button className="btn-primary" onClick={handleSubmit} disabled={loading}>
        {loading ? 'Adding...' : '+ Add Subscription'}
      </button>
    </div>
  )
}
