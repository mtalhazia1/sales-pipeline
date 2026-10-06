import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowRight, Bell, Bot, Check, ChevronDown, ExternalLink, Inbox, MessageSquareReply, MessageSquareText,
  Phone, StickyNote, Trash2, Trophy, User as UserIcon, X, XCircle,
} from "lucide-react";
import { ApiError, type Detail, type Option, type TimelineEvent } from "../lib/api";
import { ago, due, hostOf, href, inDays, money, nextMonday, parseMoney, snoozed } from "../lib/format";
import { labelOf, useMeta } from "../lib/meta";
import { useDrawer, useOppActions, useOpportunity } from "../lib/hooks";
import { Button, Fit, Modal, Segmented, Select, Spinner, StagePill, YourMove, cx, useToast } from "./ui";
import { DUE_TONE } from "./OppRow";
import { useConfirm } from "./confirm";

export function Drawer() {
  const drawer = useDrawer();
  const { data: opp, isLoading, error } = useOpportunity(drawer.id);

  useEffect(() => {
    if (drawer.id == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector("[role=dialog]")) return;
      const el = e.target as HTMLElement;
      if (el?.closest?.("input,textarea,select")) el.blur(); // first Esc leaves the field, second closes
      else drawer.close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  if (drawer.id == null) return null;
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/25 md:bg-black/10" onClick={drawer.close} />
      <aside className="anim-slide fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-line bg-panel shadow-2xl sm:w-[560px]">
        {(!opp || error) && (
          <div className="flex justify-end border-b border-line px-4 py-2.5">
            <button className="rounded-lg p-2 text-muted hover:bg-panel-2 hover:text-fg" onClick={drawer.close} title="Close (Esc)">
              <X size={18} />
            </button>
          </div>
        )}
        {isLoading && (
          <div className="flex flex-1 items-center justify-center">
            <Spinner />
          </div>
        )}
        {error && (
          <div className="p-6 text-muted">
            {error instanceof ApiError && error.status === 404 ? "This opportunity no longer exists." : `Couldn't load it — ${error.message}`}
          </div>
        )}
        {/* After a delete the cache can still hold the old record next to a 404 — never show it as editable. */}
        {opp && !error && <DrawerBody key={opp.id} opp={opp} />}
      </aside>
    </>
  );
}

function DrawerBody({ opp }: { opp: Detail }) {
  const { data: meta } = useMeta();
  const drawer = useDrawer();
  const act = useOppActions();
  const confirm = useConfirm();
  const [composer, setComposer] = useState<string | null>(null);
  const [lostOpen, setLostOpen] = useState(false);
  const toast = useToast();
  // `revert` puts an inline field back to the saved value when the server refuses the edit.
  const save = (patch: Record<string, unknown>, revert?: () => void) => act.update.mutate({ id: opp.id, ...patch }, { onError: revert });
  const closed = opp.stage === "won" || opp.stage === "lost";
  const stages = (meta?.stages ?? []).filter((s) => s.value !== "matcher" || opp.channel === "toptal" || opp.stage === "matcher");

  return (
    <>
      {/* header */}
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <div className="relative">
          <select
            value={opp.stage}
            onChange={(e) => (e.target.value === "lost" ? setLostOpen(true) : save({ stage: e.target.value }))}
            className="absolute inset-0 cursor-pointer opacity-0"
            aria-label="Stage"
          >
            {stages.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <span className="pointer-events-none inline-flex items-center gap-1">
            <StagePill stage={opp.stage} />
            <ChevronDown size={14} className="text-muted" />
          </span>
        </div>
        {opp.stage === "lost" && opp.lost_reason && <span className="text-xs text-muted">{labelOf(meta?.lost_reasons, opp.lost_reason)}</span>}
        {opp.waiting_on === "me" && !closed && <YourMove />}
        {opp.waiting_on === "client" && !closed && <span className="text-xs text-muted">Waiting on client</span>}
        <div className="ml-auto flex items-center gap-0.5">
          {opp.application_url && (
            <a href={href(opp.application_url)} target="_blank" rel="noreferrer" className="rounded-lg p-2 text-muted hover:bg-panel-2 hover:text-fg" title="Open posting">
              <ExternalLink size={16} />
            </a>
          )}
          <button
            className="rounded-lg p-2 text-muted hover:bg-panel-2 hover:text-rose-500"
            title="Delete"
            onClick={async () => {
              if (await confirm({ title: `Delete ${opp.company}?`, body: "It disappears from the pipeline and stats.", confirm: "Delete", danger: true })) {
                act.remove.mutate({ id: opp.id });
                drawer.close();
              }
            }}
          >
            <Trash2 size={16} />
          </button>
          <button className="rounded-lg p-2 text-muted hover:bg-panel-2 hover:text-fg" onClick={drawer.close} title="Close (Esc)">
            <X size={18} />
          </button>
        </div>
      </div>

      <div className="scroll-thin flex-1 overflow-y-auto">
        {opp.needs_review && (
          <div className="flex items-center gap-3 border-b border-line bg-accent/8 px-5 py-2.5 text-[13px]">
            <Bot size={16} className="shrink-0 text-accent" />
            <span className="flex-1">Changed by an agent — check the timeline below.</span>
            <Button size="sm" variant="primary" onClick={() => act.review.mutate({ id: opp.id })}>
              <Check size={14} /> Looks good
            </Button>
          </div>
        )}

        <div className="space-y-1 px-5 pt-4">
          <InlineText value={opp.company} onSave={(v, revert) => save({ company: v }, revert)} className="text-xl font-semibold tracking-tight" placeholder="Company" required />
          <InlineText value={opp.title ?? ""} onSave={(v, revert) => save({ title: v }, revert)} className="text-[15px] text-muted" placeholder="Add a title…" />
        </div>

        {/* quick actions */}
        <div className="flex flex-wrap gap-1.5 px-5 pt-4">
          <Button size="sm" onClick={() => setComposer("client_message")}>
            <MessageSquareReply size={14} /> Client replied
          </Button>
          <Button size="sm" onClick={() => setComposer("my_message")}>
            <MessageSquareText size={14} /> I replied
          </Button>
          <Button size="sm" onClick={() => setComposer("call")}>
            <Phone size={14} /> Call
          </Button>
          <Button size="sm" onClick={() => setComposer("note")}>
            <StickyNote size={14} /> Note
          </Button>
          <Button size="sm" onClick={() => setComposer("reminder")}>
            <Bell size={14} /> Remind
          </Button>
          {!closed && (
            <>
              <Button size="sm" className="text-emerald-600 dark:text-emerald-300" onClick={() => save({ stage: "won" })}>
                <Trophy size={14} /> Won
              </Button>
              <Button size="sm" className="text-rose-600 dark:text-rose-300" onClick={() => setLostOpen(true)}>
                <XCircle size={14} /> Lost
              </Button>
            </>
          )}
        </div>
        {composer && <Composer key={composer} kind={composer} opp={opp} onDone={() => setComposer(null)} />}

        <Reminders opp={opp} />

        {/* details */}
        <Section title="Details">
          <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
            <Field label="Type">
              <Segmented value={opp.kind} onChange={(v) => save({ kind: v })} options={meta?.kinds ?? []} />
            </Field>
            <Field label="Fit">
              <div className="flex h-9 items-center">
                <Fit value={opp.fit} onChange={(v) => save({ fit: v })} />
              </div>
            </Field>
            <Field label="Channel">
              <Select value={opp.channel} onChange={(v) => save({ channel: v })} options={meta?.channels ?? []} />
            </Field>
            <Field label="Network">
              <Select value={opp.network} onChange={(v) => save({ network: v })} options={meta?.networks ?? []} />
            </Field>
            <Field label="Whose move">
              <Select
                value={opp.waiting_on ?? ""}
                onChange={(v) => save({ waiting_on: v || null })}
                options={[{ value: "me", label: "Mine" }, { value: "client", label: "Client's" }]}
                placeholder="—"
              />
            </Field>
            <Field label="Origin">
              <Segmented
                value={opp.inbound ? "in" : "out"}
                onChange={(v) => save({ inbound: v === "in" })}
                options={[{ value: "out", label: "I reached out" }, { value: "in", label: <><Inbox size={13} /> Inbound</> }]}
              />
            </Field>
            <Field label="Budget (as posted)">
              <InlineInput value={opp.budget} onSave={(v, revert) => save({ budget: v }, revert)} placeholder="$50-70/hr" />
            </Field>
            <Field label="Deal value (USD)">
              <InlineInput
                value={opp.value != null ? String(opp.value) : ""}
                onSave={(v, revert) => {
                  const n = v ? parseMoney(v) : null;
                  if (v && n == null) {
                    revert();
                    return toast.error(`"${v}" isn't an amount — try 8000, 8k or 1.5M`);
                  }
                  save({ value: n }, revert);
                }}
                placeholder="8000, 8k, 1.5M"
                inputMode="decimal"
              />
            </Field>
            <Field label="Contact">
              <InlineInput value={opp.contact_name} onSave={(v, revert) => save({ contact_name: v }, revert)} placeholder="Name" />
            </Field>
            <Field label="Contact email">
              <InlineInput value={opp.contact_email} onSave={(v, revert) => save({ contact_email: v }, revert)} placeholder="name@company.com" type="email" />
            </Field>
            <Field label="Contact profile">
              <LinkInput value={opp.contact_url} onSave={(v, revert) => save({ contact_url: v }, revert)} placeholder="linkedin.com/in/…" />
            </Field>
            <Field label="Company site">
              <LinkInput value={opp.company_url} onSave={(v, revert) => save({ company_url: v }, revert)} placeholder="company.com" />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Application / posting URL">
                <LinkInput value={opp.application_url} onSave={(v, revert) => save({ application_url: v }, revert)} placeholder="https://…" />
              </Field>
            </div>
          </div>
        </Section>

        <Section title="Notes">
          <InlineArea value={opp.notes} onSave={(v, revert) => save({ notes: v }, revert)} placeholder="Anything worth remembering — pricing, red flags, what they care about…" />
        </Section>

        <Description text={opp.description} onSave={(v, revert) => save({ description: v }, revert)} />

        <Section title="Timeline">
          <Timeline events={opp.events} />
        </Section>
        <div className="px-5 pb-8 text-xs text-muted">
          Added {ago(opp.created_at)} by {opp.created_by}
          {opp.applied_at && <> · applied {ago(opp.applied_at)}</>}
        </div>
      </div>

      <LostDialog open={lostOpen} onClose={() => setLostOpen(false)} onPick={(reason) => save({ stage: "lost", lost_reason: reason })} />
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line px-5 py-4 first:border-t-0 mt-4">
      <h3 className="mb-3 text-xs font-semibold tracking-wide text-muted uppercase">{title}</h3>
      {children}
    </section>
  );
}

// A <div>, not a <label>: a label forwards any click on its text or empty space to the first button
// inside (Fit's first star, Type's first option), silently changing data.
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="group" aria-label={label}>
      <span className="label">{label}</span>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- inline editing (save on blur / Enter, Esc cancels)

type OnSave = (v: string, revert: () => void) => void;

function useInlineEdit(saved: string, onSave: OnSave, opts: { trim?: boolean; required?: boolean; enterSaves?: boolean } = {}) {
  const { trim = true, required = false, enterSaves = true } = opts;
  const [v, setV] = useState(saved);
  const cancelled = useRef(false);
  useEffect(() => setV(saved), [saved]);
  const norm = (s: string) => (trim ? s.trim() : s);
  return {
    value: v,
    onChange: (e: React.ChangeEvent<HTMLInputElement & HTMLTextAreaElement>) => setV(e.target.value),
    onBlur: () => {
      if (cancelled.current || (required && !norm(v))) {
        cancelled.current = false;
        return setV(saved);
      }
      if (norm(v) !== norm(saved)) onSave(norm(v), () => setV(saved));
    },
    onKeyDown: (e: React.KeyboardEvent<HTMLInputElement & HTMLTextAreaElement>) => {
      if (e.key === "Escape") {
        cancelled.current = true;
        e.currentTarget.blur();
      } else if (enterSaves && e.key === "Enter") e.currentTarget.blur();
    },
  };
}

function InlineText({ value, onSave, className, placeholder, required }: {
  value: string;
  onSave: OnSave;
  className?: string;
  placeholder?: string;
  required?: boolean;
}) {
  const edit = useInlineEdit(value, onSave, { required });
  return (
    <input
      {...edit}
      placeholder={placeholder}
      className={cx("-mx-1.5 w-full rounded-md bg-transparent px-1.5 py-0.5 outline-none hover:bg-panel-2 focus:bg-panel-2 placeholder:text-muted/60", className)}
    />
  );
}

function InlineInput({ value, onSave, ...rest }: {
  value: string | null;
  onSave: OnSave;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  const edit = useInlineEdit(value ?? "", onSave);
  return <input {...rest} {...edit} className="field" />;
}

function LinkInput(props: { value: string | null; onSave: OnSave; placeholder?: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <InlineInput {...props} />
      {props.value && (
        <a href={href(props.value)} target="_blank" rel="noreferrer" className="shrink-0 rounded-lg p-2 text-muted hover:bg-panel-2 hover:text-fg" title={hostOf(props.value)}>
          <ExternalLink size={15} />
        </a>
      )}
    </div>
  );
}

function InlineArea({ value, onSave, placeholder, rows = 4 }: { value: string | null; onSave: OnSave; placeholder?: string; rows?: number }) {
  const edit = useInlineEdit(value ?? "", onSave, { trim: false, enterSaves: false });
  return <textarea {...edit} rows={rows} placeholder={placeholder} className="field min-h-24 resize-y leading-relaxed" />;
}

function Description({ text, onSave }: { text: string | null; onSave: OnSave }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="mt-4 border-t border-line px-5 py-4">
      <button className="mb-3 flex w-full items-center gap-1 text-xs font-semibold tracking-wide text-muted uppercase" onClick={() => setOpen(!open)}>
        Job post / brief
        <ChevronDown size={14} className={cx("transition", open && "rotate-180")} />
        {!open && text && <span className="ml-2 truncate font-normal normal-case tracking-normal">{text.slice(0, 80)}</span>}
      </button>
      {open && <InlineArea value={text} onSave={onSave} placeholder="Paste the job post or project brief" rows={10} />}
    </section>
  );
}

// ---------------------------------------------------------------- composer

const COMPOSER: Record<string, { title: string; placeholder: string }> = {
  client_message: { title: "What did the client say?", placeholder: "They want a call next week, budget is fine…" },
  my_message: { title: "What did you send?", placeholder: "Sent follow-up with case study…" },
  call: { title: "How did the call go?", placeholder: "30 min intro — they need an MVP by December…" },
  note: { title: "Note", placeholder: "Anything worth remembering" },
};

function Composer({ kind, opp, onDone }: { kind: string; opp: Detail; onDone: () => void }) {
  const act = useOppActions();
  const [body, setBody] = useState("");
  const [when, setWhen] = useState("");
  const [followUp, setFollowUp] = useState(kind === "my_message" ? inDays(3) : "");
  const logged = useRef(false); // if only the follow-up failed, Save again must not log the message twice
  if (kind === "reminder") return <ReminderComposer opp={opp} onDone={onDone} />;
  const cfg = COMPOSER[kind];
  const busy = act.log.isPending || act.remind.isPending;
  const submit = async () => {
    if (busy) return;
    try {
      if (!logged.current) {
        await act.log.mutateAsync({ id: opp.id, kind, body, occurred_at: when || undefined });
        logged.current = true;
      }
      if (followUp) await act.remind.mutateAsync({ id: opp.id, due_at: followUp, note: "Follow up if no reply" });
      onDone();
    } catch {
      // the mutation already showed the error toast
    }
  };
  return (
    <div className="anim-pop mx-5 mt-3 space-y-2 rounded-xl border border-line bg-panel-2/60 p-3">
      <div className="text-[13px] font-medium">{cfg.title}</div>
      <textarea
        autoFocus
        rows={3}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && submit()}
        placeholder={cfg.placeholder}
        className="field resize-none"
      />
      <div className="flex flex-wrap items-center gap-2 text-[13px]">
        <label className="flex items-center gap-1.5 text-muted">
          When
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className="field h-8 w-auto py-0 text-[13px]" />
        </label>
        {kind === "my_message" && (
          <label className="flex items-center gap-1.5 text-muted">
            <Bell size={13} /> Follow up
            <input type="date" value={followUp} onChange={(e) => setFollowUp(e.target.value)} className="field h-8 w-auto py-0 text-[13px]" />
          </label>
        )}
        <div className="ml-auto flex gap-1.5">
          <Button size="sm" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
          <Button size="sm" variant="primary" onClick={submit} disabled={busy}>
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}

function ReminderComposer({ opp, onDone }: { opp: Detail; onDone: () => void }) {
  const act = useOppActions();
  const [note, setNote] = useState("Follow up");
  const [date, setDate] = useState(inDays(3));
  const set = async (d: string) => {
    if (act.remind.isPending) return;
    try {
      await act.remind.mutateAsync({ id: opp.id, due_at: d, note });
      onDone();
    } catch {
      // error toast already shown
    }
  };
  return (
    <div className="anim-pop mx-5 mt-3 space-y-2 rounded-xl border border-line bg-panel-2/60 p-3">
      <input autoFocus value={note} onChange={(e) => setNote(e.target.value)} className="field" placeholder="Next step" />
      <div className="flex flex-wrap items-center gap-1.5">
        <Button size="sm" onClick={() => set(inDays(1))}>Tomorrow</Button>
        <Button size="sm" onClick={() => set(inDays(3))}>In 3 days</Button>
        <Button size="sm" onClick={() => set(nextMonday())}>Next Monday</Button>
        <Button size="sm" onClick={() => set(inDays(14))}>In 2 weeks</Button>
        <span className="mx-1 text-muted">or</span>
        <input type="datetime-local" value={date.length === 10 ? `${date}T09:00` : date} onChange={(e) => setDate(e.target.value)} className="field h-8 w-auto py-0 text-[13px]" />
        <Button size="sm" variant="primary" onClick={() => set(date)}>Set</Button>
        <Button size="sm" variant="ghost" onClick={onDone}>Cancel</Button>
      </div>
    </div>
  );
}

function Reminders({ opp }: { opp: Detail }) {
  const act = useOppActions();
  const open = opp.reminders.filter((r) => !r.done_at);
  if (!open.length) return null;
  return (
    <div className="mx-5 mt-4 space-y-1">
      {open.map((r) => {
        const d = due(r.due_at);
        return (
          <div key={r.id} className="group flex items-center gap-2.5 rounded-lg border border-line px-3 py-2">
            <button
              onClick={() => act.reminder.mutate({ id: opp.id, reminderId: r.id, done: true })}
              className="group/done -m-1.5 shrink-0 p-1.5"
              title="Done"
              aria-label="Mark done"
            >
              <span className="block h-4.5 w-4.5 rounded-full border-2 border-line group-hover/done:border-emerald-500 group-hover/done:bg-emerald-500/15" />
            </button>
            <Bell size={14} className={DUE_TONE[d.tone]} />
            <span className="flex-1 truncate text-[13px]">{r.note || "Reminder"}</span>
            <span className={cx("text-xs", DUE_TONE[d.tone])}>{d.text}</span>
            <button
              onClick={() => act.reminder.mutate({ id: opp.id, reminderId: r.id, due_at: snoozed(r.due_at) })}
              className="rounded px-1.5 py-1 text-xs text-muted hover:bg-panel-2 hover:text-fg"
              title="Push back a day"
            >
              +1d
            </button>
            <button
              onClick={() => act.deleteReminder.mutate({ id: opp.id, reminderId: r.id })}
              className="rounded p-1 text-muted hover:bg-panel-2 hover:text-rose-500"
              title="Remove reminder"
              aria-label="Remove reminder"
            >
              <X size={13} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function LostDialog({ open, onClose, onPick }: { open: boolean; onClose: () => void; onPick: (r: string) => void }) {
  const { data: meta } = useMeta();
  return (
    <Modal open={open} onClose={onClose} title="Why was it lost?" width="max-w-sm">
      <div className="grid gap-1.5 p-4">
        {meta?.lost_reasons.map((r) => (
          <Button
            key={r.value}
            className="justify-start"
            onClick={() => {
              onPick(r.value);
              onClose();
            }}
          >
            {r.label}
          </Button>
        ))}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------- timeline

const EVENT_ICON: Record<string, ReactNode> = {
  client_message: <MessageSquareReply size={14} />,
  my_message: <MessageSquareText size={14} />,
  call: <Phone size={14} />,
  note: <StickyNote size={14} />,
  reminder: <Bell size={14} />,
  reviewed: <Check size={14} />,
};

export function eventTitle(e: TimelineEvent, labels: (field: string, v: unknown) => string): ReactNode {
  switch (e.kind) {
    case "created":
      return "Added";
    case "client_message":
      return "Client messaged";
    case "my_message":
      return "Sent a message";
    case "call":
      return "Call";
    case "note":
      return "Note";
    case "reviewed":
      return "Reviewed";
    case "reminder": {
      const dueAt = e.changes?.due_at?.[1];
      if (e.changes?.deleted) return <>Removed reminder: {e.body ?? "reminder"}</>;
      if (e.changes?.done_at) return e.changes.done_at[1] ? <>Done: {e.body ?? "reminder"}</> : <>Reopened: {e.body ?? "reminder"}</>;
      if (e.changes?.due_at?.[0] != null)
        return (
          <>
            Moved: {e.body ?? "reminder"}
            {typeof dueAt === "string" && <span className="text-muted"> → {due(dueAt).text}</span>}
          </>
        );
      if (e.changes?.note) return <>Reminder reworded: {e.body ?? "—"}</>;
      return (
        <>
          Reminder{e.body ? `: ${e.body}` : ""}
          {typeof dueAt === "string" && <span className="text-muted"> · {due(dueAt).text}</span>}
        </>
      );
    }
    default:
      if (e.body) return e.body;
      return (
        <span className="inline-flex flex-wrap gap-x-3 gap-y-0.5">
          {Object.entries(e.changes ?? {}).map(([f, [a, b]]) => (
            <span key={f}>
              <span className="text-muted">{f.replace(/_/g, " ")}</span>{" "}
              {a != null && a !== "" && <span className="text-muted line-through decoration-muted/50">{labels(f, a)}</span>}
              {a != null && a !== "" && <ArrowRight size={11} className="mx-0.5 inline text-muted" />}
              <span className="font-medium">{labels(f, b) || "—"}</span>
            </span>
          ))}
        </span>
      );
  }
}

export function useChangeLabels() {
  const { data: meta } = useMeta();
  return (field: string, v: unknown): string => {
    if (v == null) return "";
    const map: Record<string, Option[]> = {
      stage: meta?.stages ?? [],
      channel: meta?.channels ?? [],
      network: meta?.networks ?? [],
      kind: meta?.kinds ?? [],
      lost_reason: meta?.lost_reasons ?? [],
    };
    if (map[field]) return labelOf(map[field], String(v));
    if (field === "waiting_on") return v === "me" ? "your move" : "their move";
    if (field === "value") return money(Number(v));
    if (typeof v === "boolean") return v ? "yes" : "no";
    return String(v);
  };
}

function Timeline({ events }: { events: TimelineEvent[] }) {
  const labels = useChangeLabels();
  if (!events.length) return <div className="text-[13px] text-muted">Nothing yet.</div>;
  return (
    <ol className="relative space-y-4 before:absolute before:top-2 before:bottom-2 before:left-[13px] before:w-px before:bg-line">
      {events.map((e) => (
        <li key={e.id} className="relative flex gap-3">
          <div
            className={cx(
              "z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line bg-panel",
              e.kind === "client_message" ? "text-violet-500" : e.actor_type === "agent" ? "text-accent" : "text-muted",
            )}
          >
            {EVENT_ICON[e.kind] ?? (e.actor_type === "agent" ? <Bot size={14} /> : <UserIcon size={14} />)}
          </div>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className="text-[13px]">{eventTitle(e, labels)}</div>
            {e.body && !["updated", "reminder", "created"].includes(e.kind) && (
              <div className="mt-1 rounded-lg bg-panel-2 px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap">{e.body}</div>
            )}
            <div className="mt-1 flex items-center gap-1.5 text-xs text-muted">
              {e.actor_type === "agent" ? (
                <span className="inline-flex items-center gap-1 text-accent">
                  <Bot size={11} />
                  {e.actor_name}
                </span>
              ) : (
                <span>{e.actor_name}</span>
              )}
              · <span title={new Date(e.occurred_at).toLocaleString()}>{ago(e.occurred_at)}</span>
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function useCopy() {
  const toast = useToast();
  return (text: string, what = "Copied") =>
    navigator.clipboard.writeText(text).then(
      () => toast.ok(what),
      () => toast.error("Couldn't copy — select the text and copy it by hand"),
    );
}
