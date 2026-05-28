/**
 * Tests for src/pages/auth/OAuthCallback.jsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import OAuthCallback from './OAuthCallback'

beforeEach(() => {
  Object.defineProperty(window, 'location', {
    writable: true,
    value: { replace: vi.fn(), href: '' },
  })
})

describe('OAuthCallback', () => {
  it('renders "Signing you in…" text', () => {
    render(<OAuthCallback />)
    expect(screen.getByText(/signing you in/i)).toBeInTheDocument()
  })

  it('redirects to "/" on mount', () => {
    render(<OAuthCallback />)
    expect(window.location.replace).toHaveBeenCalledWith('/')
  })
})
