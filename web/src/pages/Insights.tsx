import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Funnel, type Stats } from "../lib/api";
import { money, pct } from "../lib/format";
import { STAGE_STYLE, useMeta } from "../lib/meta";
import { PageHeader } from "../components/Shell";
import { Empty, PageError, PageLoading, Segmented, cx } from "../components/ui";

const RANGES = [
  { value: "30", label: "30d" },
  { value: "90", label: "90d" },
  { value: "365", label: "1y" },
  { value: "0", label: "All" },
];

export function Insights() {
  const [days, setDays] = useState("90");
  const { data: s, isLoading, error, refetch } = useQuery({ queryKey: ["stats", days], queryFn: () => api.get<Stats>(`/stats?days=${days}`) });

  return (
    <>
      <PageHeader title="Insights" sub="Outbound funnel for everything you applied to in the window.">
        <Segmented value={days} onChange={setDays} options={RANGES} />
      </PageHeader>
      {error && !s ? (
        <PageError error={error} onRetry={refetch} />
      ) : isLoading || !s ? (
        <PageLoading />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Tile label="Applied" value={s.overall.applied} />
            <Tile label="Reply rate" value={pct(s.overall.reply_rate)} sub={`${s.overall.replied} replied`} />
            <Tile label="Calls" value={s.overall.calls} sub={s.overall.applied ? `${pct(s.overall.calls / s.overall.applied)} of applied` : undefined} />
            <Tile label="Won" value={s.overall.won} sub={s.overall.won_value ? money(s.overall.won_value) : pct(s.overall.win_rate) + " win rate"} />
            <Tile
              label="Days to reply"
              value={s.overall.median_days_to_reply ?? "—"}
              sub="median"
              className="col-span-2 lg:col-span-1"
            />
          </div>

          <Card title="Applications per week" sub="last 12 weeks · hover a bar for replies and wins">
            <WeeklyBars weeks={s.weekly} />
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="By channel" sub="where replies actually come from">
              <FunnelTable rows={s.by_channel} />
            </Card>
            <Card title="By network" sub="warm intros vs cold">
              <FunnelTable rows={s.by_network} />
            </Card>
            <Card title="Open pipeline" sub="right now">
              <OpenPipeline rows={s.open_by_stage} />
            </Card>
            {s.by_template.length > 0 && (
              <Card title="By first message" sub="which outreach variant gets replies">
                <FunnelTable rows={s.by_template} />
              </Card>
            )}
            <Card title="Message templates sent" sub="how often each template was used in the window, by platform">
              <TemplateUsage rows={s.template_usage} />
            </Card>
            {s.by_resume_version.length > 0 && (
              <Card title="By resume version" sub="job applications, by the base resume tailored from">
                <FunnelTable rows={s.by_resume_version} />
              </Card>
            )}
            <Card title="Jobs vs projects">
              <FunnelTable rows={s.by_kind} />
              {s.lost_reasons.length > 0 && (
                <div className="mt-4 border-t border-line pt-3 text-[13px]">
                  <div className="mb-1.5 text-xs font-medium text-muted">Why deals were lost</div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {s.lost_reasons.map((r) => (
                      <span key={r.key}>
                        {r.label} <span className="font-semibold tabular-nums">{r.count}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </>
  );
}

function Tile({ label, value, sub, className }: { label: string; value: string | number; sub?: string; className?: string }) {
  return (
    <div className={cx("rounded-2xl border border-line bg-panel px-4 py-3.5", className)}>
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  );
}

function Card({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-2xl border border-line bg-panel p-4">
      <div className="mb-3">
        <h2 className="font-semibold">{title}</h2>
        {sub && <div className="text-[13px] text-muted">{sub}</div>}
      </div>
      {children}
    </section>
  );
}

/** Single-series bars: one colour, no legend needed; per-bar hover tooltip carries the detail. */
function WeeklyBars({ weeks }: { weeks: Stats["weekly"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...weeks.map((w) => w.applied));
  const ticks = max <= 4 ? Array.from({ length: max + 1 }, (_, i) => i) : [0, Math.round(max / 2), max];
  if (weeks.every((w) => w.applied === 0 && w.replies === 0))
    return <Empty title="No applications in the last 12 weeks">Bars appear as you log applications.</Empty>;
  return (
    <div className="relative">
      <div className="flex h-44 gap-3">
        <div className="relative w-6 shrink-0 text-right text-[11px] text-muted tabular-nums">
          {ticks.map((t) => (
            <span key={t} className="absolute right-0 -translate-y-1/2" style={{ top: `${100 - (t / max) * 100}%` }}>
              {t}
            </span>
          ))}
        </div>
        <div className="relative flex flex-1 items-end gap-[2px] border-b border-line">
          {ticks.slice(1).map((t) => (
            <div key={t} className="pointer-events-none absolute inset-x-0 border-t border-dashed border-line/70" style={{ top: `${100 - (t / max) * 100}%` }} />
          ))}
          {weeks.map((w, i) => (
            <div
              key={w.week}
              className="group relative flex h-full flex-1 cursor-default items-end justify-center"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onClick={() => setHover(hover === i ? null : i)}
            >
              <div
                className={cx("w-full max-w-9 rounded-t-[4px] bg-accent transition-opacity", hover != null && hover !== i && "opacity-40")}
                style={{ height: `${(w.applied / max) * 100}%`, minHeight: w.applied ? 2 : 0 }}
              />
              {hover === i && (
                <div className="anim-pop absolute bottom-full z-10 mb-2 w-max rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-lg">
                  <div className="mb-1 font-semibold">Week of {new Date(w.week + "T00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" })}</div>
                  <div className="text-muted">
                    Applied <span className="font-semibold text-fg tabular-nums">{w.applied}</span>
                  </div>
                  <div className="text-muted">
                    Replies <span className="font-semibold text-fg tabular-nums">{w.replies}</span>
                  </div>
                  <div className="text-muted">
                    Won <span className="font-semibold text-fg tabular-nums">{w.won}</span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="mt-1.5 flex gap-[2px] pl-9 text-[11px] text-muted">
        {weeks.map((w, i) => (
          <span key={w.week} className="flex-1 text-center">
            {i % 2 === (weeks.length - 1) % 2 ? new Date(w.week + "T00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" }) : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function FunnelTable({ rows }: { rows: (Funnel & { key: string; label: string })[] }) {
  if (!rows.length) return <div className="py-6 text-center text-[13px] text-muted">No applications in this window yet.</div>;
  return (
    <table className="w-full text-[13px]">
      <thead className="text-xs text-muted">
        <tr>
          <th className="pb-2 text-left font-medium"></th>
          <th className="pb-2 text-right font-medium">Applied</th>
          <th className="pb-2 text-right font-medium">Reply</th>
          <th className="pb-2 text-right font-medium">Calls</th>
          <th className="pb-2 text-right font-medium">Won</th>
        </tr>
      </thead>
      <tbody className="tabular-nums">
        {rows.map((r) => (
          <tr key={r.key} className="border-t border-line/60">
            <td className="py-2 font-medium">
              {r.label}
              {r.inbound > 0 && <span className="ml-1.5 text-xs font-normal text-muted">+{r.inbound} inbound</span>}
            </td>
            <td className="py-2 text-right">{r.applied}</td>
            <td className="py-2 text-right">
              <RateBar v={r.reply_rate} />
            </td>
            <td className="py-2 text-right">{r.calls}</td>
            <td className="py-2 text-right">
              {r.won}
              {r.won_value > 0 && <span className="ml-1 text-xs text-muted">{money(r.won_value)}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RateBar({ v }: { v: number | null }) {
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span className="hidden h-1.5 w-12 overflow-hidden rounded-full bg-panel-2 sm:inline-block">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${(v ?? 0) * 100}%` }} />
      </span>
      <span className="w-9">{pct(v)}</span>
    </span>
  );
}

function OpenPipeline({ rows }: { rows: Stats["open_by_stage"] }) {
  const total = rows.reduce((s, r) => s + r.count, 0);
  if (!total) return <div className="py-6 text-center text-[13px] text-muted">No open opportunities.</div>;
  return (
    <div className="space-y-2.5">
      {rows
        .filter((r) => r.count > 0)
        .map((r) => (
          <div key={r.stage} className="flex items-center gap-3 text-[13px]">
            <span className="flex w-32 items-center gap-2">
              <span className={cx("h-2 w-2 rounded-full", STAGE_STYLE[r.stage]?.dot)} />
              {r.label}
            </span>
            <span className="h-2 flex-1 overflow-hidden rounded-full bg-panel-2">
              <span className="block h-full rounded-full bg-fg/25" style={{ width: `${(r.count / total) * 100}%` }} />
            </span>
            <span className="w-8 text-right font-semibold tabular-nums">{r.count}</span>
            <span className="w-14 text-right text-xs text-muted tabular-nums">{r.value ? money(r.value) : ""}</span>
          </div>
        ))}
    </div>
  );
}

/** Stacked bars: one row per template, a segment per platform. Colour follows the platform (fixed slot by its
 *  place in the channel list), so filtering never repaints one; the table view carries the exact numbers. */
function TemplateUsage({ rows }: { rows: Stats["template_usage"] }) {
  const { data: meta } = useMeta();
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hover, setHover] = useState<string | null>(null);
  if (!rows.length) return <div className="py-6 text-center text-[13px] text-muted">No templated messages logged in this window yet.</div>;
  const order = meta?.channels.map((c) => c.value) ?? [];
  const color = (ch: string) => `var(--series-${Math.min(order.indexOf(ch), 6) + 1})`;
  const present = order.filter((ch) => rows.some((r) => r.by_channel.some((b) => b.key === ch)));
  const label = (ch: string) => meta?.channels.find((c) => c.value === ch)?.label ?? ch;
  const max = Math.max(...rows.map((r) => r.uses));
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          {present.map((ch) => (
            <span key={ch} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color(ch) }} />
              {label(ch)}
            </span>
          ))}
        </div>
        <Segmented value={view} onChange={setView} options={[{ value: "chart", label: "Chart" }, { value: "table", label: "Table" }]} />
      </div>
      {view === "table" ? (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="text-xs text-muted">
              <tr>
                <th className="pb-2 text-left font-medium">Message</th>
                {present.map((ch) => (
                  <th key={ch} className="pb-2 text-right font-medium">
                    {label(ch)}
                  </th>
                ))}
                <th className="pb-2 text-right font-medium">Total</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((r) => (
                <tr key={r.key} className="border-t border-line/60">
                  <td className="py-2 font-medium">{r.label}</td>
                  {present.map((ch) => (
                    <td key={ch} className="py-2 text-right">
                      {r.by_channel.find((b) => b.key === ch)?.count ?? "—"}
                    </td>
                  ))}
                  <td className="py-2 text-right font-semibold">{r.uses}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => (
            <div key={r.key}>
              <div className="mb-1 text-[13px] font-medium [overflow-wrap:anywhere]">
                {r.label}
              </div>
              <div className="flex items-center gap-2">
                <div className="flex h-3 gap-[2px]" style={{ width: `calc((100% - 2.5rem) * ${r.uses / max})` }}>
                  {r.by_channel.map((b) => {
                    const id = `${r.key}:${b.key}`;
                    return (
                      <div
                        key={b.key}
                        className={cx("relative h-full first:rounded-l-[4px] last:rounded-r-[4px] transition-opacity", hover && hover !== id && "opacity-40")}
                        style={{ flex: b.count, background: color(b.key) }}
                        onMouseEnter={() => setHover(id)}
                        onMouseLeave={() => setHover(null)}
                        onClick={() => setHover(hover === id ? null : id)}
                      >
                        {hover === id && (
                          <div className="anim-pop absolute bottom-full left-1/2 z-10 mb-2 w-max -translate-x-1/2 rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-lg">
                            <div className="font-semibold">{b.label}</div>
                            <div className="text-muted">
                              Sent <span className="font-semibold text-fg tabular-nums">{b.count}</span> of {r.uses}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                <span className="w-8 shrink-0 text-[13px] font-semibold tabular-nums">{r.uses}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
