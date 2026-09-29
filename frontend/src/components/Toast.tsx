import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

interface Toast {
  id: number
  message: string
  action?: { label: string; onClick: () => void }
}

const ToastContext = createContext<(message: string, action?: Toast['action']) => void>(() => {})

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const show = useCallback((message: string, action?: Toast['action']) => {
    setToast({ id: Date.now(), message, action })
  }, [])

  useEffect(() => {
    if (!toast) return
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setToast(null), 5000)
    return () => clearTimeout(timer.current)
  }, [toast])

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-24 z-50 flex justify-center px-4 lg:bottom-6" aria-live="polite" role="status">
        {toast && (
          <div key={toast.id} className="pointer-events-auto flex items-center gap-4 rounded-md bg-ink px-4 py-3 text-stock shadow-lg">
            <span>{toast.message}</span>
            {toast.action && (
              <button
                type="button"
                className="font-semibold text-cyan underline-offset-2 hover:underline"
                onClick={() => {
                  toast.action!.onClick()
                  setToast(null)
                }}
              >
                {toast.action.label}
              </button>
            )}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
