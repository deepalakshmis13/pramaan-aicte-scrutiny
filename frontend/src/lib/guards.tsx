import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './auth'
import { R } from './routes'
import { LoadingBlock } from '../components/ui/basics'

export function RequireAuth() {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading)
    return (
      <div className="mx-auto max-w-lg p-10">
        <LoadingBlock rows={3} />
      </div>
    )
  if (!user) return <Navigate to={R.login} replace state={{ from: loc.pathname + loc.search }} />
  return <Outlet />
}

export function RequireRole({ role }: { role: 'reviewer' | 'institution' | 'admin' }) {
  const { user } = useAuth()
  if (!user || user.role !== role) return <Navigate to={R.unauthorized} replace />
  return <Outlet />
}
