const DAY = 86_400_000;

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/** "3m ago", "2h ago", "yesterday", "5d ago", "12 Sep" */
export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < DAY) return `${Math.floor(diff / 3_600_000)}h ago`;
  const days = Math.round((startOfDay(new Date()) - startOfDay(new Date(t))) / DAY);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return shortDate(iso);
}

export function shortDate(iso: string): string {
  const d = new Date(iso);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
}

/** Due-date label: "Overdue · 2d", "Today 09:00", "Tomorrow", "Fri 9 Oct" */
export function due(iso: string): { text: string; tone: "overdue" | "today" | "soon" | "later" } {
  const d = new Date(iso);
  const days = Math.round((startOfDay(d) - startOfDay(new Date())) / DAY);
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const showTime = !(d.getHours() === 9 && d.getMinutes() === 0);
  if (d.getTime() < Date.now() && days < 0) return { text: `Overdue · ${-days}d`, tone: "overdue" };
  if (days <= 0) return { text: `Today${showTime ? " " + time : ""}`, tone: d.getTime() < Date.now() ? "overdue" : "today" };
  if (days === 1) return { text: `Tomorrow${showTime ? " " + time : ""}`, tone: "soon" };
  const label = d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  return { text: `${label}${showTime ? " " + time : ""}`, tone: days < 7 ? "soon" : "later" };
}

export function money(v: number | null | undefined): string {
  if (v == null) return "";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (v >= 10_000) return `$${Math.round(v / 1000)}k`;
  if (v >= 1000) return `$${(v / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `$${Math.round(v)}`;
}

export function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

/** Local date (YYYY-MM-DD) n days from today, for quick reminder buttons. */
export function inDays(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return toLocalDate(d);
}

export function toLocalDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** "+1d" on a reminder: an overdue one moves to tomorrow (09:00), a future one a day later — never earlier. */
export function snoozed(dueIso: string): string {
  const t = new Date(dueIso).getTime();
  return t <= Date.now() ? inDays(1) : new Date(t + DAY).toISOString();
}

/** "8000", "$8,000", "8k", "1.5M", "8000 USD" → 8000; null when it isn't a number. */
export function parseMoney(text: string): number | null {
  const m = text.replace(/[$,\s]|usd/gi, "").match(/^(\d+(?:\.\d+)?)([km]?)$/i);
  if (!m) return null;
  const unit: Record<string, number> = { "": 1, k: 1e3, m: 1e6 };
  return Number(m[1]) * unit[m[2].toLowerCase()];
}

/** Next Monday (or the Monday after if today is Monday). */
export function nextMonday(): string {
  const d = new Date();
  d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7));
  return toLocalDate(d);
}

export function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url.includes("://") ? url : `https://${url}`).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** A clickable web link — anything that isn't http(s) is treated as a host name, never as another scheme. */
export function href(url: string): string {
  return /^https?:\/\//i.test(url) ? url : `https://${url.replace(/^[a-z][a-z0-9+.-]*:(?!\d)\/*/i, "")}`;
}
