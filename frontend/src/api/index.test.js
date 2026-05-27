/**
 * Tests for src/api/index.js
 *
 * Each exported function is tested to call the correct endpoint and return the
 * right slice of the response. The axios instance is mocked at the module level.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ── Mock the axios module before importing api ────────────────────────────────
vi.mock('axios', () => {
  const mockAxios = {
    create: vi.fn(() => mockInstance),
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  }
  const mockInstance = {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  }
  return { default: mockAxios }
})

// ─────────────────────────────────────────────────────────────────────────────

// After mocking, import the API module
import axios from 'axios'

// Obtain a reference to the mock instance that api/index.js created
const mockInstance = axios.create()

import api, {
  getLinkToken,
  exchangeToken,
  getAccounts,
  getSavedSubscriptions,
  syncSubscriptions,
  addManualSubscription,
  deleteSubscription,
  getSummary,
  getAlerts,
  markAlertRead,
  deleteAlert,
} from '../api'


describe('API module', () => {
  it('creates axios instance with correct base config', () => {
    expect(axios.create).toHaveBeenCalledWith(
      expect.objectContaining({
        baseURL: '/api',
        withCredentials: true,
      })
    )
  })
})

describe('getLinkToken', () => {
  it('calls POST /auth/link-token and returns link_token', async () => {
    mockInstance.post.mockResolvedValue({ data: { link_token: 'link-sandbox-xxx' } })
    const token = await getLinkToken()
    expect(mockInstance.post).toHaveBeenCalledWith('/auth/link-token')
    expect(token).toBe('link-sandbox-xxx')
  })
})

describe('exchangeToken', () => {
  it('calls POST /auth/exchange-token with correct payload', async () => {
    mockInstance.post.mockResolvedValue({ data: { message: 'ok' } })
    await exchangeToken('public-token', 'Chase')
    expect(mockInstance.post).toHaveBeenCalledWith('/auth/exchange-token', {
      public_token: 'public-token',
      institution_name: 'Chase',
    })
  })
})

describe('getAccounts', () => {
  it('calls GET /auth/accounts and returns accounts array', async () => {
    const accounts = [{ id: '1', institution: 'Chase' }]
    mockInstance.get.mockResolvedValue({ data: { accounts } })
    const result = await getAccounts()
    expect(mockInstance.get).toHaveBeenCalledWith('/auth/accounts')
    expect(result).toEqual(accounts)
  })
})

describe('getSavedSubscriptions', () => {
  it('calls GET /subscriptions/saved and returns data', async () => {
    const data = { subscriptions: [], total_monthly_spend: 0 }
    mockInstance.get.mockResolvedValue({ data })
    const result = await getSavedSubscriptions()
    expect(mockInstance.get).toHaveBeenCalledWith('/subscriptions/saved')
    expect(result).toEqual(data)
  })
})

describe('syncSubscriptions', () => {
  it('calls GET /subscriptions and returns data', async () => {
    const data = { subscriptions: [], total_monthly_spend: 0 }
    mockInstance.get.mockResolvedValue({ data })
    const result = await syncSubscriptions()
    expect(mockInstance.get).toHaveBeenCalledWith('/subscriptions')
    expect(result).toEqual(data)
  })
})

describe('addManualSubscription', () => {
  it('calls POST /subscriptions/manual with payload', async () => {
    const payload = { merchant: 'Netflix', amount: 15.99, frequency: 'monthly' }
    mockInstance.post.mockResolvedValue({ data: { subscription: payload } })
    await addManualSubscription(payload)
    expect(mockInstance.post).toHaveBeenCalledWith('/subscriptions/manual', payload)
  })
})

describe('deleteSubscription', () => {
  it('calls DELETE /subscriptions/{id}', async () => {
    mockInstance.delete.mockResolvedValue({ data: { message: 'removed' } })
    await deleteSubscription('sub-id-123')
    expect(mockInstance.delete).toHaveBeenCalledWith('/subscriptions/sub-id-123')
  })
})

describe('getSummary', () => {
  it('calls GET /summary and returns monthly_summary array', async () => {
    const monthly_summary = [{ month: '2024-01', total: 25.98 }]
    mockInstance.get.mockResolvedValue({ data: { monthly_summary } })
    const result = await getSummary()
    expect(mockInstance.get).toHaveBeenCalledWith('/summary')
    expect(result).toEqual(monthly_summary)
  })
})

describe('getAlerts', () => {
  it('calls GET /alerts and returns alerts array', async () => {
    const alerts = [{ id: '1', message: 'Netflix renews' }]
    mockInstance.get.mockResolvedValue({ data: { alerts } })
    const result = await getAlerts()
    expect(mockInstance.get).toHaveBeenCalledWith('/alerts')
    expect(result).toEqual(alerts)
  })
})

describe('markAlertRead', () => {
  it('calls PATCH /alerts/{id}/read', async () => {
    mockInstance.patch.mockResolvedValue({ data: { is_read: true } })
    const result = await markAlertRead('alert-id-1')
    expect(mockInstance.patch).toHaveBeenCalledWith('/alerts/alert-id-1/read')
    expect(result.is_read).toBe(true)
  })
})

describe('deleteAlert', () => {
  it('calls DELETE /alerts/{id}', async () => {
    mockInstance.delete.mockResolvedValue({ data: { message: 'deleted' } })
    await deleteAlert('alert-id-1')
    expect(mockInstance.delete).toHaveBeenCalledWith('/alerts/alert-id-1')
  })
})
