import { useState } from "react";
import { AlertTriangle, Bot, Check, FolderPlus, MessageSquarePlus, Pencil, Trash2 } from "lucide-react";
import type { MessageCategory, TemplateWithUsage } from "../lib/api";
import { ago, pct } from "../lib/format";
import { useTemplateActions, useTemplateCategories, useTemplates } from "../lib/hooks";
import { useMeta } from "../lib/meta";
import { PageHeader } from "../components/Shell";
import { Button, Empty, Modal, PageError, PageLoading, cx } from "../components/ui";
import { useConfirm } from "../components/confirm";

/** The owner's example messages: categories (each with a purpose that tells agents when to use it) and their
 *  variants. Agents fetch a category's current one (MCP get_message_template) as a recommended example and adapt
 *  it to each person, filling the {placeholders}; agents can also add and edit categories and messages, which then wait for review here. */
export function Messages() {
  const cats = useTemplateCategories();
  const msgs = useTemplates();
  const [editing, setEditing] = useState<{ category: MessageCategory; template?: TemplateWithUsage; hasCurrent: boolean } | null>(null);
  const [editingCat, setEditingCat] = useState<{ category?: MessageCategory } | null>(null);
  const error = cats.error ?? msgs.error;
  const list = msgs.data;

  return (
    <>
      <PageHeader
        title="Messages"
        sub={
          <>
            Example messages your agents work from — the <span className="font-medium text-fg">current</span> one in each category. They keep its
            point, tone and length and adapt the wording to each person. Anything that changes per deal is written fresh.
          </>
        }
      >
        <Button onClick={() => setEditingCat({})}>
          <FolderPlus size={15} /> New category
        </Button>
      </PageHeader>
      <p className="mb-6 rounded-xl border border-line bg-panel-2/60 px-4 py-3 text-[13px] text-muted">
        Write placeholders like <code className="text-fg">{"{first_name}"}</code>, <code className="text-fg">{"{company}"}</code> or{" "}
        <code className="text-fg">{"{role}"}</code> — the agent fills them in with facts it checked, or words around them. Small tweaks: edit the
        variant. A different approach: add a new variant, so Insights can compare them. You can also ask an agent to set these up; what it
        writes is marked for your review.
      </p>
      {error && !(cats.data && list) ? (
        <PageError
          error={error}
          onRetry={() => {
            cats.refetch();
            msgs.refetch();
          }}
        />
      ) : !cats.data || !list ? (
        <PageLoading />
      ) : cats.data.length === 0 ? (
        <Empty title="No categories yet">Add one for each kind of message you send again and again, like a LinkedIn intro or a cold email.</Empty>
      ) : (
        <div className="space-y-8">
          {cats.data.map((cat) => {
            const items = list.filter((t) => t.category === cat.key);
            const hasCurrent = items.some((t) => t.is_current);
            return (
              <CategorySection
                key={cat.key}
                cat={cat}
                items={items}
                onEdit={() => setEditingCat({ category: cat })}
                onNew={() => setEditing({ category: cat, hasCurrent })}
                onEditMessage={(t) => setEditing({ category: cat, template: t, hasCurrent })}
              />
            );
          })}
        </div>
      )}
      {editing && <Editor key={editing.template?.id ?? editing.category.key} {...editing} onClose={() => setEditing(null)} />}
      {editingCat && (
        <CategoryEditor
          key={editingCat.category?.key ?? "new"}
          category={editingCat.category}
          hasMessages={!!editingCat.category && !!list?.some((t) => t.category === editingCat.category!.key)}
          onClose={() => setEditingCat(null)}
        />
      )}
    </>
  );
}

function CategorySection({ cat, items, onEdit, onNew, onEditMessage }: {
  cat: MessageCategory;
  items: TemplateWithUsage[];
  onEdit: () => void;
  onNew: () => void;
  onEditMessage: (t: TemplateWithUsage) => void;
}) {
  const act = useTemplateActions();
  const confirm = useConfirm();
  const hasCurrent = items.some((t) => t.is_current);
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">{cat.name}</h2>
            <code className="text-xs text-muted" title="What agents call this category">
              {cat.key}
            </code>
            {cat.has_subject && <span className="text-xs text-muted">· with subject line</span>}
            {cat.needs_review && <ReviewChip by={cat.updated_by} onOk={() => act.updateCategory.mutate({ key: cat.key, updated_at: cat.updated_at })} busy={act.updateCategory.isPending} />}
          </div>
          <p className={cx("mt-0.5 max-w-3xl text-[13px] whitespace-pre-wrap [overflow-wrap:anywhere]", cat.purpose ? "text-muted" : "text-amber-700 dark:text-amber-300")}>
            {cat.purpose ?? "No purpose yet: say when agents should send this, or they won't know."}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" onClick={onEdit} aria-label={`Edit category ${cat.name}`}>
            <Pencil size={14} />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Delete category ${cat.name}`}
            disabled={items.length > 0}
            title={items.length ? "Delete its messages first" : undefined}
            onClick={async () => {
              if (await confirm({ title: `Delete "${cat.name}"?`, confirm: "Delete", danger: true })) act.removeCategory.mutate({ key: cat.key });
            }}
          >
            <Trash2 size={14} />
          </Button>
          <Button size="sm" onClick={onNew}>
            <MessageSquarePlus size={14} /> New variant
          </Button>
        </div>
      </div>
      {items.length > 0 && !hasCurrent && (
        <div className="mb-2 flex items-center gap-2 rounded-xl bg-amber-500/12 px-3 py-2 text-[13px] text-amber-700 dark:text-amber-300">
          <AlertTriangle size={14} className="shrink-0" /> No current message — agents won't send any until you pick one with "Use this".
        </div>
      )}
      {items.length ? (
        <div className="space-y-2">
          {items.map((t) => (
            <TemplateCard key={t.id} t={t} onEdit={() => onEditMessage(t)} />
          ))}
        </div>
      ) : (
        <Empty title={`No ${cat.name.toLowerCase()} yet`}>Agents can't send one until you add it.</Empty>
      )}
    </section>
  );
}

function ReviewChip({ by, onOk, busy }: { by: string | null; onOk: () => void; busy: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-accent/12 py-0.5 pr-0.5 pl-1.5 text-xs font-medium text-accent">
      <Bot size={12} /> {by ? `By ${by}` : "By an agent"} · review
      <button className="rounded px-1.5 py-0.5 font-semibold hover:bg-accent/15 disabled:opacity-50" disabled={busy} onClick={onOk}>
        Looks good
      </button>
    </span>
  );
}

/** "Used 7× · LinkedIn 5 · Email 2", then how deals did when it was their first message. */
function UsageLine({ u }: { u: TemplateWithUsage["usage"] }) {
  const { data: meta } = useMeta();
  if (!u.uses && !u.sent) return <span className="text-xs text-muted">Not sent yet</span>;
  const platforms = (meta?.channels ?? []).filter((c) => u.by_channel[c.value]).map((c) => `${c.label} ${u.by_channel[c.value]}`);
  return (
    <span className="text-xs text-muted tabular-nums">
      {u.uses > 0 && (
        <span title={u.last_used_at ? `Last used ${ago(u.last_used_at)}` : undefined}>
          Used <span className="font-semibold text-fg">{u.uses}×</span>
          {platforms.length > 0 && ` · ${platforms.join(" · ")}`}
        </span>
      )}
      {u.sent > 0 && (
        <span className={cx(u.uses > 0 && "ml-2 border-l border-line pl-2")}>
          First message on {u.sent} · {u.replied} replied ({pct(u.reply_rate)}) · {u.calls} {u.calls === 1 ? "call" : "calls"} · {u.won} won
        </span>
      )}
    </span>
  );
}

function TemplateCard({ t, onEdit }: { t: TemplateWithUsage; onEdit: () => void }) {
  const act = useTemplateActions();
  const confirm = useConfirm();
  const used = t.usage.uses > 0 || t.usage.sent > 0;
  return (
    <div className={cx("rounded-2xl border bg-panel p-4", t.is_current ? "border-emerald-500/50" : "border-line")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t.name}</span>
        {t.is_current && (
          <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/12 px-1.5 py-0.5 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
            <Check size={12} /> Current
          </span>
        )}
        {t.needs_review && <ReviewChip by={t.updated_by} onOk={() => act.update.mutate({ id: t.id, updated_at: t.updated_at })} busy={act.update.isPending} />}
        <UsageLine u={t.usage} />
        <div className="ml-auto flex items-center gap-1">
          {!t.is_current && (
            <Button size="sm" variant="primary" disabled={act.update.isPending} onClick={() => act.update.mutate({ id: t.id, updated_at: t.updated_at, is_current: true })}>
              Use this
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onEdit} aria-label={`Edit ${t.name}`}>
            <Pencil size={14} />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Delete ${t.name}`}
            onClick={async () => {
              const ok = await confirm({
                title: `Delete "${t.name}"?`,
                body:
                  [
                    t.is_current && "It's the current one: agents won't send this kind of message until you pick another.",
                    used && "Deals it was sent to keep its name, and Insights keeps its numbers.",
                  ]
                    .filter(Boolean)
                    .join(" ") || undefined,
                confirm: "Delete",
                danger: true,
              });
              if (ok) act.remove.mutate({ id: t.id });
            }}
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </div>
      {t.subject && (
        <div className="mt-2 text-[13px]">
          <span className="text-muted">Subject:</span> <span className="[overflow-wrap:anywhere]">{t.subject}</span>
        </div>
      )}
      <p className="mt-2 rounded-lg bg-panel-2 px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">{t.body}</p>
      {t.placeholders.length > 0 && (
        <div className="mt-2 text-xs text-muted">Agent fills in: {t.placeholders.map((p) => `{${p}}`).join(", ")}</div>
      )}
    </div>
  );
}

function CategoryEditor({ category, hasMessages, onClose }: { category?: MessageCategory; hasMessages: boolean; onClose: () => void }) {
  const act = useTemplateActions();
  const [name, setName] = useState(category?.name ?? "");
  const [purpose, setPurpose] = useState(category?.purpose ?? "");
  const [subject, setSubject] = useState(category?.has_subject ?? false);
  const dirty = name !== (category?.name ?? "") || purpose !== (category?.purpose ?? "") || subject !== (category?.has_subject ?? false);
  const busy = act.createCategory.isPending || act.updateCategory.isPending;

  const save = async () => {
    if (busy || !name.trim()) return;
    try {
      if (category) await act.updateCategory.mutateAsync({ key: category.key, updated_at: category.updated_at, name, purpose, ...(hasMessages ? {} : { has_subject: subject }) });
      else await act.createCategory.mutateAsync({ name, purpose, has_subject: subject });
      onClose();
    } catch {
      // the mutation already showed the error toast
    }
  };

  return (
    <Modal open onClose={onClose} title={category ? `Edit ${category.name}` : "New category"} dismissable={!dirty}>
      <div className="space-y-3 p-5">
        <div>
          <span className="label">Name</span>
          <input autoFocus className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="Rate card" maxLength={120} />
          {category && <div className="mt-1 text-xs text-muted">Agents keep calling it {category.key} after a rename.</div>}
        </div>
        <div>
          <span className="label">Purpose: when agents should send it</span>
          <textarea
            className="field min-h-24 resize-y leading-relaxed"
            rows={4}
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && save()}
            placeholder="When a client asks about rates, after the first call."
            maxLength={2000}
          />
        </div>
        <label className={cx("flex items-center gap-2 text-[13px]", hasMessages && "text-muted")}>
          <input type="checkbox" checked={subject} disabled={hasMessages} onChange={(e) => setSubject(e.target.checked)} />
          Messages have a subject line (emails)
          {hasMessages && <span className="text-xs">· fixed once it has messages</span>}
        </label>
        <div className="flex justify-end gap-1.5">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} disabled={busy || !name.trim()}>
            Save
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function Editor({ category, template, hasCurrent, onClose }: {
  category: MessageCategory;
  template?: TemplateWithUsage;
  hasCurrent: boolean;
  onClose: () => void;
}) {
  const act = useTemplateActions();
  const [name, setName] = useState(template?.name ?? "");
  const [subject, setSubject] = useState(template?.subject ?? "");
  const [body, setBody] = useState(template?.body ?? "");
  const [current, setCurrent] = useState(false);
  const email = category.has_subject;
  // A half-written message shouldn't vanish on Esc or a stray click outside.
  const dirty = name !== (template?.name ?? "") || subject !== (template?.subject ?? "") || body !== (template?.body ?? "");
  const missing = !name.trim() || !body.trim() || (email && !subject.trim());
  const busy = act.create.isPending || act.update.isPending;
  const catLabel = category.name;

  const save = async () => {
    if (busy || missing) return;
    try {
      if (template) await act.update.mutateAsync({ id: template.id, updated_at: template.updated_at, name, body, ...(email ? { subject } : {}) });
      else await act.create.mutateAsync({ category: category.key, name, body, ...(email ? { subject } : {}), ...(current ? { is_current: true } : {}) });
      onClose();
    } catch {
      // the mutation already showed the error toast
    }
  };

  return (
    <Modal open onClose={onClose} title={template ? `Edit ${catLabel.toLowerCase()}` : `New ${catLabel.toLowerCase()}`} width="max-w-2xl" dismissable={!dirty}>
      <div className="space-y-3 p-5">
        <div>
          <span className="label">Name (for you and Insights)</span>
          <input autoFocus className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="Short intro v2" maxLength={120} />
        </div>
        {email && (
          <div>
            <span className="label">Subject</span>
            <input className="field" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Quick question about {company}'s AI roadmap" maxLength={300} />
          </div>
        )}
        <div>
          <span className="label">Message</span>
          <textarea
            className="field min-h-48 resize-y leading-relaxed"
            rows={10}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && save()}
            placeholder={"Hi {first_name},\n\n…"}
            maxLength={10000}
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {!template && (
            <label className="flex items-center gap-2 text-[13px]">
              {/* With no current one in the category, the server makes the new variant current anyway. */}
              <input type="checkbox" checked={current || !hasCurrent} disabled={!hasCurrent} onChange={(e) => setCurrent(e.target.checked)} />
              {hasCurrent ? "Make it the current one" : "Becomes the current one (none is set)"}
            </label>
          )}
          <div className="ml-auto flex gap-1.5">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" onClick={save} disabled={busy || missing}>
              Save
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
