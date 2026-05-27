/**
 * Tests for src/components/AddManualForm.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AddManualForm from './AddManualForm'

vi.mock('../api', () => ({
  addManualSubscription: vi.fn(),
}))

import { addManualSubscription } from '../api'

beforeEach(() => vi.clearAllMocks())

function renderForm(onAdded = vi.fn()) {
  return { onAdded, ...render(<AddManualForm onAdded={onAdded} />) }
}

describe('AddManualForm', () => {
  it('renders all form fields', () => {
    renderForm()
    expect(screen.getByPlaceholderText(/merchant/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/amount/i)).toBeInTheDocument()
    expect(screen.getByRole('combobox')).toBeInTheDocument()  // frequency select
    expect(screen.getByRole('button', { name: /add subscription/i })).toBeInTheDocument()
  })

  it('shows validation error when merchant is empty', async () => {
    renderForm()
    await userEvent.click(screen.getByRole('button', { name: /add subscription/i }))
    expect(await screen.findByText(/merchant is required/i)).toBeInTheDocument()
    expect(addManualSubscription).not.toHaveBeenCalled()
  })

  it('shows validation error for invalid (zero) amount', async () => {
    renderForm()
    await userEvent.type(screen.getByPlaceholderText(/merchant/i), 'Netflix')
    await userEvent.clear(screen.getByPlaceholderText(/amount/i))
    await userEvent.type(screen.getByPlaceholderText(/amount/i), '0')
    await userEvent.click(screen.getByRole('button', { name: /add subscription/i }))
    expect(await screen.findByText(/valid amount/i)).toBeInTheDocument()
    expect(addManualSubscription).not.toHaveBeenCalled()
  })

  it('shows validation error for negative amount', async () => {
    renderForm()
    await userEvent.type(screen.getByPlaceholderText(/merchant/i), 'Netflix')
    await userEvent.clear(screen.getByPlaceholderText(/amount/i))
    await userEvent.type(screen.getByPlaceholderText(/amount/i), '-5')
    await userEvent.click(screen.getByRole('button', { name: /add subscription/i }))
    expect(await screen.findByText(/valid amount/i)).toBeInTheDocument()
  })

  it('calls addManualSubscription with correct payload on valid submit', async () => {
    addManualSubscription.mockResolvedValue({ subscription: {} })
    const { onAdded } = renderForm()

    await userEvent.type(screen.getByPlaceholderText(/merchant/i), 'Notion')
    await userEvent.clear(screen.getByPlaceholderText(/amount/i))
    await userEvent.type(screen.getByPlaceholderText(/amount/i), '8')
    await userEvent.selectOptions(screen.getByRole('combobox'), 'monthly')

    await userEvent.click(screen.getByRole('button', { name: /add subscription/i }))

    await waitFor(() => {
      expect(addManualSubscription).toHaveBeenCalledWith(
        expect.objectContaining({ merchant: 'Notion', amount: 8, frequency: 'monthly' })
      )
    })
    expect(onAdded).toHaveBeenCalled()
  })

  it('resets form after successful submit', async () => {
    addManualSubscription.mockResolvedValue({ subscription: {} })
    renderForm()

    const merchantInput = screen.getByPlaceholderText(/merchant/i)
    await userEvent.type(merchantInput, 'Spotify')
    await userEvent.type(screen.getByPlaceholderText(/amount/i), '10')
    await userEvent.click(screen.getByRole('button', { name: /add subscription/i }))

    await waitFor(() => expect(addManualSubscription).toHaveBeenCalled())
    expect(merchantInput).toHaveValue('')
  })

  it('shows API error message on failure', async () => {
    addManualSubscription.mockRejectedValue(new Error('Server error'))
    renderForm()

    await userEvent.type(screen.getByPlaceholderText(/merchant/i), 'Netflix')
    await userEvent.type(screen.getByPlaceholderText(/amount/i), '15.99')
    await userEvent.click(screen.getByRole('button', { name: /add subscription/i }))

    expect(await screen.findByText(/failed to add subscription/i)).toBeInTheDocument()
  })

  it('disables submit button while loading', async () => {
    let resolve
    addManualSubscription.mockReturnValue(new Promise(r => { resolve = r }))
    renderForm()

    await userEvent.type(screen.getByPlaceholderText(/merchant/i), 'Netflix')
    await userEvent.type(screen.getByPlaceholderText(/amount/i), '15.99')

    const button = screen.getByRole('button', { name: /add subscription/i })
    await userEvent.click(button)

    await waitFor(() => expect(button).toBeDisabled())
    resolve({ subscription: {} })
  })

  it('does not include next_expected when not filled', async () => {
    addManualSubscription.mockResolvedValue({ subscription: {} })
    renderForm()

    await userEvent.type(screen.getByPlaceholderText(/merchant/i), 'GitHub')
    await userEvent.type(screen.getByPlaceholderText(/amount/i), '4')
    await userEvent.click(screen.getByRole('button', { name: /add subscription/i }))

    await waitFor(() => {
      const call = addManualSubscription.mock.calls[0][0]
      expect(call).not.toHaveProperty('next_expected')
    })
  })
})
