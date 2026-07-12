import { useState, useCallback } from 'react'
import { getLinkToken, getUpdateLinkToken, exchangeToken } from '../api'

export function usePlaid(onSuccess) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const initAndOpen = useCallback(async () => {
    setLoading(true)
    setError(null)

    let token
    try {
      token = await getLinkToken()
    } catch (e) {
      setError('Failed to fetch link token')
      setLoading(false)
      return
    }

    try {
      window.Plaid.create({
        token,
        onSuccess: async (public_token, metadata) => {
          try {
            await exchangeToken(public_token, metadata.institution?.name || 'Unknown Bank')
            onSuccess?.()
          } catch (e) {
            setError('Failed to save bank connection')
          }
        },
        onExit: (err) => {
          if (err) {
            setError('Bank connection failed')
          }
        },
      }).open()
    } catch (e) {
      setError('Failed to open bank connection')
    }

    setLoading(false)
  }, [onSuccess])

  // Update mode: re-authenticate an existing item (e.g. after ITEM_LOGIN_REQUIRED).
  // No token exchange happens — Plaid repairs the item behind the same access token.
  const openUpdate = useCallback(async (accountId) => {
    setLoading(true)
    setError(null)

    let token
    try {
      token = await getUpdateLinkToken(accountId)
    } catch (e) {
      setError('Failed to fetch link token')
      setLoading(false)
      return
    }

    try {
      window.Plaid.create({
        token,
        onSuccess: () => {
          onSuccess?.()
        },
        onExit: (err) => {
          if (err) {
            setError('Bank reconnection failed')
          }
        },
      }).open()
    } catch (e) {
      setError('Failed to open bank connection')
    }

    setLoading(false)
  }, [onSuccess])

  return { initAndOpen, openUpdate, loading, error }
}
