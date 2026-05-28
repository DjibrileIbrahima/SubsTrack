/**
 * Tests for src/pages/auth/ResetPassword.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ResetPassword from './ResetPassword'

vi.mock('../../api', () => ({
  resetPassword: vi.fn(),
}))

import { resetPassword } from '../../api'

beforeEach(() => {
  vi.clearAllMocks()
})

function renderReset({ token = 'test-token-abc', onSuccess = vi.fn() } = {}) {
  return render(<ResetPassword token={token} onSuccess={onSuccess} />)
}

// Helpers for the two password inputs that share "password" in their text.
// Using exact strings avoids ambiguity with /new password/i matching both.
const newPwField = () => screen.getByPlaceholderText('New password')
const confirmPwField = () => screen.getByPlaceholderText('Confirm new password')
const submitBtn = () => screen.getByRole('button', { name: /set new password/i })

// ── Rendering ─────────────────────────────────────────────────────────────────

describe('ResetPassword — rendering', () => {
  it('renders "Set new password" heading', () => {
    renderReset()
    expect(screen.getByRole('heading', { name: /set new password/i })).toBeInTheDocument()
  })

  it('renders new password input', () => {
    renderReset()
    expect(newPwField()).toBeInTheDocument()
  })

  it('renders confirm password input', () => {
    renderReset()
    expect(confirmPwField()).toBeInTheDocument()
  })

  it('renders submit button', () => {
    renderReset()
    expect(submitBtn()).toBeInTheDocument()
  })
})

// ── Validation ────────────────────────────────────────────────────────────────

describe('ResetPassword — validation', () => {
  it('shows error when both fields are empty', async () => {
    renderReset()
    await userEvent.click(submitBtn())
    expect(screen.getByText(/all fields required/i)).toBeInTheDocument()
    expect(resetPassword).not.toHaveBeenCalled()
  })

  it('shows error when password is fewer than 8 characters', async () => {
    renderReset()
    await userEvent.type(newPwField(), 'short')
    await userEvent.type(confirmPwField(), 'short')
    await userEvent.click(submitBtn())
    expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument()
    expect(resetPassword).not.toHaveBeenCalled()
  })

  it('shows error when passwords do not match', async () => {
    renderReset()
    await userEvent.type(newPwField(), 'password123')
    await userEvent.type(confirmPwField(), 'different456')
    await userEvent.click(submitBtn())
    expect(screen.getByText(/do not match/i)).toBeInTheDocument()
    expect(resetPassword).not.toHaveBeenCalled()
  })
})

// ── Submit flow ───────────────────────────────────────────────────────────────

describe('ResetPassword — submit', () => {
  it('calls resetPassword with the correct token and password', async () => {
    resetPassword.mockResolvedValue({})
    renderReset({ token: 'my-reset-token' })
    await userEvent.type(newPwField(), 'newpassword1')
    await userEvent.type(confirmPwField(), 'newpassword1')
    await userEvent.click(submitBtn())
    await waitFor(() =>
      expect(resetPassword).toHaveBeenCalledWith('my-reset-token', 'newpassword1')
    )
  })

  it('calls onSuccess after a successful reset', async () => {
    const onSuccess = vi.fn()
    resetPassword.mockResolvedValue({})
    renderReset({ onSuccess })
    await userEvent.type(newPwField(), 'newpassword1')
    await userEvent.type(confirmPwField(), 'newpassword1')
    await userEvent.click(submitBtn())
    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
  })

  it('shows "Saving…" and disables button while in flight', async () => {
    let resolve
    resetPassword.mockReturnValue(new Promise(r => { resolve = r }))
    renderReset()
    await userEvent.type(newPwField(), 'newpassword1')
    await userEvent.type(confirmPwField(), 'newpassword1')
    await userEvent.click(submitBtn())
    await waitFor(() => expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled())
    resolve({})
  })

  it('shows API error detail on failure', async () => {
    resetPassword.mockRejectedValue({
      response: { data: { detail: 'Invalid or expired reset link' } },
    })
    renderReset()
    await userEvent.type(newPwField(), 'newpassword1')
    await userEvent.type(confirmPwField(), 'newpassword1')
    await userEvent.click(submitBtn())
    expect(await screen.findByText(/invalid or expired reset link/i)).toBeInTheDocument()
  })

  it('shows fallback error when response has no detail', async () => {
    resetPassword.mockRejectedValue(new Error('Network error'))
    renderReset()
    await userEvent.type(newPwField(), 'newpassword1')
    await userEvent.type(confirmPwField(), 'newpassword1')
    await userEvent.click(submitBtn())
    expect(await screen.findByText(/invalid or expired reset link/i)).toBeInTheDocument()
  })

  it('submits on Enter key press in the confirm field', async () => {
    resetPassword.mockResolvedValue({})
    renderReset()
    await userEvent.type(newPwField(), 'newpassword1')
    await userEvent.type(confirmPwField(), 'newpassword1{Enter}')
    await waitFor(() => expect(resetPassword).toHaveBeenCalled())
  })
})
