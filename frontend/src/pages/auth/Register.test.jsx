/**
 * Tests for src/pages/auth/Register.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Register from './Register'

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
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { href: '' },
  })
})

function renderRegister(onSwitch = vi.fn()) {
  return render(<Register onSwitch={onSwitch} />)
}

describe('Register', () => {
  it('renders all input fields', () => {
    renderRegister()
    expect(screen.getByPlaceholderText(/email/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/^password/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/confirm password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument()
  })

  it('shows error when email is empty', async () => {
    renderRegister()
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))
    expect(await screen.findByText(/all fields required/i)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('shows error for password shorter than 8 characters', async () => {
    renderRegister()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'a@b.com')
    await userEvent.type(screen.getByPlaceholderText(/^password/i), 'short')
    await userEvent.type(screen.getByPlaceholderText(/confirm password/i), 'short')
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))
    expect(await screen.findByText(/8 characters/i)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('shows error when passwords do not match', async () => {
    renderRegister()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'a@b.com')
    await userEvent.type(screen.getByPlaceholderText(/^password/i), 'password123')
    await userEvent.type(screen.getByPlaceholderText(/confirm password/i), 'different123')
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))
    expect(await screen.findByText(/do not match/i)).toBeInTheDocument()
    expect(api.post).not.toHaveBeenCalled()
  })

  it('calls register API with email and password', async () => {
    const loginFn = vi.fn().mockResolvedValue(undefined)
    useAuth.mockReturnValue({ login: loginFn })
    api.post.mockResolvedValue({})

    renderRegister()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'new@example.com')
    await userEvent.type(screen.getByPlaceholderText(/^password/i), 'secure123')
    await userEvent.type(screen.getByPlaceholderText(/confirm password/i), 'secure123')
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/auth/register', {
        email: 'new@example.com',
        password: 'secure123',
      })
    })
  })

  it('calls login() after successful registration', async () => {
    const loginFn = vi.fn().mockResolvedValue(undefined)
    useAuth.mockReturnValue({ login: loginFn })
    api.post.mockResolvedValue({})

    renderRegister()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'new@example.com')
    await userEvent.type(screen.getByPlaceholderText(/^password/i), 'secure123')
    await userEvent.type(screen.getByPlaceholderText(/confirm password/i), 'secure123')
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() => expect(loginFn).toHaveBeenCalled())
  })

  it('shows API error detail on failure', async () => {
    useAuth.mockReturnValue({ login: vi.fn() })
    api.post.mockRejectedValue({ response: { data: { detail: 'Email already registered' } } })

    renderRegister()
    await userEvent.type(screen.getByPlaceholderText(/email/i), 'existing@example.com')
    await userEvent.type(screen.getByPlaceholderText(/^password/i), 'password123')
    await userEvent.type(screen.getByPlaceholderText(/confirm password/i), 'password123')
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByText(/email already registered/i)).toBeInTheDocument()
  })

  it('navigates to Google OAuth on button click', async () => {
    renderRegister()
    await userEvent.click(screen.getByRole('button', { name: /continue with google/i }))
    expect(window.location.href).toBe('/api/auth/google')
  })

  it('calls onSwitch when "Sign in" link is clicked', async () => {
    const onSwitch = vi.fn()
    renderRegister(onSwitch)
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    expect(onSwitch).toHaveBeenCalled()
  })
})
