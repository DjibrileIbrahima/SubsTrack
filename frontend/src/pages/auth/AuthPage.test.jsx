/**
 * Tests for src/pages/auth/AuthPage.jsx
 *
 * Tests the view-routing logic (login / register / forgot / reset) and the
 * ?token= URL handling. Child components are stubbed so tests focus purely
 * on AuthPage's own state machine.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AuthPage from './AuthPage'

// ── Stub child components ─────────────────────────────────────────────────────
// Each stub renders a unique marker string and exposes the props it receives
// as clickable buttons so tests can trigger navigation callbacks.

vi.mock('./Login', () => ({
  default: ({ onSwitch, onForgot, successMessage }) => (
    <div>
      <span>login-view</span>
      {successMessage && <span data-testid="success-msg">{successMessage}</span>}
      <button onClick={onForgot}>go-forgot</button>
      <button onClick={onSwitch}>go-register</button>
    </div>
  ),
}))

vi.mock('./Register', () => ({
  default: ({ onSwitch }) => (
    <div>
      <span>register-view</span>
      <button onClick={onSwitch}>go-login</button>
    </div>
  ),
}))

vi.mock('./ForgotPassword', () => ({
  default: ({ onBack }) => (
    <div>
      <span>forgot-view</span>
      <button onClick={onBack}>go-back</button>
    </div>
  ),
}))

vi.mock('./ResetPassword', () => ({
  default: ({ onSuccess }) => (
    <div>
      <span>reset-view</span>
      <button onClick={onSuccess}>reset-done</button>
    </div>
  ),
}))

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { search: '', pathname: '/', href: '' },
  })
  vi.spyOn(window.history, 'replaceState').mockImplementation(() => {})
})

// ── Default view ──────────────────────────────────────────────────────────────

describe('AuthPage — default view', () => {
  it('shows the login view by default', () => {
    render(<AuthPage />)
    expect(screen.getByText('login-view')).toBeInTheDocument()
  })

  it('does not show register, forgot, or reset views by default', () => {
    render(<AuthPage />)
    expect(screen.queryByText('register-view')).not.toBeInTheDocument()
    expect(screen.queryByText('forgot-view')).not.toBeInTheDocument()
    expect(screen.queryByText('reset-view')).not.toBeInTheDocument()
  })
})

// ── Navigation ────────────────────────────────────────────────────────────────

describe('AuthPage — navigation', () => {
  it('navigates to forgot view when Login calls onForgot', async () => {
    render(<AuthPage />)
    await userEvent.click(screen.getByRole('button', { name: 'go-forgot' }))
    expect(screen.getByText('forgot-view')).toBeInTheDocument()
  })

  it('returns to login from forgot view', async () => {
    render(<AuthPage />)
    await userEvent.click(screen.getByRole('button', { name: 'go-forgot' }))
    await userEvent.click(screen.getByRole('button', { name: 'go-back' }))
    expect(screen.getByText('login-view')).toBeInTheDocument()
  })

  it('navigates to register view when Login calls onSwitch', async () => {
    render(<AuthPage />)
    await userEvent.click(screen.getByRole('button', { name: 'go-register' }))
    expect(screen.getByText('register-view')).toBeInTheDocument()
  })

  it('returns to login from register view', async () => {
    render(<AuthPage />)
    await userEvent.click(screen.getByRole('button', { name: 'go-register' }))
    await userEvent.click(screen.getByRole('button', { name: 'go-login' }))
    expect(screen.getByText('login-view')).toBeInTheDocument()
  })
})

// ── ?token= URL handling ──────────────────────────────────────────────────────

describe('AuthPage — reset token in URL', () => {
  it('shows reset view when ?token= is present in URL', () => {
    window.location.search = '?token=abc123'
    render(<AuthPage />)
    expect(screen.getByText('reset-view')).toBeInTheDocument()
  })

  it('does not show login view when token is in URL', () => {
    window.location.search = '?token=abc123'
    render(<AuthPage />)
    expect(screen.queryByText('login-view')).not.toBeInTheDocument()
  })

  it('after reset success switches to login view', async () => {
    window.location.search = '?token=abc123'
    render(<AuthPage />)
    await userEvent.click(screen.getByRole('button', { name: 'reset-done' }))
    expect(screen.getByText('login-view')).toBeInTheDocument()
  })

  it('after reset success shows the success message on the login view', async () => {
    window.location.search = '?token=abc123'
    render(<AuthPage />)
    await userEvent.click(screen.getByRole('button', { name: 'reset-done' }))
    expect(screen.getByTestId('success-msg')).toBeInTheDocument()
  })

  it('after reset success clears the token from the URL', async () => {
    window.location.search = '?token=abc123'
    render(<AuthPage />)
    await userEvent.click(screen.getByRole('button', { name: 'reset-done' }))
    expect(window.history.replaceState).toHaveBeenCalled()
  })
})
