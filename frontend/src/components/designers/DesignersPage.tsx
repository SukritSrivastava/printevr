// Designer Assignment tab: who gets the next job, the jobs board and each designer's workload.
// Everything comes from the database through the API and refreshes while the tab is visible.
import { useState } from 'react'
import { fetchDesigners, fetchNextDesigner, fetchVendors } from '../../api/designers'
import { JobsBoard } from './JobsBoard'
import { VENDOR_LIST_ID } from './JobControls'
import { describe, useLive } from './live'
import { ManageDesigners } from './ManageDesigners'
import { Workload } from './Workload'

type Tab = 'jobs' | 'workload'

export function DesignersPage() {
  const [tab, setTab] = useState<Tab>('jobs')
  const [managing, setManaging] = useState(false)
  const designers = useLive(['designers'], fetchDesigners)
  const next = useLive(['next'], fetchNextDesigner)
  const vendors = useLive(['vendors'], fetchVendors)

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="type-expanded text-2xl font-bold">Designer Assignment</h1>
          <p className="mt-1" data-testid="next-designer">
            Next job goes to:{' '}
            <strong className="text-cyan-deep">
              {next.isPending ? '…' : next.data ? next.data.name : 'nobody (every designer is paused)'}
            </strong>
          </p>
        </div>
        <button
          type="button"
          className="rounded-md border-[1.5px] border-ink px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
          disabled={!designers.data}
          onClick={() => setManaging(true)}
        >
          Manage designers
        </button>
      </div>

      <div role="tablist" aria-label="View" className="flex gap-2">
        {(
          [
            ['jobs', 'Jobs board'],
            ['workload', 'Designer workload'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`rounded-md px-3 py-1.5 text-sm font-semibold ${tab === key ? 'bg-ink text-stock' : 'ring-1 ring-rule'}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {designers.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-stop">
          <span>{describe(designers.error)}</span>
          <button type="button" className="rounded-md bg-ink px-3 py-1 text-sm font-semibold text-stock" onClick={() => designers.refetch()}>
            Retry
          </button>
        </div>
      ) : tab === 'jobs' ? (
        <JobsBoard designers={designers.data ?? []} />
      ) : (
        <Workload />
      )}

      <datalist id={VENDOR_LIST_ID}>
        {(vendors.data ?? []).map((v) => (
          <option key={v} value={v} />
        ))}
      </datalist>

      {managing && designers.data && <ManageDesigners designers={designers.data} onClose={() => setManaging(false)} />}
    </main>
  )
}
