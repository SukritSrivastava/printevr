// The production employee list, and adding to it. New names are assignable at once.
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { addEmployee, type Employee } from '../../api/production'
import { Dialog } from '../Dialog'
import { StaffCancelled, useStaff } from '../StaffLoginDialog'
import { describe, ROOT } from './ProductionPage'

const NAME_MAX = 40

export function ManageEmployees({ employees, onClose }: { employees: Employee[]; onClose: () => void }) {
  const qc = useQueryClient()
  const withStaff = useStaff()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const value = name.trim().replace(/\s+/g, ' ')
    if (!value) return setError('Enter a name')
    const taken = employees.find((x) => x.name.toLowerCase() === value.toLowerCase())
    if (taken) return setError(`${taken.name} is already on the list`)
    setBusy(true)
    setError(null)
    try {
      const added = await withStaff(() => addEmployee(value))
      qc.setQueryData<Employee[]>([ROOT, 'employees'], (list) => (list ? [...list, added] : [added]))
      setName('')
      await qc.invalidateQueries({ queryKey: [ROOT, 'employees'] })
    } catch (err) {
      if (!(err instanceof StaffCancelled)) setError(describe(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title="Production employees" onClose={onClose}>
      <p className="text-sm text-ink-soft">Everyone here can be assigned to a production job.</p>
      {employees.length === 0 ? (
        <p className="mt-4 text-ink-soft">No employees yet. Add the first one below.</p>
      ) : (
        <ul className="mt-4 flex flex-col gap-2">
          {employees.map((e, i) => (
            <li key={e.id} className="flex items-center gap-2 rounded-md bg-sheet px-3 py-2">
              <span className="w-6 text-right text-sm text-ink-soft">{i + 1}.</span>
              <span className="font-semibold">{e.name}</span>
            </li>
          ))}
        </ul>
      )}
      <form className="mt-4 flex gap-2" onSubmit={submit}>
        <input
          className="field flex-1"
          aria-label="New employee's name"
          placeholder="New employee"
          maxLength={NAME_MAX}
          value={name}
          onChange={(e) => {
            setName(e.target.value)
            setError(null)
          }}
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
