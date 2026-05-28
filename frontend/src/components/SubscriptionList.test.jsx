/**
 * Tests for src/components/SubscriptionList.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SubscriptionList from './SubscriptionList'

vi.mock('../api', () => ({
  deleteSubscription: vi.fn(),
  updateSubscription: vi.fn(),
}))

import { deleteSubscription, updateSubscription } from '../api'

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

describe('SubscriptionList — edit subscription', () => {
  it('renders an edit button for each subscription with an id', () => {
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)
    const editButtons = screen.getAllByRole('button', { name: /edit subscription/i })
    expect(editButtons).toHaveLength(2)
  })

  it('clicking edit button opens the inline edit form', async () => {
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)
    const editButtons = screen.getAllByRole('button', { name: /edit subscription/i })
    await userEvent.click(editButtons[0])
    expect(screen.getByPlaceholderText('Merchant')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Amount')).toBeInTheDocument()
  })

  it('edit form is pre-filled with the subscription current values', async () => {
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)
    const editButtons = screen.getAllByRole('button', { name: /edit subscription/i })
    await userEvent.click(editButtons[0])

    expect(screen.getByPlaceholderText('Merchant')).toHaveValue('Netflix')
    expect(screen.getByPlaceholderText('Amount')).toHaveValue(15.99)
    expect(screen.getByPlaceholderText('Category')).toHaveValue('Entertainment')
  })

  it('clicking Cancel closes the form without calling updateSubscription', async () => {
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)
    const editButtons = screen.getAllByRole('button', { name: /edit subscription/i })
    await userEvent.click(editButtons[0])

    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))

    expect(screen.queryByPlaceholderText('Merchant')).not.toBeInTheDocument()
    expect(updateSubscription).not.toHaveBeenCalled()
  })

  it('clicking Save calls updateSubscription with correct id and payload, then calls onRefresh and closes form', async () => {
    updateSubscription.mockResolvedValue({ subscription: { ...MOCK_SUBS[0], merchant: 'Netflix Updated' } })
    const onRefresh = vi.fn().mockResolvedValue(undefined)

    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={onRefresh} />)
    const editButtons = screen.getAllByRole('button', { name: /edit subscription/i })
    await userEvent.click(editButtons[0])

    const merchantInput = screen.getByPlaceholderText('Merchant')
    await userEvent.clear(merchantInput)
    await userEvent.type(merchantInput, 'Netflix Updated')

    await userEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(updateSubscription).toHaveBeenCalledWith('sub-1', expect.objectContaining({
        merchant: 'Netflix Updated',
        amount: 15.99,
        frequency: 'monthly',
      }))
      expect(onRefresh).toHaveBeenCalled()
    })

    expect(screen.queryByPlaceholderText('Merchant')).not.toBeInTheDocument()
  })

  it('shows error message when save fails', async () => {
    updateSubscription.mockRejectedValue({ response: { data: { detail: 'Update failed' } } })
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)

    const editButtons = screen.getAllByRole('button', { name: /edit subscription/i })
    await userEvent.click(editButtons[0])
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }))

    expect(await screen.findByText('Update failed')).toBeInTheDocument()
  })

  it('shows fallback error when save fails without response detail', async () => {
    updateSubscription.mockRejectedValue(new Error('Network error'))
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)

    const editButtons = screen.getAllByRole('button', { name: /edit subscription/i })
    await userEvent.click(editButtons[0])
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }))

    expect(await screen.findByText(/failed to save/i)).toBeInTheDocument()
  })

  it('shows Saving... while request is in flight', async () => {
    let resolve
    updateSubscription.mockReturnValue(new Promise(r => { resolve = r }))
    render(<SubscriptionList subscriptions={MOCK_SUBS} onRefresh={vi.fn()} />)

    const editButtons = screen.getAllByRole('button', { name: /edit subscription/i })
    await userEvent.click(editButtons[0])
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }))

    expect(screen.getByText('Saving...')).toBeInTheDocument()
    resolve({ subscription: MOCK_SUBS[0] })
  })
})
