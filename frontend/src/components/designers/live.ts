// Shared state for the Designer Assignment tab: one query-key root, live refetching, and the
// optimistic cache edits a status or vendor change makes before the server answers.
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ApiError, NetworkError } from '../../api/client'
import { updateJob, type DesignerLoad, type Job, type JobChange } from '../../api/designers'
import { PENDING_STATUSES, REFRESH_MS, statusLabel } from '../../lib/designers'
import { StaffCancelled, useStaff } from '../StaffLoginDialog'
import { useToast } from '../Toast'

/** Every Designer Assignment query starts with this, so one invalidate refreshes them all. */
export const ROOT = 'design'

/** Stop polling after a sign-in problem; a Retry (or the user's next action) starts again. */
const stopsPolling = (err: unknown) =>
  err instanceof StaffCancelled || (err instanceof ApiError && ['AUTH_REQUIRED', 'STORAGE_DISABLED', 'DESIGNERS_NOT_SET_UP'].includes(err.code))

/**
 * A query that stays fresh while the tab is open and visible: every REFRESH_MS, never while
 * the browser tab is hidden, and at once when the window regains focus.
 */
export function useLive<T>(key: QueryKey, fn: () => Promise<T>, keepPrevious = false) {
  const withStaff = useStaff()
  return useQuery({
    queryKey: [ROOT, ...key],
    queryFn: () => withStaff(fn),
    placeholderData: keepPrevious ? keepPreviousData : undefined,
    refetchInterval: (query) => (stopsPolling(query.state.error) ? false : REFRESH_MS),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: 'always',
    retry: (count, err) => !stopsPolling(err) && !(err instanceof ApiError) && count < 2,
    staleTime: 0,
  })
}

export function describe(err: unknown): string {
  if (err instanceof StaffCancelled) return 'Enter the staff passcode to see the jobs.'
  if (err instanceof NetworkError) return "Can't reach the server."
  if (err instanceof ApiError && err.code === 'DESIGNERS_NOT_SET_UP')
    return "The designer tables aren't in the database yet. Run the migrations (see README), then retry."
  if (err instanceof ApiError && err.code === 'STORAGE_DISABLED') return "This server doesn't store jobs (no database)."
  return err instanceof Error ? err.message : String(err)
}

function patchJob(job: Job, change: JobChange): Job {
  const next = { ...job }
  if (change.status !== undefined) {
    next.status = change.status
    next.status_label = statusLabel(change.status)
    next.pending = PENDING_STATUSES.includes(change.status)
  }
  if (change.vendor_name !== undefined) next.vendor_name = change.vendor_name?.trim() || null
  return next
}

type JobsData = { jobs: Job[]; total: number }
type LoadData = { designers: DesignerLoad[]; unassigned_pending: number }

/** Saves a job change at once; the screen shows it first and puts it back if the save fails. */
export function useJobUpdate() {
  const qc = useQueryClient()
  const withStaff = useStaff()
  const toast = useToast()
  return useMutation({
    mutationFn: ({ id, change }: { id: number; change: JobChange }) => withStaff(() => updateJob(id, change)),
    onMutate: async ({ id, change }) => {
      await qc.cancelQueries({ queryKey: [ROOT] })
      const before = qc.getQueriesData({ queryKey: [ROOT] })
      qc.setQueriesData<JobsData>({ queryKey: [ROOT, 'jobs'] }, (d) =>
        d ? { ...d, jobs: d.jobs.map((j) => (j.id === id ? patchJob(j, change) : j)) } : d,
      )
      qc.setQueriesData<LoadData>({ queryKey: [ROOT, 'workload'] }, (d) =>
        d
          ? { ...d, designers: d.designers.map((x) => ({ ...x, jobs: x.jobs.map((j) => (j.id === id ? patchJob(j, change) : j)) })) }
          : d,
      )
      return { before }
    },
    onError: (err, _vars, ctx) => {
      ctx?.before.forEach(([key, data]) => qc.setQueryData(key, data))
      if (!(err instanceof StaffCancelled)) toast(`Not saved: ${describe(err)}`)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: [ROOT] }),
  })
}

/** The current time, ticking every 30 s, for "5 minutes ago" labels. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])
  return now
}
