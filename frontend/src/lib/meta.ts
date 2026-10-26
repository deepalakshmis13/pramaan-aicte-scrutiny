import { useQuery } from '@tanstack/react-query'
import { api } from './api'

export type Meta = {
  application_statuses: Record<string, string>
  result_states: Record<string, string>
  finding_categories: Record<string, string>
  document_types: Record<string, string>
  notice_statuses: Record<string, string>
  decision_outcomes: Record<string, string>
  categories: { id: number; code: string; name: string }[]
}

export function useMeta() {
  return useQuery({ queryKey: ['meta'], queryFn: () => api<Meta>('/meta'), staleTime: Infinity })
}
