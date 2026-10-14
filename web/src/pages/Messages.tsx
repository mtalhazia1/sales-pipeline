import { useState } from "react";
import { Check, MessageSquarePlus, Pencil, Trash2 } from "lucide-react";
import type { MessageTemplate } from "../lib/api";
import { pct } from "../lib/format";
import { useTemplateActions, useTemplates } from "../lib/hooks";
import { useMeta } from "../lib/meta";
import { PageHeader } from "../components/Shell";
import { Button, Empty, Modal, PageError, PageLoading, cx } from "../components/ui";
import { useConfirm } from "../components/confirm";

const EMAIL = new Set(["cold_email", "warm_email"]);

/** First-contact message variants. Agents fetch each category's current one (MCP get_message_template)
 *  and send it word for word, filling only the {placeholders}. */
export function Messages() {
  const { data: meta } = useMeta();
  const { data: list, isLoading, error, refetch } = useTemplates();
  const [editing, setEditing] = useState<{ category: string; template?: MessageTemplate } | null>(null);

  return (
    <>
      <PageHeader
        title="Messages"
        sub={
          <>
            First-contact messages your agents send — the <span className="font-medium text-fg">current</span> one in each category. Replies are yours.
          </>
        }
      />
      <p className="mb-6 rounded-xl border border-line bg-panel-2/60 px-4 py-3 text-[13px] text-muted">
        Write placeholders like <code className="text-fg">{"{first_name}"}</code>, <code className="text-fg">{"{company}"}</code> or{" "}
        <code className="text-fg">{"{role}"}</code> — the agent fills them in and sends everything else word for word. Small tweaks: edit the
        variant. A different approach: add a new variant, so Insights can compare them.
      </p>
      {error && !list ? (
        <PageError error={error} onRetry={refetch} />
      ) : isLoading || !list || !meta ? (
        <PageLoading />
      ) : (
        <div className="space-y-8">
          {meta.template_categories.map((cat) => {
            const items = list.filter((t) => t.category === cat.value);
            return (
              <section key={cat.value}>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h2 className="font-semibold">{cat.label}</h2>
                  <Button size="sm" onClick={() => setEditing({ category: cat.value })}>
                    <MessageSquarePlus size={14} /> New variant
                  </Button>
                </div>
                {items.length ? (
                  <div className="space-y-2">
                    {items.map((t) => (
                      <TemplateCard key={t.id} t={t} onEdit={() => setEditing({ category: t.category, template: t })} />
                    ))}
                  </div>
                ) : (
                  <Empty title={`No ${cat.label.toLowerCase()} yet`}>Agents can't send one until you add it.</Empty>
                )}
              </section>
            );
          })}
        </div>
      )}
      {editing && <Editor key={editing.template?.id ?? editing.category} {...editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function TemplateCard({ t, onEdit }: { t: MessageTemplate; onEdit: () => void }) {
  const act = useTemplateActions();
  const confirm = useConfirm();
  const u = t.usage;
  return (
    <div className={cx("rounded-2xl border bg-panel p-4", t.is_current ? "border-emerald-500/50" : "border-line")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{t.name}</span>
        {t.is_current && (
          <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/12 px-1.5 py-0.5 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
            <Check size={12} /> Current
          </span>
        )}
        <span className="text-xs text-muted tabular-nums">
          {u.sent ? `Sent ${u.sent} · ${u.replied} replied (${pct(u.reply_rate)}) · ${u.calls} calls · ${u.won} won` : "Not sent yet"}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {!t.is_current && (
            <Button size="sm" variant="primary" disabled={act.update.isPending} onClick={() => act.update.mutate({ id: t.id, is_current: true })}>
              Use this
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onEdit} aria-label="Edit">
            <Pencil size={14} />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Delete"
            onClick={async () => {
              const ok = await confirm({
                title: `Delete "${t.name}"?`,
                body: u.sent
                  ? "Deals it was sent to keep its name, and Insights keeps its numbers."
                  : t.is_current
                    ? "Agents will have no message for this category until you pick another."
                    : undefined,
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
          <span className="text-muted">Subject:</span> {t.subject}
        </div>
      )}
      <p className="mt-2 rounded-lg bg-panel-2 px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap">{t.body}</p>
    </div>
  );
}

function Editor({ category, template, onClose }: { category: string; template?: MessageTemplate; onClose: () => void }) {
  const { data: meta } = useMeta();
  const act = useTemplateActions();
  const [name, setName] = useState(template?.name ?? "");
  const [subject, setSubject] = useState(template?.subject ?? "");
  const [body, setBody] = useState(template?.body ?? "");
  const [current, setCurrent] = useState(false);
  const email = EMAIL.has(category);
  const busy = act.create.isPending || act.update.isPending;
  const catLabel = meta?.template_categories.find((c) => c.value === category)?.label ?? category;

  const save = async () => {
    if (busy || !name.trim() || !body.trim()) return;
    try {
      if (template) await act.update.mutateAsync({ id: template.id, name, body, ...(email ? { subject } : {}) });
      else await act.create.mutateAsync({ category, name, body, ...(email ? { subject } : {}), ...(current ? { is_current: true } : {}) });
      onClose();
    } catch {
      // the mutation already showed the error toast
    }
  };

  return (
    <Modal open onClose={onClose} title={template ? `Edit ${catLabel.toLowerCase()}` : `New ${catLabel.toLowerCase()}`} width="max-w-2xl">
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
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {!template && (
            <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" checked={current} onChange={(e) => setCurrent(e.target.checked)} />
              Make it the current one
            </label>
          )}
          <div className="ml-auto flex gap-1.5">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" onClick={save} disabled={busy || !name.trim() || !body.trim()}>
              Save
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
