import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthProvider'
import { Splash } from '../components/ui'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, initializing } = useAuth()
  const location = useLocation()

  if (initializing) return <Splash />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

export function RequirePermission({
  permission,
  children,
}: {
  permission: string
  children: ReactNode
}) {
  const { can } = useAuth()
  if (!can(permission)) {
    return (
      <div className="card mx-auto mt-10 max-w-md text-center">
        <div className="mb-2 text-2xl">🔒</div>
        <h2 className="mb-2 text-lg font-semibold">Недостаточно прав</h2>
        <p className="hint">
          Раздел доступен только администратору. Обратитесь к инженеру участка.
        </p>
      </div>
    )
  }
  return <>{children}</>
}
