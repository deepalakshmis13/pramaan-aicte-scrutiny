// Single source of truth for in-app paths.
export const R = {
  login: '/login',
  unauthorized: '/unauthorized',
  profile: '/profile',
  notifications: '/notifications',
  reviewer: {
    home: '/reviewer',
    apps: (q?: string) => `/reviewer/applications${q ? `?${q}` : ''}`,
    app: (id: number, section?: string) => `/reviewer/applications/${id}${section ? `#${section}` : ''}`,
    notices: '/reviewer/notices',
    audit: '/reviewer/audit',
  },
  institution: {
    home: '/institution',
    apps: '/institution/applications',
    newApp: '/institution/applications/new',
    app: (id: number) => `/institution/applications/${id}`,
    notices: '/institution/notices',
    notice: (id: number) => `/institution/notices/${id}`,
  },
  admin: {
    home: '/admin',
    config: '/admin/configuration',
    audit: '/admin/audit',
  },
}

export function homeFor(role?: string) {
  if (role === 'reviewer') return R.reviewer.home
  if (role === 'institution') return R.institution.home
  if (role === 'admin') return R.admin.home
  return R.login
}

/** Only allow in-app relative links coming from the server (notifications). */
export function safeInternal(path?: string | null) {
  return path && path.startsWith('/') && !path.startsWith('//') ? path : null
}
