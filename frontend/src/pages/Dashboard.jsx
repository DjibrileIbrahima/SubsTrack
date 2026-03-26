import { useState, useEffect, useCallback } from 'react'
import { getSubscriptions, getSummary, getAccounts } from '../api'
import { usePlaid } from '../hooks/usePlaid'
import SubscriptionList from '../components/SubscriptionList'
import AddManualForm from '../components/AddManualForm'
import SpendingChart from '../components/SpendingChart'

export default function Dashboard() {
  const [subs, setSubs] = useState(null)
  const [summary, setSummary] = useState([])
  const [accounts, setAccounts] = useState([])
  const [monthlyTotal, setMonthlyTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [subsData, summaryData, accountsData] = await Promise.all([
        getSubscriptions().catch(() => ({ subscriptions: [], total_monthly_spend: 0 })),
        getSummary().catch(() => []),
        getAccounts().catch(() => []),
      ])
      setSubs(subsData.subscriptions)
      setMonthlyTotal(subsData.total_monthly_spend)
      setSummary(summaryData)
      setAccounts(accountsData)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const { fetchLinkToken, open, ready, loading: plaidLoading } = usePlaid(fetchData)

  const handleConnectBank = async () => {
    await fetchLinkToken()
    open()
  }

  useEffect(() => {
    if (ready) open()
  }, [ready])

  return (
    <main className="dashboard">

      {/* Stats row */}
      <div className="stats-row">
        <div className="stat-card">
          <p className="stat-label">Monthly Spend</p>
          <p className="stat-value">${monthlyTotal.toFixed(2)}</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Subscriptions</p>
          <p className="stat-value">{subs?.length ?? '—'}</p>
        </div>
        <div className="stat-card">
          <p className="stat-label">Linked Accounts</p>
          <p className="stat-value">{accounts.length}</p>
        </div>
        <button
          className="btn-primary connect-btn"
          onClick={handleConnectBank}
          disabled={plaidLoading}
        >
          {plaidLoading ? 'Loading...' : '+ Connect Bank'}
        </button>
      </div>

      {/* Chart */}
      <SpendingChart data={summary} />

      {/* Subscriptions */}
      <div className="section-header">
        <h3 className="section-title">Subscriptions</h3>
        <button className="btn-ghost" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ Add Manually'}
        </button>
      </div>

      {showForm && (
        <AddManualForm onAdded={() => { setShowForm(false); fetchData() }} />
      )}

      {loading ? (
        <div className="loading-rows">
          {[...Array(4)].map((_, i) => <div key={i} className="skeleton" />)}
        </div>
      ) : (
        <SubscriptionList subscriptions={subs} onRefresh={fetchData} />
      )}

    </main>
  )
}
