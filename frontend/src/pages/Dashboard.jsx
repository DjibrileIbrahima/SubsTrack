import { useState, useEffect, useCallback } from 'react'
import { getSavedSubscriptions, syncSubscriptions, getSummary, getAccounts } from '../api'
import { usePlaid } from '../hooks/usePlaid'
import SubscriptionList from '../components/SubscriptionList'
import AddManualForm from '../components/AddManualForm'
import SpendingChart from '../components/SpendingChart'
import CategoryChart from '../components/CategoryChart'

const MONTHLY_FACTOR = {
  weekly: 4.33,
  biweekly: 2.17,
  monthly: 1,
  quarterly: 1 / 3,
  yearly: 1 / 12,
}

function getDueSoon(subs) {
  const todayStr = new Date().toISOString().slice(0, 10)
  const cutoff = new Date()
  cutoff.setDate(cutoff.getDate() + 7)
  const cutoffStr = cutoff.toISOString().slice(0, 10)
  return subs
    .filter(s => s.next_expected && s.next_expected >= todayStr && s.next_expected <= cutoffStr)
    .sort((a, b) => a.next_expected.localeCompare(b.next_expected))
}

function daysLabel(dateStr) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(dateStr + 'T00:00:00')
  const days = Math.round((d - today) / 86400000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Tomorrow'
  return `In ${days} days`
}

export default function Dashboard() {
  const [subs, setSubs] = useState([])
  const [summary, setSummary] = useState([])
  const [accounts, setAccounts] = useState([])
  const [monthlyTotal, setMonthlyTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')

    try {
      const [subsData, summaryData, accountsData] = await Promise.all([
        getSavedSubscriptions().catch(() => ({ subscriptions: [], total_monthly_spend: 0 })),
        getSummary().catch(() => []),
        getAccounts().catch(() => []),
      ])

      setSubs(subsData.subscriptions || [])
      setMonthlyTotal(subsData.total_monthly_spend || 0)
      setSummary(summaryData || [])
      setAccounts(accountsData || [])
    } catch {
      setError('Failed to load dashboard data.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleSync = useCallback(async () => {
    setSyncing(true)
    setError('')

    try {
      const data = await syncSubscriptions()
      setSubs(data.subscriptions || [])
      setMonthlyTotal(data.total_monthly_spend || 0)

      const refreshedSummary = await getSummary().catch(() => [])
      setSummary(refreshedSummary || [])
    } catch (e) {
      console.error('Sync failed:', e)
      setError('Failed to sync subscriptions.')
    } finally {
      setSyncing(false)
    }
  }, [])

  const { initAndOpen, loading: plaidLoading, error: plaidError } = usePlaid(async () => {
    await fetchData()
    await handleSync()
  })

  const annualEstimate = subs.reduce((acc, s) => {
    return acc + (s.amount || 0) * (MONTHLY_FACTOR[s.frequency] || 1)
  }, 0) * 12

  const dueSoon = getDueSoon(subs)

  return (
    <main className="dashboard">
      <div className="stats-row">
        <div className="stat-card">
          <p className="stat-label">Monthly Spend</p>
          <p className="stat-value">${monthlyTotal.toFixed(2)}</p>
        </div>

        <div className="stat-card">
          <p className="stat-label">Annual Est.</p>
          <p className="stat-value">${Math.round(annualEstimate).toLocaleString()}</p>
        </div>

        <div className="stat-card">
          <p className="stat-label">Subscriptions</p>
          <p className="stat-value">{subs.length}</p>
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className="btn-primary connect-btn"
            onClick={initAndOpen}
            disabled={plaidLoading}
          >
            {plaidLoading ? 'Connecting...' : '+ Connect Bank'}
          </button>

          {accounts.length > 0 && (
            <button
              className="btn-ghost"
              onClick={handleSync}
              disabled={syncing}
            >
              {syncing ? 'Syncing...' : '↻ Sync'}
            </button>
          )}
        </div>
      </div>

      {(plaidError || error) && (
        <p style={{ color: 'var(--danger)', fontSize: 13, marginBottom: 12 }}>
          {plaidError || error}
        </p>
      )}

      <SpendingChart data={summary} />

      <CategoryChart subscriptions={subs} />

      {dueSoon.length > 0 && (
        <div style={{ marginBottom: 32 }}>
          <div className="section-header" style={{ marginBottom: 10 }}>
            <h3 className="section-title">Due Soon</h3>
          </div>

          <div className="due-soon-list">
            {dueSoon.map(s => {
              const label = daysLabel(s.next_expected)
              const urgent = label === 'Today' || label === 'Tomorrow'
              return (
                <div key={s.id || s.merchant} className="due-soon-item">
                  <div className="due-soon-avatar">
                    {s.merchant?.[0]?.toUpperCase() || '?'}
                  </div>
                  <span className="due-soon-merchant">{s.merchant}</span>
                  <span className={`due-soon-when${urgent ? ' urgent' : ''}`}>
                    {label}
                  </span>
                  <span className="due-soon-amount">${Number(s.amount || 0).toFixed(2)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="section-header">
        <h3 className="section-title">Subscriptions</h3>
        <button className="btn-ghost" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ Add Manually'}
        </button>
      </div>

      {showForm && (
        <AddManualForm
          onAdded={() => {
            setShowForm(false)
            fetchData()
          }}
        />
      )}

      {loading ? (
        <div className="loading-rows">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="skeleton" />
          ))}
        </div>
      ) : (
        <SubscriptionList
          subscriptions={subs}
          onRefresh={fetchData}
          hasAccounts={accounts.length > 0}
          onSync={handleSync}
          syncing={syncing}
        />
      )}
    </main>
  )
}
