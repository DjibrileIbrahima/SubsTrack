/**
 * Tests for src/components/SubscriptionList.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SubscriptionList from './SubscriptionList'

vi.mock('../api', () => ({
  deleteSubscription: vi.fn(),
}))

import { deleteSubscription } from '../api'

const MOCK_SUBS = [
  {
    id: 'sub-1',
    merchant: 'Netflix',
    amount: 15.99,
    frequency: 'monthly',
    category: 'Entertainment',
    next_expected: '2025-06-15',
    source: 'plaid',
    confidence: 0.92,
    detection_method: 'rules',
  },
  {
    id: 'sub-2',
    merchant: 'Spotify',
    amount: 9.99,
    frequency: 'monthly',
    category: 'Music',
    next_expected: '2025-06-20',
    source: 'manual',
  },
]

beforeEach(() => vi.clearAllMocks())

describe('SubscriptionList — empty state', () => {
  it('shows no-bank message when no accounts and no subs', () => {
    render(
      <SubscriptionList subscriptions={[]} hasAccounts={false} onRefresh={vi.fn()} />
    )
    expect(screen.getByText(/no bank account connected/i)).toBeInTheDocument()
  })

  it('shows sync prompt when accounts exist but no subs', () => {
    render(
      <SubscriptionList subscriptions={[]} hasAccounts={true} onRefresh={vi.fn()} onSync={vi.fn()} />
    )
    expect(screen.getByText(/no subscriptions detected/i)).toBeInTheDocument()
  })
})

describe('SubscriptionList — with subscriptions', () => {
  it('renders all subscriptions', () => {
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)
    expect(screen.getByText('Netflix')).toBeInTheDocument()
    expect(screen.getByText('Spotify')).toBeInTheDocument()
  })

  it('displays amount formatted to 2 decimal places', () => {
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)
    expect(screen.getByText('$15.99')).toBeInTheDocument()
    expect(screen.getByText('$9.99')).toBeInTheDocument()
  })

  it('shows frequency badge', () => {
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)
    const badges = screen.getAllByText('monthly')
    expect(badges.length).toBeGreaterThan(0)
  })

  it('shows "Bank" badge for plaid source and "Manual" for manual', () => {
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)
    expect(screen.getByText('Bank')).toBeInTheDocument()
    expect(screen.getByText('Manual')).toBeInTheDocument()
  })

  it('shows confidence percentage for plaid-detected subscriptions', () => {
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)
    expect(screen.getByText('92% confidence')).toBeInTheDocument()
  })

  it('calls deleteSubscription and then onRefresh when delete button clicked', async () => {
    deleteSubscription.mockResolvedValue({ message: 'removed' })
    const onRefresh = vi.fn().mockResolvedValue(undefined)

    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={onRefresh} />)

    const deleteButtons = screen.getAllByRole('button', { name: /✕/ })
    await userEvent.click(deleteButtons[0])

    await waitFor(() => {
      expect(deleteSubscription).toHaveBeenCalledWith('sub-1')
      expect(onRefresh).toHaveBeenCalled()
    })
  })

  it('shows error message when delete fails', async () => {
    deleteSubscription.mockRejectedValue(new Error('Server error'))
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)

    const deleteButtons = screen.getAllByRole('button', { name: /✕/ })
    await userEvent.click(deleteButtons[0])

    expect(await screen.findByText(/failed to delete/i)).toBeInTheDocument()
  })
})
