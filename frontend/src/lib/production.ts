// Production tab: the production stages, in order.

export type Stage = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10

/** Same as STAGES in backend/app/production/models.py. */
export const STAGES: { value: Stage; label: string }[] = [
  { value: 1, label: 'Sampling' },
  { value: 2, label: 'Paper / Material' },
  { value: 3, label: 'Printing' },
  { value: 4, label: 'Lamination' },
  { value: 5, label: 'UV / Foiling / Special Finishing' },
  { value: 6, label: 'Cutting / Making / Pasting' },
  { value: 7, label: 'Quality Check' },
  { value: 8, label: 'Packaging' },
  { value: 9, label: 'Delivery / Dispatch' },
  { value: 10, label: 'Customer Feedback' },
]

export const stageLabel = (s: number) => STAGES.find((x) => x.value === s)?.label ?? `Stage ${s}`
