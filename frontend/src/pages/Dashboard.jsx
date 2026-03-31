import { useState, useEffect, useCallback } from 'react'
import { getSavedSubscriptions, syncSubscriptions, getSummary, getAccounts } from '../api'
import { usePlaid } from '../hooks/usePlaid'
import SubscriptionList from '../components/SubscriptionList'
import AddManualForm from '../components/AddManualForm'
import SpendingChart from '../components/SpendingChart'

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

  return (
    <main className="dashboard">
      <div className="stats-row">
        <div className="stat-card">
          <p className="stat-label">Monthly Spend</p>
          <p className="stat-value">${monthlyTotal.toFixed(2)}</p>
        </div>

        <div className="stat-card">
          <p className="stat-label">Subscriptions</p>
          <p className="stat-value">{subs.length}</p>
        </div>

        <div className="stat-card">
          <p className="stat-label">Linked Accounts</p>
          <p className="stat-value">{accounts.length}</p>
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
        <SubscriptionList subscriptions={subs} onRefresh={fetchData} />
      )}
    </main>
  )
}