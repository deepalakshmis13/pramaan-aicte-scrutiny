export const fmtDate = (s?: string | null) =>
  s ? new Date(s.length === 10 ? s + 'T00:00:00' : s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'

export const fmtDateTime = (s?: string | null) =>
  s ? new Date(s).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'

export const fmtBytes = (n?: number) => (n == null ? '—' : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`)

export function relative(s?: string | null) {
  if (!s) return '—'
  const diff = (Date.now() - new Date(s).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`
  return fmtDate(s)
}

export const plural = (n: number, one: string, many?: string) => `${n} ${n === 1 ? one : many ?? one + 's'}`

export const fieldLabel = (f: string) =>
  ({
    institution_name: 'Institution name', permanent_id: 'Permanent ID', certificate_number: 'Certificate no.', issuing_authority: 'Issuing authority',
    issue_date: 'Issue date', expiry_date: 'Valid until', holder_name: 'Holder name', degree: 'Degree', awarding_body: 'Awarding body',
    approved_intake: 'Approved intake', academic_year: 'Academic year', transaction_id: 'Transaction ID', amount: 'Amount',
    room_label: 'Room label', room_label_use: 'Room use (caption)', faculty_name: 'Faculty name', faculty_qualification: 'Qualification',
    faculty_designation: 'Designation', faculty_id: 'Faculty ID', programme_name: 'Programme', programme_intake: 'Programme intake',
    floor_room: 'Room', floor_room_use: 'Room use', floor_room_area_sqm: 'Area (sq.m)', pub_title: 'Title', pub_authors: 'Authors',
    pub_venue: 'Venue', pub_year: 'Year', pub_doi: 'DOI', pub_indexing: 'Claimed indexing', accreditation_body: 'Accrediting body',
    programme_accredited: 'Programme',
  })[f] ?? f.replace(/_/g, ' ')
