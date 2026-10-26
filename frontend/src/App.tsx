import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './lib/auth'
import { homeFor } from './lib/routes'
import { RequireAuth, RequireRole } from './lib/guards'
import AppShell from './layouts/AppShell'
import Login from './pages/auth/Login'
import { NotFound, NotificationsPage, Profile, Unauthorized } from './pages/auth/Misc'
import { OfficerApplications, OfficerDashboard, OfficerNotices } from './pages/officer/Officer'
import ApplicationReview from './pages/officer/ApplicationReview'
import Audit from './pages/shared/Audit'
import { InstApplication, InstApplications, InstNotice, InstNotices, InstOverview, NewApplication } from './pages/institution/Institution'
import { AdminConfiguration, AdminUsers } from './pages/admin/Admin'

function Home() {
  const { user } = useAuth()
  return <Navigate to={homeFor(user?.role)} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="unauthorized" element={<Unauthorized />} />
          <Route path="profile" element={<Profile />} />
          <Route path="notifications" element={<NotificationsPage />} />

          <Route path="reviewer" element={<RequireRole role="reviewer" />}>
            <Route index element={<OfficerDashboard />} />
            <Route path="applications" element={<OfficerApplications />} />
            <Route path="applications/:applicationId" element={<ApplicationReview />} />
            <Route path="notices" element={<OfficerNotices />} />
            <Route path="audit" element={<Audit scope="reviewer" />} />
            <Route path="*" element={<NotFound />} />
          </Route>

          <Route path="institution" element={<RequireRole role="institution" />}>
            <Route index element={<InstOverview />} />
            <Route path="applications" element={<InstApplications />} />
            <Route path="applications/new" element={<NewApplication />} />
            <Route path="applications/:applicationId" element={<InstApplication />} />
            <Route path="notices" element={<InstNotices />} />
            <Route path="notices/:noticeId" element={<InstNotice />} />
            <Route path="*" element={<NotFound />} />
          </Route>

          <Route path="admin" element={<RequireRole role="admin" />}>
            <Route index element={<AdminUsers />} />
            <Route path="configuration" element={<AdminConfiguration />} />
            <Route path="audit" element={<Audit scope="admin" />} />
            <Route path="*" element={<NotFound />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  )
}
