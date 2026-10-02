// Add, rename, pause and resume designers. Paused designers are skipped by the rotation.
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { addDesigner, updateDesigner, type Designer } from '../../api/designers'
import { Dialog } from '../Dialog'
import { StaffCancelled, useStaff } from '../StaffLoginDialog'
import { describe, ROOT } from './live'

const NAME_MAX = 40

export function ManageDesigners({ designers, onClose }: { designers: Designer[]; onClose: () => void }) {
  const qc = useQueryClient()
  const withStaff = useStaff()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await withStaff(fn)
      await qc.invalidateQueries({ queryKey: [ROOT] })
      return true
    } catch (err) {
      if (!(err instanceof StaffCancelled)) setError(describe(err))
      return false
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title="Manage designers" onClose={onClose}>
      <p className="text-sm text-ink-soft">Jobs go to active designers in this order, one each in turn. Paused designers are skipped.</p>
      <ul className="mt-4 flex flex-col gap-2">
        {designers.map((d, i) => (
          <DesignerRow key={d.id} designer={d} position={i + 1} busy={busy} act={act} />
        ))}
      </ul>
      <form
        className="mt-4 flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!name.trim()) return setError('Enter a name')
          if (await act(() => addDesigner(name))) setName('')
        }}
      >
        <input
          className="field flex-1"
          aria-label="New designer's name"
          placeholder="New designer"
          maxLength={NAME_MAX}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" className="rounded-md bg-ink px-4 py-2 font-semibold text-stock disabled:opacity-50" disabled={busy}>
          Add
        </button>
      </form>
      {error && (
        <p role="alert" className="mt-3 text-sm text-stop">
          {error}
        </p>
      )}
      <div className="mt-5 flex justify-end">
        <button type="button" className="rounded-md px-4 py-2 font-semibold ring-1 ring-rule" onClick={onClose} data-close>
          Done
        </button>
      </div>
    </Dialog>
  )
}

function DesignerRow({
  designer,
  position,
  busy,
  act,
}: {
  designer: Designer
  position: number
  busy: boolean
  act: (fn: () => Promise<unknown>) => Promise<boolean>
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const rename = async () => {
    if (draft === null) return
    const value = draft.trim()
    if (value && value !== designer.name) await act(() => updateDesigner(designer.id, { name: value }))
    setDraft(null)
  }
  return (
    <li className="flex items-center gap-2">
      <span className="w-6 text-right text-sm text-ink-soft">{position}.</span>
      <input
        className={`field flex-1 ${designer.active ? '' : 'text-ink-soft'}`}
        aria-label={`Name of designer ${position}`}
        maxLength={NAME_MAX}
        value={draft ?? designer.name}
        onFocus={() => setDraft(designer.name)}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={rename}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            ;(e.target as HTMLInputElement).blur()
          }
        }}
      />
      <button
        type="button"
        className={`w-24 rounded-md px-3 py-2 text-sm font-semibold disabled:opacity-50 ${designer.active ? 'ring-1 ring-rule' : 'bg-cyan text-stock'}`}
        disabled={busy}
        aria-label={`${designer.active ? 'Pause' : 'Resume'} ${designer.name}`}
        onClick={() => act(() => updateDesigner(designer.id, { active: !designer.active }))}
      >
        {designer.active ? 'Pause' : 'Resume'}
      </button>
    </li>
  )
}
