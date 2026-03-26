import { useState, useCallback } from 'react'
import { getLinkToken, exchangeToken } from '../api'

export function usePlaid(onSuccess) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const initAndOpen = useCallback(async () => {
    setLoading(true)
    setError(null)

    let token
    try {
      const data = await fetch('/api/auth/link-token', { method: 'POST' })
      const json = await data.json()
      token = json.link_token
      console.log('link token:', token)
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
        onExit: (err, metadata) => {
          if (err) {
            console.error('Plaid exit error:', err, metadata)
            setError('Bank connection failed')
          }
        },
        onEvent: (eventName) => {
          console.log('Plaid event:', eventName)
        },
      }).open()
    } catch (e) {
      console.error('Plaid.create error:', e)
      setError('Failed to open bank connection')
    }

    setLoading(false)
  }, [onSuccess])

  return { initAndOpen, loading, error }
}