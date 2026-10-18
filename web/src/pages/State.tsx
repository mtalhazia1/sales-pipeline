import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { Database, Lock, Plus, Search, Timer, Trash2 } from "lucide-react";
import { api, type AgentRun, type StateRow } from "../lib/api";
import { ago, shortDate } from "../lib/format";
import { useAgentState, useForgetNamespace, useRuns, useStateActions } from "../lib/hooks";
import { labelOf, useMeta } from "../lib/meta";
import { PageHeader } from "../components/Shell";
import { AgentBadge, Button, Chip, Empty, Modal, PageError, PageLoading, Segmented, Select, cx, pressable } from "../components/ui";
import { useConfirm } from "../components/confirm";

/** What scheduled agents remember between runs (MCP run_start / state_set / count / seen) and how each run went.
 *  Rows you save here are yours: locked (owner) ones agents can read but not change — in a list they may merge fields. */
export function State() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "memory" | "runs") || "memory";
  const ns = (params.get("ns") ?? "").toLowerCase(); // namespaces are lowercase server-side
  const set = (k: string, v: string) =>
    setParams(
      (p) => {
        if (v) p.set(k, v);
        else p.delete(k);
        return p;
      },
      { replace: true },
    );

  return (
    <>
      <PageHeader title="State" sub="What your scheduled agents remember between runs, and how each run went.">
        <Segmented
          value={tab}
          onChange={(v) => set("tab", v === "memory" ? "" : v)}
          options={[
            { value: "memory", label: "Memory" },
            { value: "runs", label: "Runs" },
          ]}
        />
      </PageHeader>
      {tab === "memory" ? <Memory ns={ns} setNs={(v) => set("ns", v)} /> : <Runs ns={ns} setNs={(v) => set("ns", v)} />}
    </>
  );
}

// ---------------------------------------------------------------- memory

function Memory({ ns, setNs }: { ns: string; setNs: (v: string) => void }) {
  const [section, setSection] = useState("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState(""); // q, debounced so typing doesn't refetch every keystroke
  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const { data, isLoading, error, refetch } = useAgentState({ ns, section, q: query });
  const { data: meta } = useMeta();
  const [editing, setEditing] = useState<{ row?: StateRow } | null>(null);
  const forget = useForgetNamespace();
  const confirm = useConfirm();
  const fixed = new Set(meta?.state_sections.map((x) => x.value));
  const forgetNs = async () => {
    const body = "Deletes its rows, counters, seen ids and run history. Do this when you retire an agent; a running one starts from scratch.";
    if (await confirm({ title: `Forget ${ns}?`, body, confirm: "Forget", danger: true })) forget.mutate(ns, { onSuccess: () => setNs("") });
  };

  if (error && !data) return <PageError error={error} onRetry={refetch} />;
  if (isLoading || !data) return <PageLoading />;
  const counters = Object.entries(data.counters).filter(([n]) => !ns || n === ns);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select className="w-auto" value={ns} onChange={setNs} placeholder="All namespaces" options={data.namespaces.map((n) => ({ value: n, label: n }))} />
        <Select
          className="w-auto"
          value={section}
          onChange={setSection}
          placeholder="All sections"
          options={data.sections.map((x) => ({ value: x, label: fixed.has(x) ? `${x} · ${labelOf(meta?.state_sections, x)}` : `${x} (list)` }))}
        />
        <div className="relative min-w-40 flex-1">
          <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
          <input className="field pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find in keys and values" />
        </div>
        <Button onClick={() => setEditing({})}>
          <Plus size={15} /> Add row
        </Button>
        {ns && (
          <Button variant="ghost" onClick={forgetNs} disabled={forget.isPending} title={`Delete everything in ${ns}`}>
            <Trash2 size={15} /> Forget {ns}
          </Button>
        )}
      </div>

      {counters.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-2">
          {counters.flatMap(([n, keys]) =>
            Object.entries(keys).map(([key, periods]) => (
              <div key={`${n}/${key}`} className="rounded-xl border border-line bg-panel px-3 py-2 text-[13px]">
                <div className="flex items-center gap-1.5 font-medium">
                  <Timer size={13} className="text-muted" /> {n} · {key}
                </div>
                <div className="mt-0.5 text-xs text-muted">
                  {["day", "week", "month", "total"]
                    .filter((p) => periods[p] !== undefined)
                    .map((p) => `${p === "total" ? "all time" : `this ${p}`} ${periods[p]}`)
                    .join(" · ")}
                </div>
              </div>
            )),
          )}
        </div>
      )}

      {data.more && (
        <p className="mb-3 rounded-xl border border-line bg-panel-2/60 px-4 py-2.5 text-[13px] text-muted">
          Showing the first {data.rows.length.toLocaleString()} rows — pick a namespace or section, or search, to see the rest.
        </p>
      )}
      {!data.rows.length ? (
        <Empty icon={<Database size={28} />} title={ns || section || q ? "Nothing matches" : "No agent state yet"}>
          Scheduled agents keep their cursors, stops, lessons and lists here (MCP run_start, state_set). Rows you add are owner rows
          (locked to agents) unless you untick it.
        </Empty>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-line bg-panel">
          {data.rows.map((r) => (
            <div
              key={`${r.ns}/${r.section}/${r.key}`}
              {...pressable(() => setEditing({ row: r }))}
              aria-label={`${r.ns} / ${r.section} / ${r.key}`}
              className="flex cursor-pointer flex-col gap-1 border-b border-line px-4 py-2.5 last:border-b-0 hover:bg-panel-2/60 md:flex-row md:items-baseline md:gap-4"
            >
              <div className="flex min-w-0 items-baseline gap-1.5 md:w-72 md:shrink-0">
                <span className="shrink-0 text-xs text-muted">
                  {r.ns} / {r.section} /
                </span>
                <span className="truncate font-mono text-[13px] font-medium">{r.key}</span>
                {r.locked && <Lock size={12} className="shrink-0 self-center text-muted" aria-label="Locked: agents can't change it" />}
              </div>
              <div className="line-clamp-2 min-w-0 flex-1 font-mono text-[12.5px] break-all text-muted">{preview(r.value)}</div>
              <div className="flex shrink-0 items-center gap-2 text-xs text-muted">
                {r.due_at && (
                  <Chip title={`Due ${new Date(r.due_at).toLocaleString()}`} className={cx(new Date(r.due_at) <= new Date() && "bg-rose-500/12 text-rose-700 dark:text-rose-300")}>
                    due {shortDate(r.due_at)}
                  </Chip>
                )}
                {r.expires_at && <Chip title={`Expires ${new Date(r.expires_at).toLocaleString()}`}>expires {shortDate(r.expires_at)}</Chip>}
                {r.by === "owner" ? <span>you</span> : <AgentBadge name={r.by} />}
                <span>{ago(r.updated_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
      {editing && <RowEditor row={editing.row} ns={ns} section={section} known={data} onClose={() => setEditing(null)} />}
    </>
  );
}

function preview(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
}

/** Integers past 2^53 lose digits in the browser's JSON (a LinkedIn URN, a snowflake id), so such a value
 *  is never re-sent from here: it would come back rounded. */
function hasUnsafeInt(v: unknown): boolean {
  if (typeof v === "number") return Number.isInteger(v) && !Number.isSafeInteger(v);
  if (v && typeof v === "object") return Object.values(v).some(hasUnsafeInt);
  return false;
}

/** A stored UTC time as "YYYY-MM-DDTHH:mm" in the workspace timezone — what the server reads a time without an offset as. */
function localInput(iso: string | undefined, tz: string | undefined): string {
  if (!iso) return "";
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date(iso))
      .map((x) => [x.type, x.value]),
  );
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

function RowEditor({ row, ns, section, known, onClose }: {
  row?: StateRow;
  ns: string;
  section: string;
  known: { namespaces: string[]; sections: string[] };
  onClose: () => void;
}) {
  const save = useStateActions();
  const confirm = useConfirm();
  const { data: meta } = useMeta();
  const [rowNs, setRowNs] = useState(row?.ns ?? ns);
  const [rowSection, setRowSection] = useState(row?.section ?? section);
  const [key, setKey] = useState(row?.key ?? "");
  const tz = meta?.timezone;
  const original = row ? (typeof row.value === "string" ? row.value : JSON.stringify(row.value, null, 2)) : "";
  const [text, setText] = useState(original);
  const [expires, setExpires] = useState(() => localInput(row?.expires_at, tz));
  const [due, setDue] = useState(() => localInput(row?.due_at, tz));
  // Your new rows are owner rows by default; editing an agent's row keeps it writable for the agent unless you lock it.
  const [locked, setLocked] = useState(row ? !!row.locked : true);
  const isList = !!rowSection.trim() && !meta?.state_sections.some((x) => x.value === rowSection.trim().toLowerCase());
  const frozen = !!row && hasUnsafeInt(row.value); // value read-only here; due, expiry and lock still editable
  const valueChanged = !row || text !== original;
  const dueChanged = due !== localInput(row?.due_at, tz);
  const expiresChanged = expires !== localInput(row?.expires_at, tz);
  const dirty = valueChanged || key !== (row?.key ?? "") || dueChanged || expiresChanged || locked !== (row ? !!row.locked : true);

  // A text row stays text. Anything else must be JSON; a new row is JSON when it parses (42, {"a": 1}), else text.
  let value: unknown = text;
  let problem = "";
  if (!(row && typeof row.value === "string")) {
    try {
      value = JSON.parse(text);
      if (value === null) problem = "null would delete the row — use Delete.";
      else if (valueChanged && hasUnsafeInt(value)) problem = "A number this large loses digits here — put it in quotes to store it as text.";
    } catch {
      if (row) problem = "Not valid JSON.";
    }
  }
  const missing = !rowNs.trim() || !rowSection.trim() || !key.trim() || (!row && !text.trim());

  const submit = async () => {
    if (missing || problem || save.isPending) return;
    // Adding a key that exists would silently replace it (an agent's row, or one of yours).
    if (!row) {
      const found = await api
        .post<{ state?: Record<string, unknown> }>("/state/get", { ns: rowNs, sections: [rowSection], keys: [key], limit: 1 })
        .catch(() => null);
      if (found?.state && Object.keys(found.state).length && !(await confirm({ title: `${key} already exists`, body: "Replace its value?", confirm: "Replace" }))) return;
    }
    try {
      // Only what changed is sent: an unchanged value isn't rewritten (so an agent's newer write or a big number survives),
      // and an emptied due / expiry is sent as null, which clears it.
      await save.mutateAsync({
        ns: rowNs,
        section: rowSection,
        key,
        ...(valueChanged ? { value } : {}),
        ...(dueChanged ? { due: due.trim() || null } : {}),
        ...(expiresChanged ? { expires: expires.trim() || null } : {}),
        locked,
      });
      onClose();
    } catch {
      // the mutation already showed the error toast
    }
  };
  const remove = async () => {
    if (!row || !(await confirm({ title: `Delete ${row.key}?`, body: "Agents will no longer see it.", confirm: "Delete", danger: true }))) return;
    try {
      await save.mutateAsync({ ns: row.ns, section: row.section, key: row.key, op: "delete" });
      onClose();
    } catch {
      // toast shown
    }
  };

  return (
    <Modal open onClose={onClose} title={row ? `${row.ns} / ${row.section} / ${row.key}` : "Add a row"} width="max-w-2xl" dismissable={!dirty}>
      <div className="space-y-3 p-5">
        {!row && (
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <span className="label">Namespace</span>
              <input autoFocus className="field" list="state-ns" value={rowNs} onChange={(e) => setRowNs(e.target.value)} placeholder="linkedin" />
              <datalist id="state-ns">{known.namespaces.map((n) => <option key={n} value={n} />)}</datalist>
            </div>
            <div>
              <span className="label">Section</span>
              <input className="field" list="state-sections" value={rowSection} onChange={(e) => setRowSection(e.target.value)} placeholder="stop" />
              <datalist id="state-sections">{known.sections.map((x) => <option key={x} value={x} />)}</datalist>
            </div>
            <div>
              <span className="label">Key</span>
              <input className="field" value={key} onChange={(e) => setKey(e.target.value)} placeholder="account_warning" maxLength={200} />
            </div>
          </div>
        )}
        <div>
          <span className="label">Value {row && typeof row.value !== "string" ? "(JSON)" : row ? "(text)" : "(text or JSON)"}</span>
          <textarea
            className={cx("field min-h-40 resize-y font-mono text-[13px] leading-relaxed", problem && "border-rose-500", frozen && "opacity-70")}
            rows={8}
            readOnly={frozen}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && submit()}
            placeholder={'Paused until the warning clears\nor {"until": "2026-11-01", "why": "…"}'}
          />
          {problem && <div className="mt-1 text-xs text-rose-600 dark:text-rose-300">{problem}</div>}
          {frozen && (
            <div className="mt-1 text-xs text-muted">
              Has a number too large to edit here without losing digits — you can still change due, expiry and lock.
            </div>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {(isList || row?.due_at) && (
            <div>
              <span className="label">Due (optional, {tz}): when an agent should work it</span>
              <input className="field" value={due} onChange={(e) => setDue(e.target.value)} placeholder="2026-11-01 or 2026-11-01T14:00" />
            </div>
          )}
          <div>
            <span className="label">Expires (optional, {tz})</span>
            <input className="field" value={expires} onChange={(e) => setExpires(e.target.value)} placeholder="7d, 12h or 2026-11-01" />
          </div>
        </div>
        <label className="flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={locked} onChange={(e) => setLocked(e.target.checked)} />
          Owner row: agents can read it but not change it{isList && " (they may only add or update fields, and reschedule it)"}
        </label>
        <div className="flex items-center gap-1.5">
          {row && (
            <Button variant="danger" onClick={remove} disabled={save.isPending}>
              Delete
            </Button>
          )}
          <div className="ml-auto flex gap-1.5">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" onClick={submit} disabled={save.isPending || missing || !!problem}>
              Save
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- runs

const RUN_STYLE: Record<string, string> = {
  running: "bg-sky-500/12 text-sky-700 dark:text-sky-300",
  quiet: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300",
  routine: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300",
  attention: "bg-orange-500/15 text-orange-700 dark:text-orange-300",
  error: "bg-rose-500/12 text-rose-700 dark:text-rose-300",
};
const FILTERS = { all: "", active: "running,routine,attention,error", attention: "attention", error: "error" } as const;

function Runs({ ns, setNs }: { ns: string; setNs: (v: string) => void }) {
  const [filter, setFilter] = useState<keyof typeof FILTERS>("active");
  const [limit, setLimit] = useState(100);
  const { data: runs, isLoading, error, refetch } = useRuns({ ns, status: FILTERS[filter], limit });
  const { data: state } = useAgentState({ limit: 0 }); // only the namespace list
  const { data: meta } = useMeta();

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select className="w-auto" value={ns} onChange={setNs} placeholder="All namespaces" options={(state?.namespaces ?? []).map((n) => ({ value: n, label: n }))} />
        <Segmented
          value={filter}
          onChange={(v) => {
            setFilter(v);
            setLimit(100);
          }}
          options={[
            { value: "active", label: "Not quiet" },
            { value: "attention", label: "Attention" },
            { value: "error", label: "Errors" },
            { value: "all", label: "All" },
          ]}
        />
      </div>
      {error && !runs ? (
        <PageError error={error} onRetry={refetch} />
      ) : isLoading || !runs ? (
        <PageLoading />
      ) : !runs.length ? (
        <Empty icon={<Timer size={28} />} title="No runs here">
          Scheduled agents log a run with MCP run_start and run_end; quiet runs are hidden unless you pick All.
        </Empty>
      ) : (
        <>
          <div className="overflow-hidden rounded-2xl border border-line bg-panel">
            {runs.map((r) => (
              <RunRow key={r.id} r={r} label={r.status === "running" ? "Running" : labelOf(meta?.run_statuses, r.status)} />
            ))}
          </div>
          {runs.length >= limit && limit < 500 && (
            <div className="mt-3 flex justify-center">
              <Button size="sm" onClick={() => setLimit((l) => l + 100)}>
                Show more
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}

function RunRow({ r, label }: { r: AgentRun; label: string }) {
  const counts = Object.entries(r.counts);
  return (
    <div className="flex flex-col gap-1 border-b border-line px-4 py-2.5 last:border-b-0 md:flex-row md:items-baseline md:gap-4">
      <div className="flex items-center gap-2 md:w-64 md:shrink-0">
        <span className={cx("rounded-full px-2 py-0.5 text-xs font-medium", RUN_STYLE[r.status] ?? RUN_STYLE.quiet)}>{label}</span>
        <span className="truncate font-medium">
          {r.ns}
          <span className="text-muted"> · {r.worker}</span>
        </span>
      </div>
      <div className="min-w-0 flex-1">
        <div className={cx("text-[14px]", !r.summary && "text-muted")}>{r.summary ?? (r.status === "running" ? "In progress…" : "No summary")}</div>
        {counts.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {counts.map(([k, v]) => (
              <Chip key={k}>
                {k} {v}
              </Chip>
            ))}
          </div>
        )}
      </div>
      <div className="shrink-0 text-xs text-muted" title={new Date(r.started_at).toLocaleString()}>
        {ago(r.started_at)}
        {r.ended_at && ` · ${duration(r.started_at, r.ended_at)}`}
      </div>
    </div>
  );
}

function duration(from: string, to: string): string {
  const s = Math.max(0, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}
