/**
 * Tests for src/context/AuthContext.jsx
 *
 * Verifies: initial load, authenticated state, unauthenticated state,
 * login(), logout(), and isAuthenticated flag.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import { AuthProvider, useAuth } from './AuthContext'

// ── Mock the api module ───────────────────────────────────────────────────────
vi.mock('../api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

import api from '../api'

// Helper: a component that renders auth state for inspection
function AuthConsumer() {
  const { user, loading, isAuthenticated } = useAuth()
  if (loading) return <div>loading</div>
  return (
    <div>
      <div data-testid="email">{user?.email ?? 'none'}</div>
      <div data-testid="authenticated">{String(isAuthenticated)}</div>
    </div>
  )
}

// Helper: a component that calls login/logout
function AuthActions() {
  const { login, logout } = useAuth()
  return (
    <>
      <button onClick={login}>login</button>
      <button onClick={logout}>logout</button>
    </>
  )
}

// Helper: a component that calls updateUser
function UpdateUserAction({ newUser }) {
  const { updateUser } = useAuth()
  return <button onClick={() => updateUser(newUser)}>update</button>
}

// ─────────────────────────────────────────────────────────────────────────────

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows loading state initially', () => {
    api.get.mockReturnValue(new Promise(() => {})) // never resolves
    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )
    expect(screen.getByText('loading')).toBeInTheDocument()
  })

  it('sets user when /me succeeds', async () => {
    api.get.mockResolvedValue({ data: { email: 'user@example.com' } })
    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )
    await waitFor(() => {
      expect(screen.getByTestId('email')).toHaveTextContent('user@example.com')
    })
    expect(screen.getByTestId('authenticated')).toHaveTextContent('true')
  })

  it('sets user to null when /me fails (unauthenticated)', async () => {
    api.get.mockRejectedValue(new Error('401'))
    render(
      <AuthProvider>
        <AuthConsumer />
      </AuthProvider>
    )
    await waitFor(() => {
      expect(screen.getByTestId('email')).toHaveTextContent('none')
    })
    expect(screen.getByTestId('authenticated')).toHaveTextContent('false')
  })

  it('login() fetches /me and updates user', async () => {
    // First call (useEffect mount): unauthenticated
    api.get.mockRejectedValueOnce(new Error('401'))
    // Second call (login()): authenticated
    api.get.mockResolvedValueOnce({ data: { email: 'loggedin@example.com' } })

    render(
      <AuthProvider>
        <AuthConsumer />
        <AuthActions />
      </AuthProvider>
    )

    await waitFor(() => expect(screen.getByTestId('email')).toHaveTextContent('none'))

    await act(async () => {
      screen.getByRole('button', { name: 'login' }).click()
    })

    await waitFor(() => {
      expect(screen.getByTestId('email')).toHaveTextContent('loggedin@example.com')
    })
  })

  it('logout() clears user and calls /auth/logout', async () => {
    api.get.mockResolvedValue({ data: { email: 'user@example.com' } })
    api.post.mockResolvedValue({})

    render(
      <AuthProvider>
        <AuthConsumer />
        <AuthActions />
      </AuthProvider>
    )

    await waitFor(() => expect(screen.getByTestId('authenticated')).toHaveTextContent('true'))

    await act(async () => {
      screen.getByRole('button', { name: 'logout' }).click()
    })

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('false')
    })
    expect(api.post).toHaveBeenCalledWith('/auth/logout')
  })

  it('updateUser() replaces user state without an API call', async () => {
    api.get.mockResolvedValue({ data: { email: 'original@example.com' } })

    const updated = { email: 'updated@example.com', alert_email: true }

    render(
      <AuthProvider>
        <AuthConsumer />
        <UpdateUserAction newUser={updated} />
      </AuthProvider>
    )

    await waitFor(() =>
      expect(screen.getByTestId('email')).toHaveTextContent('original@example.com')
    )

    await act(async () => {
      screen.getByRole('button', { name: 'update' }).click()
    })

    expect(screen.getByTestId('email')).toHaveTextContent('updated@example.com')
    // updateUser should not trigger any extra API calls beyond the initial /me
    expect(api.get).toHaveBeenCalledTimes(1)
  })

  it('logout() still clears user even if API call fails', async () => {
    api.get.mockResolvedValue({ data: { email: 'user@example.com' } })
    api.post.mockRejectedValue(new Error('network error'))

    render(
      <AuthProvider>
        <AuthConsumer />
        <AuthActions />
      </AuthProvider>
    )

    await waitFor(() => expect(screen.getByTestId('authenticated')).toHaveTextContent('true'))

    await act(async () => {
      screen.getByRole('button', { name: 'logout' }).click()
    })

    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('false')
    })
  })
})
