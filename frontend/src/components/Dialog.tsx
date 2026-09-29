import { useEffect, useId, useRef } from 'react'

interface Props {
  title: string
  onClose: () => void
  children: React.ReactNode
  wide?: boolean
}

/** A modal panel: labelled, closes on Escape, keeps focus inside, bottom sheet on phones. */
export function Dialog({ title, onClose, children, wide }: Props) {
  const id = useId()
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const first = panel.current?.querySelector<HTMLElement>('input, select, textarea, button:not([data-close])')
    first?.focus()
    return () => previous?.focus?.()
  }, [])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onClose()
    }
    if (e.key === 'Tab' && panel.current) {
      const focusable = [...panel.current.querySelectorAll<HTMLElement>('input, select, textarea, button, a[href]')].filter(
        (el) => !el.hasAttribute('disabled'),
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-ink/40 sm:items-center sm:p-6" onKeyDown={onKeyDown}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        className={`max-h-[92dvh] w-full overflow-y-auto rounded-t-xl bg-stock px-5 pt-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-xl sm:rounded-xl ${wide ? 'sm:max-w-2xl' : 'sm:max-w-md'}`}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 id={id} className="type-expanded text-lg font-bold">
            {title}
          </h2>
          <button type="button" data-close className="-m-2 p-2 text-ink-soft hover:text-ink" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
