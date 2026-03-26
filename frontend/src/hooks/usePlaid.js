import { useState, useCallback } from 'react'
import { usePlaidLink } from 'react-plaid-link'
import { getLinkToken, exchangeToken } from '../api'

export function usePlaid(onSuccess) {
  const [linkToken, setLinkToken] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const fetchLinkToken = useCallback(async () => {
    try {
      setLoading(true)
      const token = await getLinkToken()
      setLinkToken(token)
    } catch (e) {
      setError('Failed to initialize bank connection')
    } finally {
      setLoading(false)
    }
  }, [])

  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess: async (public_token, metadata) => {
      try {
        await exchangeToken(public_token, metadata.institution?.name || 'Unknown Bank')
        onSuccess?.()
      } catch (e) {
        setError('Failed to connect bank account')
      }
    },
  })

  return { fetchLinkToken, open, ready: ready && !!linkToken, loading, error }
}
