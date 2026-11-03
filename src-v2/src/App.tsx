import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { useAuth } from './auth/AuthProvider'
import { RequireAuth, RequirePermission } from './auth/guards'
import { AuditPage } from './pages/AuditPage'
import { EmployeesPage } from './pages/EmployeesPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { MapPage } from './pages/MapPage'
import { MfaPage } from './pages/MfaPage'
import { ProfilePage } from './pages/ProfilePage'
import { RegisterPage } from './pages/RegisterPage'
import { RegistryPage } from './pages/RegistryPage'
import { TypesPage } from './pages/TypesPage'

export default function App() {
  const { user } = useAuth()

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route path="/mfa" element={<MfaPage />} />
      <Route path="/register" element={user ? <Navigate to="/" replace /> : <RegisterPage />} />

      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<MapPage />} />
        <Route path="/registry" element={<RegistryPage />} />
        <Route path="/status" element={<HomePage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route
          path="/types"
          element={
            <RequirePermission permission="settings.edit">
              <TypesPage />
            </RequirePermission>
          }
        />
        <Route
          path="/employees"
          element={
            <RequirePermission permission="employee.manage">
              <EmployeesPage />
            </RequirePermission>
          }
        />
        <Route
          path="/audit"
          element={
            <RequirePermission permission="audit.view">
              <AuditPage />
            </RequirePermission>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
