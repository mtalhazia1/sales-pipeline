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
  /** Agent state: fixed sections (in every run_start brief, capped); any other section is a list. */
  state_sections: (Option & { cap: number })[];
  run_statuses: Option[];
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
  template_id: number | null;
  resume_url: string | null;
  cover_letter_url: string | null;
  resume_version: string | null;
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
  /** my_message only: the platform it went out on, and the template it used. */
  channel: string | null;
  template: TemplateRef | null;
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
  template: TemplateRef | null;
  updated_at: string;
  applied_at: string | null;
  replied_at: string | null;
  call_at: string | null;
  proposal_at: string | null;
  closed_at: string | null;
  reminders: Reminder[];
  events: TimelineEvent[];
};

export type TemplateRef = { id: number; category: string; name: string };

/** A kind of recurring message (LinkedIn first contact, cold email, …); `purpose` tells agents when to send it. */
export type MessageCategory = {
  key: string;
  name: string;
  purpose: string | null;
  has_subject: boolean;
  needs_review: boolean;
  updated_by: string | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
};

/** The owner's recommended example; agents adapt the category's current one to each person. */
export type MessageTemplate = TemplateRef & {
  subject: string | null;
  body: string;
  placeholders: string[];
  is_current: boolean;
  archived: boolean;
  needs_review: boolean;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
};

/** GET /templates adds usage (all time): every send per platform, and how deals did with it as their first message. */
export type TemplateWithUsage = MessageTemplate & {
  usage: {
    uses: number;
    by_channel: Record<string, number>;
    last_used_at: string | null;
    sent: number;
    replied: number;
    calls: number;
    won: number;
    reply_rate: number | null;
  };
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
  messages_need_review: number;
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
  by_template: (Funnel & { key: string; label: string })[];
  by_resume_version: (Funnel & { key: string; label: string })[];
  template_usage: { key: string; label: string; category: string | null; uses: number; by_channel: { key: string; label: string; count: number }[] }[];
  lost_reasons: { key: string; label: string; count: number }[];
  open_by_stage: { stage: string; label: string; count: number; value: number }[];
  weekly: { week: string; applied: number; replies: number; won: number }[];
};

export type Agents = {
  mcp_url: string;
  api_keys: { id: number; name: string; prefix: string; created_at: string; last_used_at: string | null }[];
  apps: { client_id: string; name: string; connected_at: string; last_used_at: string | null }[];
};

/** Agent state: one remembered value. `locked` = an owner row: agents can't change it (in a list they may only merge fields). */
export type StateRow = {
  ns: string;
  section: string;
  key: string;
  value: unknown;
  by: string;
  updated_at: string;
  locked?: boolean;
  /** List rows worked on a schedule. */
  due_at?: string;
  expires_at?: string;
};

/** GET /state: rows (filtered) plus what the filters offer, and counters in their current windows {ns: {key: {period: n}}}. */
export type StateView = {
  rows: StateRow[];
  /** True when rows were cut at the page limit (2,000): narrow the filters. */
  more: boolean;
  namespaces: string[];
  sections: string[];
  counters: Record<string, Record<string, Record<string, number>>>;
};

export type StateChangeResult = {
  applied?: { section: string; key: string; ns?: string; value?: unknown }[];
  rejected?: { section?: string; key?: string; ns?: string; reason: string }[];
};

/** One scheduled agent run; status is "running" while it holds its lease. */
export type AgentRun = {
  id: number;
  ns: string;
  worker: string;
  started_at: string;
  ended_at: string | null;
  lease_until: string;
  status: string;
  summary: string | null;
  counts: Record<string, number>;
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
