/**
 * Tests for src/hooks/usePlaid.js
 *
 * Covers: link token fetch, Plaid.create invocation, success/exit callbacks,
 * and error state management.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePlaid } from './usePlaid'

// ── Mock API functions ────────────────────────────────────────────────────────
vi.mock('../api', () => ({
  getLinkToken: vi.fn(),
  getUpdateLinkToken: vi.fn(),
  exchangeToken: vi.fn(),
}))

import { getLinkToken, getUpdateLinkToken, exchangeToken } from '../api'

// ── Mock window.Plaid ─────────────────────────────────────────────────────────
const mockPlaidOpen = vi.fn()
const mockPlaidCreate = vi.fn(() => ({ open: mockPlaidOpen }))

beforeEach(() => {
  vi.clearAllMocks()
  window.Plaid = { create: mockPlaidCreate }
})

// ─────────────────────────────────────────────────────────────────────────────

describe('usePlaid', () => {
  it('returns loading=false and error=null initially', () => {
    const { result } = renderHook(() => usePlaid())
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
  })

  it('fetches link token and calls Plaid.create on initAndOpen', async () => {
    getLinkToken.mockResolvedValue('link-sandbox-test')

    const { result } = renderHook(() => usePlaid())

    await act(async () => {
      await result.current.initAndOpen()
    })

    expect(getLinkToken).toHaveBeenCalledOnce()
    expect(mockPlaidCreate).toHaveBeenCalledWith(
      expect.objectContaining({ token: 'link-sandbox-test' })
    )
    expect(mockPlaidOpen).toHaveBeenCalled()
  })

  it('sets error when getLinkToken fails', async () => {
    getLinkToken.mockRejectedValue(new Error('network error'))

    const { result } = renderHook(() => usePlaid())

    await act(async () => {
      await result.current.initAndOpen()
    })

    expect(result.current.error).toBe('Failed to fetch link token')
    expect(mockPlaidCreate).not.toHaveBeenCalled()
  })

  it('calls exchangeToken and onSuccess on Plaid success callback', async () => {
    getLinkToken.mockResolvedValue('link-sandbox-test')
    exchangeToken.mockResolvedValue({})
    const onSuccess = vi.fn()

    const { result } = renderHook(() => usePlaid(onSuccess))

    await act(async () => {
      await result.current.initAndOpen()
    })

    // Extract and invoke the onSuccess callback that was passed to Plaid.create
    const plaidConfig = mockPlaidCreate.mock.calls[0][0]
    await act(async () => {
      await plaidConfig.onSuccess('public-token', { institution: { name: 'Chase' } })
    })

    expect(exchangeToken).toHaveBeenCalledWith('public-token', 'Chase')
    expect(onSuccess).toHaveBeenCalled()
  })

  it('falls back to "Unknown Bank" when institution name is missing', async () => {
    getLinkToken.mockResolvedValue('link-sandbox-test')
    exchangeToken.mockResolvedValue({})

    const { result } = renderHook(() => usePlaid())

    await act(async () => {
      await result.current.initAndOpen()
    })

    const plaidConfig = mockPlaidCreate.mock.calls[0][0]
    await act(async () => {
      await plaidConfig.onSuccess('public-token', { institution: null })
    })

    expect(exchangeToken).toHaveBeenCalledWith('public-token', 'Unknown Bank')
  })

  it('sets error when exchangeToken fails', async () => {
    getLinkToken.mockResolvedValue('link-sandbox-test')
    exchangeToken.mockRejectedValue(new Error('save failed'))

    const { result } = renderHook(() => usePlaid())

    await act(async () => {
      await result.current.initAndOpen()
    })

    const plaidConfig = mockPlaidCreate.mock.calls[0][0]
    await act(async () => {
      await plaidConfig.onSuccess('public-token', { institution: { name: 'Chase' } })
    })

    expect(result.current.error).toBe('Failed to save bank connection')
  })

  it('sets error on Plaid onExit with an error', async () => {
    getLinkToken.mockResolvedValue('link-sandbox-test')

    const { result } = renderHook(() => usePlaid())

    await act(async () => {
      await result.current.initAndOpen()
    })

    const plaidConfig = mockPlaidCreate.mock.calls[0][0]
    act(() => {
      plaidConfig.onExit({ error_code: 'INSTITUTION_DOWN' })
    })

    expect(result.current.error).toBe('Bank connection failed')
  })

  it('does NOT set error when Plaid onExit is called without an error (user cancelled)', async () => {
    getLinkToken.mockResolvedValue('link-sandbox-test')

    const { result } = renderHook(() => usePlaid())

    await act(async () => {
      await result.current.initAndOpen()
    })

    const plaidConfig = mockPlaidCreate.mock.calls[0][0]
    act(() => {
      plaidConfig.onExit(null)  // null means user closed the modal
    })

    expect(result.current.error).toBeNull()
  })

  it('openUpdate fetches an update-mode token and opens Plaid', async () => {
    getUpdateLinkToken.mockResolvedValue('link-update-token')
    const onSuccess = vi.fn()

    const { result } = renderHook(() => usePlaid(onSuccess))

    await act(async () => {
      await result.current.openUpdate('account-123')
    })

    expect(getUpdateLinkToken).toHaveBeenCalledWith('account-123')
    expect(mockPlaidCreate).toHaveBeenCalledWith(
      expect.objectContaining({ token: 'link-update-token' })
    )
    expect(mockPlaidOpen).toHaveBeenCalled()

    // Update mode has no token exchange — success just notifies the caller
    const plaidConfig = mockPlaidCreate.mock.calls[0][0]
    act(() => {
      plaidConfig.onSuccess()
    })
    expect(exchangeToken).not.toHaveBeenCalled()
    expect(onSuccess).toHaveBeenCalled()
  })

  it('openUpdate sets error when the token fetch fails', async () => {
    getUpdateLinkToken.mockRejectedValue(new Error('boom'))

    const { result } = renderHook(() => usePlaid())

    await act(async () => {
      await result.current.openUpdate('account-123')
    })

    expect(result.current.error).toBe('Failed to fetch link token')
    expect(mockPlaidCreate).not.toHaveBeenCalled()
  })
})
