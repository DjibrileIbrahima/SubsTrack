/**
 * Tests for src/pages/Dashboard.jsx
 *
 * Covers: initial load, stats display, due-soon section, sync flow,
 * Plaid connect button, and error states.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Dashboard from './Dashboard'

// ── Mocks ─────────────────────────────────────────────────────────────────────
vi.mock('../api', () => ({
  getSavedSubscriptions: vi.fn(),
  syncSubscriptions: vi.fn(),
  getSyncStatus: vi.fn(),
  getSummary: vi.fn(),
  getAccounts: vi.fn(),
}))

vi.mock('../hooks/usePlaid', () => ({
  usePlaid: vi.fn(),
}))

// Mock chart components so they don't need canvas/SVG in jsdom
vi.mock('../components/SpendingChart', () => ({
  default: () => <div data-testid="spending-chart" />,
}))
vi.mock('../components/CategoryChart', () => ({
  default: () => <div data-testid="category-chart" />,
}))
vi.mock('../components/SubscriptionList', () => ({
  default: ({ subscriptions }) => (
    <div data-testid="sub-list">
      {subscriptions.map(s => (
        <div key={s.id} data-testid="sub-item">{s.merchant}</div>
      ))}
    </div>
  ),
}))
vi.mock('../components/AddManualForm', () => ({
  default: ({ onAdded }) => (
    <div data-testid="add-form">
      <button onClick={onAdded}>Submit</button>
    </div>
  ),
}))

import { getSavedSubscriptions, syncSubscriptions, getSyncStatus, getSummary, getAccounts } from '../api'
import { usePlaid } from '../hooks/usePlaid'

const localDateStr = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const TODAY = localDateStr(new Date())
const IN_3_DAYS = localDateStr(new Date(Date.now() + 3 * 86400000))
const IN_30_DAYS = localDateStr(new Date(Date.now() + 30 * 86400000))

const MOCK_SUBS = [
  { id: 'sub-1', merchant: 'Netflix',  amount: 15.99, frequency: 'monthly', next_expected: IN_3_DAYS, source: 'plaid' },
  { id: 'sub-2', merchant: 'Spotify',  amount: 9.99,  frequency: 'monthly', next_expected: IN_30_DAYS, source: 'plaid' },
]

function setupDefaultMocks({ accounts = [], subs = MOCK_SUBS, summary = [] } = {}) {
  getSavedSubscriptions.mockResolvedValue({ subscriptions: subs, total_monthly_spend: 25.98, annual_estimate: 311.76 })
  getSummary.mockResolvedValue(summary)
  getAccounts.mockResolvedValue(accounts)
  usePlaid.mockReturnValue({ initAndOpen: vi.fn(), loading: false, error: null })
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ─────────────────────────────────────────────────────────────────────────────

describe('Dashboard — initial load', () => {
  it('shows skeleton loading state before data arrives', () => {
    getSavedSubscriptions.mockReturnValue(new Promise(() => {}))
    getSummary.mockReturnValue(new Promise(() => {}))
    getAccounts.mockReturnValue(new Promise(() => {}))
    usePlaid.mockReturnValue({ initAndOpen: vi.fn(), loading: false, error: null })

    render(<Dashboard />)
    expect(screen.getByRole('main')).toBeInTheDocument()
    // Skeletons render during loading
    expect(document.querySelectorAll('.skeleton').length).toBeGreaterThan(0)
  })

  it('renders monthly spend stat after loading', async () => {
    setupDefaultMocks()
    render(<Dashboard />)
    await waitFor(() => expect(screen.getByText('$25.98')).toBeInTheDocument())
  })

  it('renders subscription count stat', async () => {
    setupDefaultMocks()
    render(<Dashboard />)
    await waitFor(() => expect(screen.getByText(String(MOCK_SUBS.length))).toBeInTheDocument())
  })

  it('renders spending and category charts', async () => {
    setupDefaultMocks()
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByTestId('spending-chart')).toBeInTheDocument()
      expect(screen.getByTestId('category-chart')).toBeInTheDocument()
    })
  })
})

describe('Dashboard — due soon', () => {
  it('shows due-soon section for subscription within 7 days', async () => {
    setupDefaultMocks()
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('Due Soon')).toBeInTheDocument()
      expect(screen.getAllByText('Netflix').length).toBeGreaterThan(0)
    })
  })

  it('does NOT show due-soon section when no subs are due within 7 days', async () => {
    setupDefaultMocks({
      subs: [{ id: '1', merchant: 'Spotify', amount: 9.99, frequency: 'monthly', next_expected: IN_30_DAYS, source: 'plaid' }],
    })
    render(<Dashboard />)
    await waitFor(() => expect(screen.queryByText('Due Soon')).not.toBeInTheDocument())
  })

  it('shows "Today" label for due-today subscription', async () => {
    const todaySub = [
      { id: 'x', merchant: 'GitHub', amount: 4.0, frequency: 'monthly', next_expected: TODAY, source: 'plaid' },
    ]
    setupDefaultMocks({ subs: todaySub })
    render(<Dashboard />)
    await waitFor(() => expect(screen.getByText('Today')).toBeInTheDocument())
  })
})

describe('Dashboard — connect bank', () => {
  it('shows "Connect Bank" button', async () => {
    setupDefaultMocks()
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /connect bank/i })).toBeInTheDocument()
    })
  })

  it('calls initAndOpen when Connect Bank is clicked', async () => {
    const initAndOpen = vi.fn()
    setupDefaultMocks()
    usePlaid.mockReturnValue({ initAndOpen, loading: false, error: null })
    render(<Dashboard />)

    await waitFor(() => screen.getByRole('button', { name: /connect bank/i }))
    await userEvent.click(screen.getByRole('button', { name: /connect bank/i }))
    expect(initAndOpen).toHaveBeenCalled()
  })

  it('shows Sync button when accounts exist', async () => {
    setupDefaultMocks({ accounts: [{ id: 'acc-1', institution: 'Chase' }] })
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sync/i })).toBeInTheDocument()
    })
  })

  it('does NOT show Sync button when no accounts', async () => {
    setupDefaultMocks({ accounts: [] })
    render(<Dashboard />)
    await waitFor(() => expect(screen.queryByRole('button', { name: /sync/i })).not.toBeInTheDocument())
  })

  it('shows Plaid error message', async () => {
    setupDefaultMocks()
    usePlaid.mockReturnValue({ initAndOpen: vi.fn(), loading: false, error: 'Bank connection failed' })
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('Bank connection failed')).toBeInTheDocument()
    })
  })
})

describe('Dashboard — Add manually', () => {
  it('toggles add-manual form on button click', async () => {
    setupDefaultMocks()
    render(<Dashboard />)

    await waitFor(() => screen.getByRole('button', { name: /add manually/i }))
    await userEvent.click(screen.getByRole('button', { name: /add manually/i }))

    expect(screen.getByTestId('add-form')).toBeInTheDocument()
    // Clicking again should hide it
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByTestId('add-form')).not.toBeInTheDocument()
  })
})

describe('Dashboard — sync', () => {
  // The sync itself now runs on a background job (see Dashboard.jsx's
  // SYNC_POLL_INTERVAL_MS) — the button click resolves quickly, then the
  // component polls getSyncStatus. These tests use real timers with a
  // generous waitFor timeout rather than faking the poll interval, since
  // userEvent + fake timers is fragile in this setup.

  it('calls syncSubscriptions then polls getSyncStatus until done', async () => {
    syncSubscriptions.mockResolvedValue({ status: 'syncing' })
    getSyncStatus.mockResolvedValue({
      syncing: false,
      subscriptions: MOCK_SUBS,
      total_monthly_spend: 25.98,
      annual_estimate: 311.76,
      reconnect_needed: [],
      sync_error: false,
    })
    getSummary.mockResolvedValue([])
    setupDefaultMocks({ accounts: [{ id: 'acc-1' }] })

    render(<Dashboard />)
    await waitFor(() => screen.getByRole('button', { name: /sync/i }))
    await userEvent.click(screen.getByRole('button', { name: /sync/i }))

    await waitFor(() => expect(syncSubscriptions).toHaveBeenCalled())
    await waitFor(() => expect(getSyncStatus).toHaveBeenCalled(), { timeout: 5000 })
  })

  it('keeps polling while the job is still running', async () => {
    syncSubscriptions.mockResolvedValue({ status: 'syncing' })
    getSyncStatus
      .mockResolvedValueOnce({ syncing: true })
      .mockResolvedValueOnce({
        syncing: false,
        subscriptions: MOCK_SUBS,
        total_monthly_spend: 25.98,
        annual_estimate: 311.76,
        reconnect_needed: [],
        sync_error: false,
      })
    getSummary.mockResolvedValue([])
    setupDefaultMocks({ accounts: [{ id: 'acc-1' }] })

    render(<Dashboard />)
    await waitFor(() => screen.getByRole('button', { name: /sync/i }))
    await userEvent.click(screen.getByRole('button', { name: /sync/i }))

    await waitFor(() => expect(getSyncStatus).toHaveBeenCalledTimes(2), { timeout: 8000 })
  }, 10000)

  it('shows error when the sync request itself fails', async () => {
    syncSubscriptions.mockRejectedValue(new Error('Plaid error'))
    setupDefaultMocks({ accounts: [{ id: 'acc-1' }] })

    render(<Dashboard />)
    await waitFor(() => screen.getByRole('button', { name: /sync/i }))
    await userEvent.click(screen.getByRole('button', { name: /sync/i }))

    await waitFor(() => {
      expect(screen.getByText(/failed to sync/i)).toBeInTheDocument()
    })
  })

  it('shows the reconnect instructions once the background job flags a broken bank connection', async () => {
    syncSubscriptions.mockResolvedValue({ status: 'syncing' })
    getSyncStatus.mockResolvedValue({
      syncing: false,
      subscriptions: [],
      total_monthly_spend: 0,
      annual_estimate: 0,
      reconnect_needed: ['Test Bank'],
      sync_error: false,
    })
    getSummary.mockResolvedValue([])
    setupDefaultMocks({ accounts: [{ id: 'acc-1' }] })

    render(<Dashboard />)
    await waitFor(() => screen.getByRole('button', { name: /sync/i }))
    await userEvent.click(screen.getByRole('button', { name: /sync/i }))

    await waitFor(
      () => expect(screen.getByText(/Test Bank needs to be reconnected/i)).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })

  it('shows a generic error when the background job fails', async () => {
    syncSubscriptions.mockResolvedValue({ status: 'syncing' })
    getSyncStatus.mockResolvedValue({
      syncing: false,
      subscriptions: [],
      total_monthly_spend: 0,
      annual_estimate: 0,
      reconnect_needed: [],
      sync_error: true,
    })
    getSummary.mockResolvedValue([])
    setupDefaultMocks({ accounts: [{ id: 'acc-1' }] })

    render(<Dashboard />)
    await waitFor(() => screen.getByRole('button', { name: /sync/i }))
    await userEvent.click(screen.getByRole('button', { name: /sync/i }))

    await waitFor(
      () => expect(screen.getByText(/failed to sync/i)).toBeInTheDocument(),
      { timeout: 5000 }
    )
  })
})

describe('Dashboard — annual estimate', () => {
  it('displays the backend-provided annual estimate', async () => {
    setupDefaultMocks()
    render(<Dashboard />)
    await waitFor(() => {
      expect(screen.getByText('Annual Est.')).toBeInTheDocument()
      // 311.76 from the API response, rounded and locale-formatted
      expect(screen.getByText('$312')).toBeInTheDocument()
    })
  })
})
