/** Save a PDF the API sent (BRD-cart-invoice FR-P5). iOS Safari may open it in a tab instead. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 'attachment; filename="Invoice_18_X_Paid.pdf"' -> 'Invoice_18_X_Paid.pdf' */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (star) {
    try {
      return decodeURIComponent(star[1].trim())
    } catch {
      /* fall through */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header)
  return plain ? plain[1].trim() : fallback
}
