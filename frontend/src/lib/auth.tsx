import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, setUnauthorizedHandler } from './api'

export type User = {
  id: number
  email: string
  full_name: string
  designation: string
  role: 'reviewer' | 'institution' | 'admin'
  institution_id: number | null
  institution_name: string | null
  last_login_at: string | null
}

type Ctx = { user: User | null; loading: boolean; sessionMinutes: number; refresh: () => void }
const AuthCtx = createContext<Ctx>({ user: null, loading: true, sessionMinutes: 0, refresh: () => {} })

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['me'],
    queryFn: () => api<{ user: User; session_minutes: number }>('/auth/me'),
    retry: false,
    staleTime: 60_000,
  })
  useEffect(() => {
    setUnauthorizedHandler(() => {
      qc.setQueryData(['me'], null)
    })
  }, [qc])
  const user = q.isError ? null : q.data?.user ?? null
  return (
    <AuthCtx.Provider value={{ user, loading: q.isLoading, sessionMinutes: q.data?.session_minutes ?? 0, refresh: () => q.refetch() }}>
      {children}
    </AuthCtx.Provider>
  )
}

export const useAuth = () => useContext(AuthCtx)
