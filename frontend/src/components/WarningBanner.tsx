import type { QuoteWarning } from '../api/types'

const TITLES: Record<string, string> = {
  PRICE_UNDER_REVIEW: 'Price under review',
  CUSTOM_ESTIMATE: 'Custom-size estimate',
  MOQ_APPLIED: 'Minimum order applied',
  PRODUCTION_TIME_UNKNOWN: 'Production time not stated',
}

export function WarningBanner({ warning }: { warning: QuoteWarning }) {
  return (
    <div role="status" className="flex gap-3 rounded-md bg-warn-wash px-3 py-2.5 text-sm text-warn">
      <svg aria-hidden="true" viewBox="0 0 20 20" className="mt-0.5 size-4 shrink-0 fill-current">
        <path d="M10 1.5 19 18H1L10 1.5Zm-1 6v5h2v-5H9Zm0 6.5v2h2v-2H9Z" />
      </svg>
      <p>
        <strong className="font-semibold">{TITLES[warning.code] ?? warning.code}.</strong> {warning.message}
      </p>
    </div>
  )
}
