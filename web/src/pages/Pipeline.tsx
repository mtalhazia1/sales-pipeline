import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { ArrowDown, ArrowUp, Bell, Columns3, Inbox, List, Search } from "lucide-react";
import type { Summary } from "../lib/api";
import { ago, due, money } from "../lib/format";
import { STAGE_STYLE, labelOf, useMeta } from "../lib/meta";
import { useDrawer, useOppActions, useOpportunities } from "../lib/hooks";
import { PageHeader } from "../components/Shell";
import { DUE_TONE, OppRow } from "../components/OppRow";
import { Button, Chip, Empty, Fit, Modal, PageError, PageLoading, Segmented, Select, StagePill, YourMove, cx, pressable, useToast } from "../components/ui";

export function Pipeline() {
  const { data: meta } = useMeta();
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as "board" | "list") || (matchMedia("(max-width: 767px)").matches ? "list" : "board");
  const showClosed = params.get("closed") === "1";
  const filters = {
    q: params.get("q") ?? "",
    channel: params.get("channel") ?? "",
    network: params.get("network") ?? "",
    kind: params.get("kind") ?? "",
    stage: params.get("stage") ?? "",
  };
  // Filters replace the history entry — Back leaves the page instead of undoing keystrokes.
  const setParam = (k: string, v: string) =>
    setParams(
      (p) => {
        if (v) p.set(k, v);
        else p.delete(k);
        return p;
      },
      { replace: true },
    );
  // The text filter applies after a short pause, not on every keystroke.
  const [q, setQ] = useState(filters.q);
  useEffect(() => {
    if (q === filters.q) return;
    const t = setTimeout(() => setParam("q", q), 250);
    return () => clearTimeout(t);
  });
  const { data: opps, isLoading, error, refetch } = useOpportunities({
    q: filters.q || undefined,
    channel: filters.channel || undefined,
    network: filters.network || undefined,
    kind: filters.kind || undefined,
    stage: filters.stage || undefined,
    include_closed: showClosed || filters.stage ? "true" : "false",
  });

  const openValue = (opps ?? []).filter((o) => meta?.open_stages.includes(o.stage)).reduce((s, o) => s + (o.value ?? 0), 0);
  const openCount = (opps ?? []).filter((o) => meta?.open_stages.includes(o.stage)).length;

  return (
    <>
      <PageHeader
        title="Pipeline"
        sub={
          <>
            {openCount} open{openValue > 0 && <> · {money(openValue)} in play</>}
          </>
        }
      >
        <Segmented
          value={view}
          onChange={(v) => setParam("view", v)}
          options={[
            { value: "board", label: <><Columns3 size={14} /> Board</> },
            { value: "list", label: <><List size={14} /> List</> },
          ]}
        />
      </PageHeader>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1 sm:max-w-xs">
          <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter…" className="field h-9 pl-9" />
        </div>
        <Select className="h-9 w-auto py-0" value={filters.channel} onChange={(v) => setParam("channel", v)} options={meta?.channels ?? []} placeholder="All channels" />
        <Select className="h-9 w-auto py-0" value={filters.network} onChange={(v) => setParam("network", v)} options={meta?.networks ?? []} placeholder="Any network" />
        <Select className="h-9 w-auto py-0" value={filters.kind} onChange={(v) => setParam("kind", v)} options={meta?.kinds ?? []} placeholder="Jobs & projects" />
        <Select className="h-9 w-auto py-0" value={filters.stage} onChange={(v) => setParam("stage", v)} options={meta?.stages ?? []} placeholder="Any stage" />
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-[13px] text-muted">
          <input type="checkbox" checked={showClosed} onChange={(e) => setParam("closed", e.target.checked ? "1" : "")} className="accent-[var(--accent)]" />
          Show won & lost
        </label>
      </div>

      {error && !opps ? (
        <PageError error={error} onRetry={refetch} />
      ) : isLoading || !opps ? (
        <PageLoading />
      ) : view === "board" ? (
        <Board opps={opps} showClosed={showClosed} />
      ) : opps.length ? (
        <ListView opps={opps} />
      ) : (
        <Empty title="Nothing here yet">Press N to add an opportunity, or connect an agent in Settings to fill this for you.</Empty>
      )}
    </>
  );
}

// ---------------------------------------------------------------- board (drag to change stage)

function Board({ opps, showClosed }: { opps: Summary[]; showClosed: boolean }) {
  const { data: meta } = useMeta();
  const act = useOppActions();
  const toast = useToast();
  const [dragging, setDragging] = useState<number | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [lostFor, setLostFor] = useState<number | null>(null);

  const columns = (meta?.stages ?? []).filter((s) => {
    if (s.value === "matcher") return opps.some((o) => o.channel === "toptal");
    if (s.value === "won" || s.value === "lost") return showClosed;
    return true;
  });

  const drop = (stage: string) => {
    const opp = opps.find((o) => o.id === dragging);
    setOver(null);
    setDragging(null);
    if (!opp || opp.stage === stage) return;
    if (stage === "matcher" && opp.channel !== "toptal") return toast.error("Sent to matcher is only for Toptal deals");
    if (stage === "lost") setLostFor(opp.id);
    else act.update.mutate({ id: opp.id, stage });
  };

  return (
    <>
      <div className="scroll-thin -mx-4 flex gap-3 overflow-x-auto px-4 pb-4 md:-mx-8 md:px-8">
        {columns.map((col) => {
          const items = opps.filter((o) => o.stage === col.value);
          const value = items.reduce((s, o) => s + (o.value ?? 0), 0);
          return (
            <div
              key={col.value}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(col.value);
              }}
              onDragLeave={() => setOver((o) => (o === col.value ? null : o))}
              onDrop={(e) => {
                e.preventDefault(); // a link dragged in from another tab must not navigate away
                drop(col.value);
              }}
              className={cx(
                "flex w-72 shrink-0 flex-col rounded-2xl border border-transparent bg-panel-2/50 p-2 transition",
                over === col.value && "border-accent bg-accent/5",
              )}
            >
              <div className="flex items-center gap-2 px-2 pt-1 pb-2.5">
                <span className={cx("h-2 w-2 rounded-full", STAGE_STYLE[col.value]?.dot)} />
                <span className="text-[13px] font-semibold">{col.label}</span>
                <span className="text-[13px] text-muted">{items.length}</span>
                {value > 0 && <span className="ml-auto text-xs text-muted">{money(value)}</span>}
              </div>
              <div className="flex min-h-24 flex-col gap-2">
                {items.map((o) => (
                  <Card key={o.id} opp={o} onDrag={setDragging} dragging={dragging === o.id} channelLabel={labelOf(meta?.channels, o.channel)} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <Modal open={lostFor != null} onClose={() => setLostFor(null)} title="Why was it lost?" width="max-w-sm">
        <div className="grid gap-1.5 p-4">
          {meta?.lost_reasons.map((r) => (
            <Button
              key={r.value}
              className="justify-start"
              onClick={() => {
                act.update.mutate({ id: lostFor!, stage: "lost", lost_reason: r.value });
                setLostFor(null);
              }}
            >
              {r.label}
            </Button>
          ))}
        </div>
      </Modal>
    </>
  );
}

function Card({ opp, onDrag, dragging, channelLabel }: { opp: Summary; onDrag: (id: number | null) => void; dragging: boolean; channelLabel: string }) {
  const drawer = useDrawer();
  const rem = opp.next_reminder ? due(opp.next_reminder.due_at) : null;
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        onDrag(opp.id);
      }}
      onDragEnd={() => onDrag(null)}
      {...pressable(() => drawer.open(opp.id))}
      className={cx(
        "cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-xl border border-line bg-panel p-3 shadow-xs transition hover:border-muted/40 hover:shadow-sm",
        dragging && "opacity-40",
      )}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{opp.company}</div>
          {opp.title && <div className="mt-0.5 line-clamp-2 text-[13px] text-muted">{opp.title}</div>}
        </div>
        {opp.needs_review && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent" title="Agent change — needs review" />}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <Chip>{channelLabel}</Chip>
        {opp.inbound && (
          <Chip>
            <Inbox size={11} />
          </Chip>
        )}
        {opp.waiting_on === "me" && opp.stage !== "won" && opp.stage !== "lost" && <YourMove />}
        {(opp.value || opp.budget) && <span className="text-xs text-muted">{opp.value ? money(opp.value) : opp.budget}</span>}
        {opp.fit && <Fit value={opp.fit} />}
      </div>
      <div className="mt-2 flex items-center text-xs">
        {rem ? (
          <span className={cx("inline-flex items-center gap-1", DUE_TONE[rem.tone])}>
            <Bell size={11} /> {rem.text}
          </span>
        ) : (
          <span className="text-muted">{ago(opp.last_activity_at)}</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- list (sortable)

type SortKey = "company" | "stage" | "channel" | "next" | "activity" | "value";

function ListView({ opps }: { opps: Summary[] }) {
  const { data: meta } = useMeta();
  const drawer = useDrawer();
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "activity", dir: -1 });
  const order = useMemo(() => Object.fromEntries((meta?.stages ?? []).map((s, i) => [s.value, i])), [meta]);

  const sorted = useMemo(() => {
    const val = (o: Summary): string | number => {
      switch (sort.key) {
        case "company": return o.company.toLowerCase();
        case "stage": return order[o.stage] ?? 0;
        case "channel": return o.channel;
        case "next": return o.next_reminder ? new Date(o.next_reminder.due_at).getTime() : Number.MAX_SAFE_INTEGER * sort.dir;
        case "value": return o.value ?? -1;
        default: return new Date(o.last_activity_at).getTime();
      }
    };
    return [...opps].sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * sort.dir);
  }, [opps, sort, order]);

  const Th = ({ k, children, className }: { k: SortKey; children: string; className?: string }) => (
    <th className={cx("px-3 py-2 text-left font-medium", className)}>
      <button
        className="inline-flex items-center gap-1 hover:text-fg"
        onClick={() => setSort((s) => ({ key: k, dir: s.key === k ? ((-s.dir) as 1 | -1) : k === "company" || k === "next" ? 1 : -1 }))}
      >
        {children}
        {sort.key === k && (sort.dir === 1 ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
      </button>
    </th>
  );

  return (
    <>
      {/* phones: rows */}
      <div className="rounded-2xl border border-line bg-panel p-1 md:hidden">
        {sorted.map((o) => (
          <OppRow key={o.id} opp={o} />
        ))}
      </div>
      {/* desktop: table */}
      <div className="hidden overflow-hidden rounded-2xl border border-line bg-panel md:block">
        <table className="w-full text-[13px]">
          <thead className="border-b border-line text-xs text-muted">
            <tr>
              <Th k="company">Company</Th>
              <Th k="stage">Stage</Th>
              <Th k="channel">Channel</Th>
              <Th k="next">Next step</Th>
              <Th k="value" className="text-right">Value</Th>
              <Th k="activity">Last activity</Th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((o) => {
              const rem = o.next_reminder ? due(o.next_reminder.due_at) : null;
              return (
                <tr key={o.id} {...pressable(() => drawer.open(o.id))} className="cursor-pointer outline-none focus-visible:bg-panel-2 border-b border-line/60 last:border-0 hover:bg-panel-2">
                  <td className="max-w-80 px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">{o.company}</span>
                      {o.waiting_on === "me" && o.stage !== "won" && o.stage !== "lost" && <YourMove />}
                      {o.needs_review && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />}
                    </div>
                    {o.title && <div className="truncate text-muted">{o.title}</div>}
                  </td>
                  <td className="px-3 py-2.5">
                    <StagePill stage={o.stage} />
                  </td>
                  <td className="px-3 py-2.5 text-muted">
                    {labelOf(meta?.channels, o.channel)}
                    {o.network !== "none" && <span className="block text-xs">via {labelOf(meta?.networks, o.network)}</span>}
                  </td>
                  <td className="px-3 py-2.5">
                    {rem ? (
                      <span className={DUE_TONE[rem.tone]}>
                        {rem.text}
                        <span className="block max-w-48 truncate text-xs text-muted">{o.next_reminder!.note}</span>
                      </span>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{o.value ? money(o.value) : <span className="text-muted">{o.budget ?? "—"}</span>}</td>
                  <td className="px-3 py-2.5 text-muted">{ago(o.last_activity_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
