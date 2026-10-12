// Types mirror server/app/service.py serializers exactly.

export type Option = { value: string; label: string };

export type Meta = {
  kinds: Option[];
  channels: Option[];
  networks: Option[];
  stages: Option[];
  open_stages: string[];
  lost_reasons: Option[];
  activity_kinds: Option[];
  channel_by_host: Record<string, string>;
  timezone: string;
  timezone_set: boolean;
  base_url: string;
};

export type ReminderRef = { id: number; due_at: string; note: string };

export type Summary = {
  id: number;
  deleted: boolean;
  kind: string;
  company: string;
  title: string | null;
  channel: string;
  network: string;
  stage: string;
  inbound: boolean;
  waiting_on: "me" | "client" | null;
  lost_reason: string | null;
  application_url: string | null;
  value: number | null;
  budget: string | null;
  fit: number | null;
  needs_review: boolean;
  created_by: string;
  created_at: string;
  last_activity_at: string;
  next_reminder: ReminderRef | null;
};

export type Reminder = {
  id: number;
  opportunity_id: number;
  due_at: string;
  note: string;
  done_at: string | null;
  created_by: string;
};

export type TimelineEvent = {
  id: number;
  opportunity_id: number;
  kind: string;
  body: string | null;
  changes: Record<string, [unknown, unknown]> | null;
  actor_type: "human" | "agent";
  actor_name: string;
  occurred_at: string;
  company?: string;
  title?: string | null;
};

export type Detail = Summary & {
  company_url: string | null;
  contact_name: string | null;
  contact_email: string | null;
  contact_url: string | null;
  description: string | null;
  notes: string | null;
  updated_at: string;
  applied_at: string | null;
  replied_at: string | null;
  call_at: string | null;
  proposal_at: string | null;
  closed_at: string | null;
  reminders: Reminder[];
  events: TimelineEvent[];
};

export type AgendaReminder = Reminder & { overdue: boolean; opportunity: Summary };

export type Agenda = {
  today: string;
  timezone: string;
  due_reminders: AgendaReminder[];
  your_move: Summary[];
  gone_quiet: (Summary & { idle_days: number })[];
  new_leads: Summary[];
  new_leads_total: number;
  upcoming: AgendaReminder[];
  needs_review: number;
  unread_notifications: number;
};

/** An alert an agent sent the owner (MCP notify_owner). */
export type AppNotification = {
  id: number;
  title: string;
  message: string | null;
  url: string | null;
  opportunity: { id: number; company: string; title: string | null } | null;
  created_by: string;
  created_at: string;
  read_at: string | null;
};

export type Funnel = {
  applied: number;
  replied: number;
  calls: number;
  proposals: number;
  won: number;
  won_value: number;
  reply_rate: number | null;
  win_rate: number | null;
  median_days_to_reply: number | null;
  inbound: number;
};

export type Stats = {
  days: number | null;
  overall: Funnel;
  by_channel: (Funnel & { key: string; label: string })[];
  by_network: (Funnel & { key: string; label: string })[];
  by_kind: (Funnel & { key: string; label: string })[];
  lost_reasons: { key: string; label: string; count: number }[];
  open_by_stage: { stage: string; label: string; count: number; value: number }[];
  weekly: { week: string; applied: number; replies: number; won: number }[];
};

export type Agents = {
  mcp_url: string;
  api_keys: { id: number; name: string; prefix: string; created_at: string; last_used_at: string | null }[];
  apps: { client_id: string; name: string; connected_at: string; last_used_at: string | null }[];
};

export type User = { id: number; email: string; name: string };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401 && !path.startsWith("/auth/")) {
    const next = encodeURIComponent(location.pathname + location.search);
    location.assign(`/login?next=${next}`);
  }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : res.statusText;
    throw new ApiError(res.status, msg || "Something went wrong");
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};
