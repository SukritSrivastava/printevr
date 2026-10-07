// Team tab API: the employee list and attendance. Staff routes like /api/production; changes
// to employees and attendance corrections also carry the admin token (X-Team-Admin), which
// stands in for role-based login. It lives in sessionStorage like the staff token, never in
// localStorage, and Sign out clears it.
import { json } from './invoices'

const ADMIN_KEY = 'printevr.team.admin'

export function adminToken(): string | null {
  try {
    return sessionStorage.getItem(ADMIN_KEY)
  } catch {
    return null
  }
}

export function setAdminToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(ADMIN_KEY, token)
    else sessionStorage.removeItem(ADMIN_KEY)
  } catch {
    /* private mode: the token lives only for this page */
  }
}

const asAdmin = (init: RequestInit = {}): RequestInit => {
  const token = adminToken()
  return token ? { ...init, headers: { ...(init.headers as Record<string, string>), 'X-Team-Admin': token } } : init
}

export type Role = 'admin' | 'sales' | 'designer' | 'production' | 'accounts' | 'staff'

export interface TeamSettings {
  roles: { value: Role; label: string }[]
  /** false: the server has no admin passcode, so nobody can change employees yet. */
  admin_configured: boolean
  /** Whether this browser's admin token is accepted. */
  is_admin: boolean
  timezone: string
}

export interface Employee {
  id: number
  name: string
  role: Role
  phone: string | null
  email: string | null
  /** YYYY-MM-DD */
  joined_on: string | null
  /** false once removed from the team; their attendance history stays. */
  active: boolean
}

export type EmployeeInput = Pick<Employee, 'name' | 'role' | 'phone' | 'email' | 'joined_on'>

export interface AttendanceRecord {
  work_date: string
  /** UTC ISO timestamps. */
  check_in: string
  check_out: string | null
  /** Minutes between check-in and check-out; null while still checked in. */
  minutes: number | null
  note: string | null
  /** An admin set or corrected these times. */
  edited_by_admin: boolean
}

export interface RegisterRow {
  employee: Employee
  record: AttendanceRecord | null
}

export interface DayRegister {
  date: string
  /** Today in IST, by the server's clock. */
  today: string
  rows: RegisterRow[]
  counts: { employees: number; present: number; checked_in_now: number }
}

export interface MonthRow {
  employee: Employee
  days_present: number
  minutes: number
  /** Past days checked in but never checked out. */
  open_days: number
  days: Record<string, AttendanceRecord>
}

export interface MonthSummary {
  month: string
  first: string
  last: string
  today: string
  rows: MonthRow[]
}

export interface RecordInput {
  /** HH:MM, 24-hour, IST */
  check_in: string
  check_out: string | null
  note: string | null
}

export const fetchTeamSettings = () => json<TeamSettings>('/api/team/settings', asAdmin())

export async function adminLogin(passcode: string): Promise<void> {
  const r = await json<{ token: string }>('/api/team/admin/login', { method: 'POST', body: JSON.stringify({ passcode }) })
  setAdminToken(r.token)
}

export const fetchEmployees = (includeRemoved = false) =>
  json<{ employees: Employee[] }>(`/api/team/employees${includeRemoved ? '?include_removed=true' : ''}`).then((r) => r.employees)

export const addEmployee = (input: EmployeeInput) =>
  json<Employee>('/api/team/employees', asAdmin({ method: 'POST', body: JSON.stringify(input) }))

export const updateEmployee = (id: number, input: Partial<EmployeeInput>) =>
  json<Employee>(`/api/team/employees/${id}`, asAdmin({ method: 'PATCH', body: JSON.stringify(input) }))

export const removeEmployee = (id: number) => json<Employee>(`/api/team/employees/${id}`, asAdmin({ method: 'DELETE' }))

export const restoreEmployee = (id: number) =>
  json<Employee>(`/api/team/employees/${id}/restore`, asAdmin({ method: 'POST' }))

export const fetchDay = (date: string | null) =>
  json<DayRegister>(`/api/team/attendance${date ? `?date=${encodeURIComponent(date)}` : ''}`)

export const fetchMonth = (month: string) => json<MonthSummary>(`/api/team/attendance/summary?month=${encodeURIComponent(month)}`)

export const checkIn = (employeeId: number) =>
  json<RegisterRow>('/api/team/attendance/check-in', { method: 'POST', body: JSON.stringify({ employee_id: employeeId }) })

export const checkOut = (employeeId: number) =>
  json<RegisterRow>('/api/team/attendance/check-out', { method: 'POST', body: JSON.stringify({ employee_id: employeeId }) })

export const setRecord = (employeeId: number, date: string, input: RecordInput) =>
  json<RegisterRow>(`/api/team/attendance/${employeeId}/${date}`, asAdmin({ method: 'PUT', body: JSON.stringify(input) }))

export const deleteRecord = (employeeId: number, date: string) =>
  json<{ status: string }>(`/api/team/attendance/${employeeId}/${date}`, asAdmin({ method: 'DELETE' }))

// ---------------------------------------------------------------- activity log (admin)

export interface LogEntry {
  id: number
  /** UTC ISO */
  at: string
  /** Who the request was signed in as: 'admin', 'staff', or 'site' (site password only). */
  actor_role: string
  /** Empty until role-based login names each person. */
  actor_name: string | null
  category: string
  summary: string
  method: string
  path: string
  status: number
  details: Record<string, unknown>
  ip: string | null
  user_agent: string | null
}

export interface LogPage {
  entries: LogEntry[]
  total: number
  limit: number
  offset: number
  categories: { value: string; label: string }[]
}

export interface LogFilter {
  from?: string
  to?: string
  category?: string
  q?: string
  limit?: number
  offset?: number
}

export function fetchLogs(filter: LogFilter): Promise<LogPage> {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(filter)) if (v !== undefined && v !== '') params.set(k, String(v))
  return json<LogPage>(`/api/team/logs?${params}`, asAdmin())
}
