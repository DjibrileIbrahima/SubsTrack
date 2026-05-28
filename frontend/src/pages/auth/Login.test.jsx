/**
 * Tests for src/pages/auth/Login.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Login from './Login'

// ── Mocks ─────────────────────────────────────────────────────────────────────
vi.mock('../../api', () => ({
  default: { post: vi.fn() },
}))

vi.mock('../../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

import api from '../../api'
import { useAuth } from '../../context/AuthContext'

beforeEach(() => {
  vi.clearAllMocks()
  useAuth.mockReturnValue({ login: vi.fn() })
  // Store original for restore
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { href: '' },
  })
})

function renderLogin({ onSwitch = vi.fn(), onForgot = vi.fn(), successMessage = null } = {}) {
  return render(<Login onSwitch={onSwitch} onForgot={onForgot} successMessage={successMessage} />)
}

// ─────────────────────────────────────────────────────────────────────────────

describe('Login', () => {
  it('renders email and password inputs', () => {
    renderLogin()
    expect(screen.getByPlaceholderText(/email/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('renders Google OAuth button', () => {
    renderLogin()
    expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument()
  })

  it('shows error when fields are empty', async () => {
    renderLogin()
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(await screen.findByText(/all fields required/i)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('calls login API with correct payload', async () => {
    const loginFn = vi.fn()
    useAuth.mockReturnValue({ login: loginFn })
    api.post.mockResolvedValue({})
    loginFn.mockResolvedValue(undefined)

    renderLogin()

    await userEvent.type(screen.getByPlaceholderText(/email/i), 'user@example.com')
    await userEvent.type(screen.getByPlaceholderText(/password/i), 'password123')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/auth/login', {
        email: 'user@example.com',
        password: 'password123',
      })
    })
  })

  it('calls login() context method after successful API call', async () => {
    const loginFn = vi.fn().mockResolvedValue(undefined)
    useAuth.mockReturnValue({ login: loginFn })
    api.post.mockResolvedValue({})

    renderLogin()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'user@example.com')
    await userEvent.type(screen.getByPlaceholderText(/password/i), 'password123')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => expect(loginFn).toHaveBeenCalled())
  })

  it('shows API error message on failed login', async () => {
    useAuth.mockReturnValue({ login: vi.fn() })
    api.post.mockRejectedValue({
      response: { data: { detail: 'Invalid email or password' } },
    })

    renderLogin()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'bad@example.com')
    await userEvent.type(screen.getByPlaceholderText(/password/i), 'wrongpass')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByText(/invalid email or password/i)).toBeInTheDocument()
  })

  it('shows fallback error when no detail in API response', async () => {
    useAuth.mockReturnValue({ login: vi.fn() })
    api.post.mockRejectedValue(new Error('Network Error'))

    renderLogin()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'a@b.com')
    await userEvent.type(screen.getByPlaceholderText(/password/i), 'password123')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByText(/invalid email or password/i)).toBeInTheDocument()
  })

  it('disables sign-in button while loading', async () => {
    useAuth.mockReturnValue({ login: vi.fn() })
    let resolve
    api.post.mockReturnValue(new Promise(r => { resolve = r }))

    renderLogin()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'a@b.com')
    await userEvent.type(screen.getByPlaceholderText(/password/i), 'password123')

    const button = screen.getByRole('button', { name: /sign in/i })
    await userEvent.click(button)

    await waitFor(() => expect(button).toBeDisabled())
    resolve({})
  })

  it('submits on Enter key press', async () => {
    const loginFn = vi.fn().mockResolvedValue(undefined)
    useAuth.mockReturnValue({ login: loginFn })
    api.post.mockResolvedValue({})

    renderLogin()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'a@b.com')
    await userEvent.type(screen.getByPlaceholderText(/password/i), 'password123{Enter}')

    await waitFor(() => expect(api.post).toHaveBeenCalled())
  })

  it('navigates to Google OAuth on button click', async () => {
    renderLogin()
    await userEvent.click(screen.getByRole('button', { name: /continue with google/i }))
    expect(window.location.href).toBe('/api/auth/google')
  })

  it('calls onSwitch when "Sign up" link is clicked', async () => {
    const onSwitch = vi.fn()
    renderLogin({ onSwitch })
    await userEvent.click(screen.getByRole('button', { name: /sign up/i }))
    expect(onSwitch).toHaveBeenCalled()
  })

  it('calls onForgot when "Forgot password?" is clicked', async () => {
    const onForgot = vi.fn()
    renderLogin({ onForgot })
    await userEvent.click(screen.getByRole('button', { name: /forgot password/i }))
    expect(onForgot).toHaveBeenCalled()
  })

  it('displays successMessage when provided', () => {
    renderLogin({ successMessage: 'Password updated — sign in with your new password.' })
    expect(screen.getByText(/password updated/i)).toBeInTheDocument()
  })

  it('does not display a success message when successMessage is null', () => {
    renderLogin({ successMessage: null })
    expect(screen.queryByText(/password updated/i)).not.toBeInTheDocument()
  })
})
