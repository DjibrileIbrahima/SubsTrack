/**
 * Tests for src/components/Navbar.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Navbar from './Navbar'

vi.mock('../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

vi.mock('../api', () => ({
  getAlerts: vi.fn(),
  markAlertRead: vi.fn(),
}))

import { useAuth } from '../context/AuthContext'
import { getAlerts, markAlertRead } from '../api'

const MOCK_USER = { email: 'user@example.com' }
const mockLogout = vi.fn()

function renderNavbar({ onNavigate = vi.fn(), currentPage = 'dashboard' } = {}) {
  return render(<Navbar onNavigate={onNavigate} currentPage={currentPage} />)
}

beforeEach(() => {
  vi.clearAllMocks()
  useAuth.mockReturnValue({ user: MOCK_USER, logout: mockLogout })
  getAlerts.mockResolvedValue([])
  markAlertRead.mockResolvedValue({ is_read: true })
})

// ── Brand ─────────────────────────────────────────────────────────────────────

describe('Navbar — brand', () => {
  it('renders the SubsTrack brand name', () => {
    renderNavbar()
    expect(screen.getByText('SubsTrack')).toBeInTheDocument()
  })
})

// ── User avatar ───────────────────────────────────────────────────────────────

describe('Navbar — user avatar', () => {
  it('shows the uppercased first letter of the user email', () => {
    renderNavbar()
    expect(screen.getByText('U')).toBeInTheDocument()
  })

  it('shows "U" as fallback when user is null', () => {
    useAuth.mockReturnValue({ user: null, logout: mockLogout })
    renderNavbar()
    expect(screen.getByText('U')).toBeInTheDocument()
  })
})

// ── User dropdown ─────────────────────────────────────────────────────────────

describe('Navbar — user dropdown', () => {
  it('dropdown is hidden before the avatar is clicked', () => {
    renderNavbar()
    expect(screen.queryByText('user@example.com')).not.toBeInTheDocument()
  })

  it('opens dropdown when the avatar button is clicked', async () => {
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: 'U' }))
    expect(screen.getByText('user@example.com')).toBeInTheDocument()
  })

  it('shows "Settings" link when currentPage is "dashboard"', async () => {
    renderNavbar({ currentPage: 'dashboard' })
    await userEvent.click(screen.getByRole('button', { name: 'U' }))
    expect(screen.getByRole('button', { name: /^settings$/i })).toBeInTheDocument()
  })

  it('shows "← Dashboard" link when currentPage is "settings"', async () => {
    renderNavbar({ currentPage: 'settings' })
    await userEvent.click(screen.getByRole('button', { name: 'U' }))
    expect(screen.getByRole('button', { name: /← dashboard/i })).toBeInTheDocument()
  })

  it('clicking "Settings" calls onNavigate("settings")', async () => {
    const onNavigate = vi.fn()
    renderNavbar({ onNavigate, currentPage: 'dashboard' })
    await userEvent.click(screen.getByRole('button', { name: 'U' }))
    await userEvent.click(screen.getByRole('button', { name: /^settings$/i }))
    expect(onNavigate).toHaveBeenCalledWith('settings')
  })

  it('clicking "← Dashboard" calls onNavigate("dashboard")', async () => {
    const onNavigate = vi.fn()
    renderNavbar({ onNavigate, currentPage: 'settings' })
    await userEvent.click(screen.getByRole('button', { name: 'U' }))
    await userEvent.click(screen.getByRole('button', { name: /← dashboard/i }))
    expect(onNavigate).toHaveBeenCalledWith('dashboard')
  })

  it('clicking "Sign out" calls logout', async () => {
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: 'U' }))
    await userEvent.click(screen.getByRole('button', { name: /sign out/i }))
    expect(mockLogout).toHaveBeenCalled()
  })
})

// ── Alerts bell ───────────────────────────────────────────────────────────────

describe('Navbar — alerts bell', () => {
  it('shows no badge when all alerts are read', async () => {
    getAlerts.mockResolvedValue([{ id: '1', message: 'Netflix', is_read: true }])
    renderNavbar()
    await waitFor(() => {}) // let the effect settle
    expect(screen.queryByText('1')).not.toBeInTheDocument()
  })

  it('shows unread badge count when there are unread alerts', async () => {
    getAlerts.mockResolvedValue([
      { id: '1', message: 'Netflix', is_read: false },
      { id: '2', message: 'Spotify', is_read: false },
    ])
    renderNavbar()
    await waitFor(() => expect(screen.getByText('2')).toBeInTheDocument())
  })

  it('shows "9+" badge when more than 9 alerts are unread', async () => {
    const alerts = Array.from({ length: 10 }, (_, i) => ({
      id: String(i), message: `Alert ${i}`, is_read: false,
    }))
    getAlerts.mockResolvedValue(alerts)
    renderNavbar()
    await waitFor(() => expect(screen.getByText('9+')).toBeInTheDocument())
  })

  it('opens alerts dropdown when bell is clicked', async () => {
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: /alerts/i }))
    expect(screen.getByText(/upcoming charges/i)).toBeInTheDocument()
  })

  it('shows "No upcoming alerts" when alerts list is empty', async () => {
    getAlerts.mockResolvedValue([])
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: /alerts/i }))
    await waitFor(() => expect(screen.getByText(/no upcoming alerts/i)).toBeInTheDocument())
  })

  it('shows alert messages in the dropdown', async () => {
    getAlerts.mockResolvedValue([{ id: '1', message: 'Netflix renews tomorrow', is_read: false }])
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: /alerts/i }))
    await waitFor(() => expect(screen.getByText('Netflix renews tomorrow')).toBeInTheDocument())
  })

  it('dismiss button marks alert as read', async () => {
    getAlerts.mockResolvedValue([{ id: 'alert-1', message: 'Netflix', is_read: false }])
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: /alerts/i }))
    await waitFor(() => screen.getByRole('button', { name: '✕' }))
    await userEvent.click(screen.getByRole('button', { name: '✕' }))
    expect(markAlertRead).toHaveBeenCalledWith('alert-1')
  })

  it('read alerts do not show the dismiss button', async () => {
    getAlerts.mockResolvedValue([{ id: '1', message: 'Netflix', is_read: true }])
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: /alerts/i }))
    await waitFor(() => screen.getByText('Netflix'))
    expect(screen.queryByRole('button', { name: '✕' })).not.toBeInTheDocument()
  })
})

// ── Click-outside dismissal ───────────────────────────────────────────────────

describe('Navbar — click outside', () => {
  it('closes user dropdown when clicking outside the navbar', async () => {
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: 'U' }))
    expect(screen.getByText('user@example.com')).toBeInTheDocument()

    fireEvent.mouseDown(document.body)
    await waitFor(() =>
      expect(screen.queryByText('user@example.com')).not.toBeInTheDocument()
    )
  })

  it('closes alerts dropdown when clicking outside the navbar', async () => {
    renderNavbar()
    await userEvent.click(screen.getByRole('button', { name: /alerts/i }))
    expect(screen.getByText(/upcoming charges/i)).toBeInTheDocument()

    fireEvent.mouseDown(document.body)
    await waitFor(() =>
      expect(screen.queryByText(/upcoming charges/i)).not.toBeInTheDocument()
    )
  })
})
