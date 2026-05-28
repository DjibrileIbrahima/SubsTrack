/**
 * Tests for src/pages/auth/ForgotPassword.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ForgotPassword from './ForgotPassword'

vi.mock('../../api', () => ({
  requestPasswordReset: vi.fn(),
}))

import { requestPasswordReset } from '../../api'

beforeEach(() => {
  vi.clearAllMocks()
})

function renderForgot(onBack = vi.fn()) {
  return render(<ForgotPassword onBack={onBack} />)
}

// ── Rendering ─────────────────────────────────────────────────────────────────

describe('ForgotPassword — rendering', () => {
  it('renders "Forgot password?" title', () => {
    renderForgot()
    expect(screen.getByText(/forgot password/i)).toBeInTheDocument()
  })

  it('renders email input', () => {
    renderForgot()
    expect(screen.getByPlaceholderText(/email/i)).toBeInTheDocument()
  })

  it('renders "Send reset link" button', () => {
    renderForgot()
    expect(screen.getByRole('button', { name: /send reset link/i })).toBeInTheDocument()
  })

  it('renders "← Back to sign in" link', () => {
    renderForgot()
    expect(screen.getByRole('button', { name: /back to sign in/i })).toBeInTheDocument()
  })
})

// ── Validation ────────────────────────────────────────────────────────────────

describe('ForgotPassword — validation', () => {
  it('shows error and does not call API when email is empty', async () => {
    renderForgot()
    await userEvent.click(screen.getByRole('button', { name: /send reset link/i }))
    expect(screen.getByText(/email is required/i)).toBeInTheDocument()
    expect(requestPasswordReset).not.toHaveBeenCalled()
  })
})

// ── Submit flow ───────────────────────────────────────────────────────────────

describe('ForgotPassword — submit', () => {
  it('calls requestPasswordReset with the typed email', async () => {
    requestPasswordReset.mockResolvedValue({})
    renderForgot()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'user@example.com')
    await userEvent.click(screen.getByRole('button', { name: /send reset link/i }))
    await waitFor(() => expect(requestPasswordReset).toHaveBeenCalledWith('user@example.com'))
  })

  it('shows "Sending…" and disables button while in flight', async () => {
    let resolve
    requestPasswordReset.mockReturnValue(new Promise(r => { resolve = r }))
    renderForgot()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'user@example.com')
    await userEvent.click(screen.getByRole('button', { name: /send reset link/i }))
    await waitFor(() => expect(screen.getByRole('button', { name: /sending/i })).toBeDisabled())
    resolve({})
  })

  it('shows confirmation screen after success', async () => {
    requestPasswordReset.mockResolvedValue({})
    renderForgot()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'user@example.com')
    await userEvent.click(screen.getByRole('button', { name: /send reset link/i }))
    await waitFor(() => expect(screen.getByText(/check your email/i)).toBeInTheDocument())
  })

  it('confirmation screen displays the submitted email', async () => {
    requestPasswordReset.mockResolvedValue({})
    renderForgot()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'user@example.com')
    await userEvent.click(screen.getByRole('button', { name: /send reset link/i }))
    await waitFor(() => expect(screen.getByText(/user@example\.com/)).toBeInTheDocument())
  })

  it('shows error message on API failure', async () => {
    requestPasswordReset.mockRejectedValue(new Error('Network error'))
    renderForgot()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'user@example.com')
    await userEvent.click(screen.getByRole('button', { name: /send reset link/i }))
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument()
  })

  it('submits on Enter key press', async () => {
    requestPasswordReset.mockResolvedValue({})
    renderForgot()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'user@example.com{Enter}')
    await waitFor(() => expect(requestPasswordReset).toHaveBeenCalled())
  })
})

// ── Navigation ────────────────────────────────────────────────────────────────

describe('ForgotPassword — navigation', () => {
  it('"← Back to sign in" in form calls onBack', async () => {
    const onBack = vi.fn()
    renderForgot(onBack)
    await userEvent.click(screen.getByRole('button', { name: /back to sign in/i }))
    expect(onBack).toHaveBeenCalled()
  })

  it('"Back to sign in" on confirmation screen calls onBack', async () => {
    const onBack = vi.fn()
    requestPasswordReset.mockResolvedValue({})
    renderForgot(onBack)
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'user@example.com')
    await userEvent.click(screen.getByRole('button', { name: /send reset link/i }))
    await waitFor(() => screen.getByText(/check your email/i))
    await userEvent.click(screen.getByRole('button', { name: /back to sign in/i }))
    expect(onBack).toHaveBeenCalled()
  })
})
