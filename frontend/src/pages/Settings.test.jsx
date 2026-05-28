/**
 * Tests for src/pages/Settings.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Settings from './Settings'

vi.mock('../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

vi.mock('../api', () => ({
  updateMe: vi.fn(),
  getAccounts: vi.fn(),
  unlinkAccount: vi.fn(),
}))

import { useAuth } from '../context/AuthContext'
import { updateMe, getAccounts, unlinkAccount } from '../api'

const MOCK_USER = {
  email: 'user@example.com',
  alert_email: false,
  alert_sms: false,
  phone: null,
}

function renderSettings(onNavigate = vi.fn()) {
  return render(<Settings onNavigate={onNavigate} />)
}

beforeEach(() => {
  useAuth.mockReturnValue({ user: MOCK_USER, updateUser: vi.fn() })
  getAccounts.mockResolvedValue([])
})

// ── Rendering ────────────────────────────────────────────────────────────────

describe('Settings — rendering', () => {
  it('renders the Settings heading', () => {
    renderSettings()
    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  it('shows the user email in the profile section', () => {
    renderSettings()
    expect(screen.getByText('user@example.com')).toBeInTheDocument()
  })

  it('shows email alerts and SMS alerts toggles', () => {
    renderSettings()
    expect(screen.getByText('Email alerts')).toBeInTheDocument()
    expect(screen.getByText('SMS alerts')).toBeInTheDocument()
  })

  it('renders Back button', () => {
    renderSettings()
    expect(screen.getByRole('button', { name: /back/i })).toBeInTheDocument()
  })

  it('renders Save changes button', () => {
    renderSettings()
    expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument()
  })

  it('shows linked bank name when accounts are present', async () => {
    getAccounts.mockResolvedValue([{ id: 'acc-1', institution_name: 'Chase' }])
    renderSettings()
    await waitFor(() => {
      expect(screen.getByText('Chase')).toBeInTheDocument()
    })
  })

  it('does not show Linked banks section when no accounts', async () => {
    getAccounts.mockResolvedValue([])
    renderSettings()
    await waitFor(() => {})
    expect(screen.queryByText(/linked banks/i)).not.toBeInTheDocument()
  })

  it('shows multiple linked banks each on their own row', async () => {
    getAccounts.mockResolvedValue([
      { id: 'acc-1', institution_name: 'Chase' },
      { id: 'acc-2', institution_name: 'Wells Fargo' },
    ])
    renderSettings()
    await waitFor(() => {
      expect(screen.getByText('Chase')).toBeInTheDocument()
      expect(screen.getByText('Wells Fargo')).toBeInTheDocument()
    })
  })
})

// ── Unlink account ───────────────────────────────────────────────────────────

describe('Settings — unlink account', () => {
  const ACCOUNTS = [
    { id: 'acc-1', institution_name: 'Chase' },
    { id: 'acc-2', institution_name: 'Wells Fargo' },
  ]

  beforeEach(() => {
    getAccounts.mockResolvedValue(ACCOUNTS)
  })

  it('shows an Unlink button for each account', async () => {
    renderSettings()
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /unlink/i })).toHaveLength(2)
    })
  })

  it('calls unlinkAccount with the correct id', async () => {
    unlinkAccount.mockResolvedValue({ message: 'Account unlinked' })
    renderSettings()
    await screen.findByText('Chase')

    await userEvent.click(screen.getByRole('button', { name: /unlink chase/i }))

    await waitFor(() => expect(unlinkAccount).toHaveBeenCalledWith('acc-1'))
  })

  it('removes the account from the list after successful unlink', async () => {
    unlinkAccount.mockResolvedValue({ message: 'Account unlinked' })
    renderSettings()
    await screen.findByText('Chase')

    await userEvent.click(screen.getByRole('button', { name: /unlink chase/i }))

    await waitFor(() => expect(screen.queryByText('Chase')).not.toBeInTheDocument())
    expect(screen.getByText('Wells Fargo')).toBeInTheDocument()
  })

  it('shows error when unlink fails', async () => {
    unlinkAccount.mockRejectedValue(new Error('Server error'))
    renderSettings()
    await screen.findByText('Chase')

    await userEvent.click(screen.getByRole('button', { name: /unlink chase/i }))

    expect(await screen.findByText(/failed to unlink/i)).toBeInTheDocument()
  })

  it('shows Unlinking… while in flight', async () => {
    let resolve
    unlinkAccount.mockReturnValue(new Promise(r => { resolve = r }))
    renderSettings()
    await screen.findByText('Chase')

    await userEvent.click(screen.getByRole('button', { name: /unlink chase/i }))

    expect(screen.getByText('Unlinking…')).toBeInTheDocument()
    resolve({ message: 'Account unlinked' })
  })
})

// ── Initial toggle state ─────────────────────────────────────────────────────

describe('Settings — initial state from user', () => {
  it('email toggle is unchecked when user.alert_email is false', () => {
    renderSettings()
    const [emailCheckbox] = screen.getAllByRole('checkbox')
    expect(emailCheckbox).not.toBeChecked()
  })

  it('email toggle is checked when user.alert_email is true', () => {
    useAuth.mockReturnValue({
      user: { ...MOCK_USER, alert_email: true },
      updateUser: vi.fn(),
    })
    renderSettings()
    const [emailCheckbox] = screen.getAllByRole('checkbox')
    expect(emailCheckbox).toBeChecked()
  })

  it('SMS toggle is unchecked when user.alert_sms is false', () => {
    renderSettings()
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes[1]).not.toBeChecked()
  })

  it('SMS toggle is checked when user.alert_sms is true', () => {
    useAuth.mockReturnValue({
      user: { ...MOCK_USER, alert_sms: true, phone: '+15550001234' },
      updateUser: vi.fn(),
    })
    renderSettings()
    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes[1]).toBeChecked()
  })
})

// ── Phone number field ───────────────────────────────────────────────────────

describe('Settings — phone number field', () => {
  it('does not show phone field when SMS alerts are off', () => {
    renderSettings()
    expect(screen.queryByPlaceholderText(/\+1/)).not.toBeInTheDocument()
  })

  it('shows phone field after toggling SMS alerts on', async () => {
    renderSettings()
    const checkboxes = screen.getAllByRole('checkbox')
    await userEvent.click(checkboxes[1])
    expect(screen.getByPlaceholderText(/\+1/)).toBeInTheDocument()
  })

  it('hides phone field after toggling SMS back off', async () => {
    renderSettings()
    const checkboxes = screen.getAllByRole('checkbox')
    await userEvent.click(checkboxes[1]) // on
    await userEvent.click(checkboxes[1]) // off
    expect(screen.queryByPlaceholderText(/\+1/)).not.toBeInTheDocument()
  })

  it('pre-fills phone from user.phone when SMS is already on', () => {
    useAuth.mockReturnValue({
      user: { ...MOCK_USER, alert_sms: true, phone: '+15550001234' },
      updateUser: vi.fn(),
    })
    renderSettings()
    expect(screen.getByDisplayValue('+15550001234')).toBeInTheDocument()
  })

  it('accepts typed phone number input', async () => {
    renderSettings()
    const checkboxes = screen.getAllByRole('checkbox')
    await userEvent.click(checkboxes[1])
    const input = screen.getByPlaceholderText(/\+1/)
    await userEvent.type(input, '+15550009999')
    expect(input).toHaveValue('+15550009999')
  })
})

// ── Save button disabled state ───────────────────────────────────────────────

describe('Settings — Save button disabled state', () => {
  it('is disabled when nothing has changed', () => {
    renderSettings()
    expect(screen.getByRole('button', { name: /save changes/i })).toBeDisabled()
  })

  it('becomes enabled after toggling email alerts', async () => {
    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    expect(screen.getByRole('button', { name: /save changes/i })).not.toBeDisabled()
  })

  it('becomes enabled after toggling SMS alerts', async () => {
    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[1])
    expect(screen.getByRole('button', { name: /save changes/i })).not.toBeDisabled()
  })

  it('becomes enabled after typing a phone number when SMS is on', async () => {
    useAuth.mockReturnValue({
      user: { ...MOCK_USER, alert_sms: true, phone: '' },
      updateUser: vi.fn(),
    })
    renderSettings()
    const input = screen.getByPlaceholderText(/\+1/)
    await userEvent.type(input, '+1555')
    expect(screen.getByRole('button', { name: /save changes/i })).not.toBeDisabled()
  })

  it('shows "Saving…" and disables button while in flight', async () => {
    let resolve
    updateMe.mockReturnValue(new Promise(r => { resolve = r }))

    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
    })
    resolve({ ...MOCK_USER, alert_email: true })
  })
})

// ── Save flow ────────────────────────────────────────────────────────────────

describe('Settings — save flow', () => {
  it('calls updateMe with correct payload on save', async () => {
    updateMe.mockResolvedValue({ ...MOCK_USER, alert_email: true })

    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(updateMe).toHaveBeenCalledWith(expect.objectContaining({
        alert_email: true,
        alert_sms: false,
        phone: null,
      }))
    })
  })

  it('calls updateUser with the server response after save', async () => {
    const updateUser = vi.fn()
    useAuth.mockReturnValue({ user: MOCK_USER, updateUser })
    const saved = { ...MOCK_USER, alert_email: true }
    updateMe.mockResolvedValue(saved)

    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(updateUser).toHaveBeenCalledWith(saved))
  })

  it('shows "Settings saved." after successful save', async () => {
    updateMe.mockResolvedValue({ ...MOCK_USER, alert_email: true })

    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText(/settings saved/i)).toBeInTheDocument()
  })

  it('shows error message when save fails', async () => {
    updateMe.mockRejectedValue(new Error('Server error'))

    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))

    expect(await screen.findByText(/failed to save/i)).toBeInTheDocument()
  })

  it('does not call updateUser when save fails', async () => {
    const updateUser = vi.fn()
    useAuth.mockReturnValue({ user: MOCK_USER, updateUser })
    updateMe.mockRejectedValue(new Error('fail'))

    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(screen.getByText(/failed to save/i)).toBeInTheDocument())
    expect(updateUser).not.toHaveBeenCalled()
  })

  it('sends phone: null when SMS is disabled', async () => {
    updateMe.mockResolvedValue({ ...MOCK_USER, alert_email: true })

    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(updateMe).toHaveBeenCalledWith(expect.objectContaining({ phone: null }))
    })
  })

  it('sends phone value when SMS is enabled and phone is typed', async () => {
    updateMe.mockResolvedValue({ ...MOCK_USER, alert_sms: true, phone: '+15559990000' })

    renderSettings()
    await userEvent.click(screen.getAllByRole('checkbox')[1]) // SMS on
    const input = screen.getByPlaceholderText(/\+1/)
    await userEvent.type(input, '+15559990000')
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(updateMe).toHaveBeenCalledWith(expect.objectContaining({
        alert_sms: true,
        phone: '+15559990000',
      }))
    })
  })
})

// ── Navigation ───────────────────────────────────────────────────────────────

describe('Settings — navigation', () => {
  it('calls onNavigate("dashboard") when Back is clicked', async () => {
    const onNavigate = vi.fn()
    render(<Settings onNavigate={onNavigate} />)
    await userEvent.click(screen.getByRole('button', { name: /back/i }))
    expect(onNavigate).toHaveBeenCalledWith('dashboard')
  })
})
