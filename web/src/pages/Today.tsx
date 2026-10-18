import type { ReactNode } from "react";
import { Bell, BellRing, Bot, Check, Clock, PartyPopper, Send, Sparkles, X } from "lucide-react";
import { useNavigate } from "react-router";
import type { AgendaReminder, Summary } from "../lib/api";
import { due, inDays, snoozed } from "../lib/format";
import { useAgenda, useOppActions } from "../lib/hooks";
import { OppRow, DUE_TONE } from "../components/OppRow";
import { PageHeader } from "../components/Shell";
import { Button, Empty, PageError, PageLoading, cx, useToast } from "../components/ui";

export function Today() {
  const { data: a, isLoading, error, refetch } = useAgenda();
  const act = useOppActions();
  const toast = useToast();
  const nav = useNavigate();
  if (error && !a) return <PageError error={error} onRetry={refetch} />;
  if (isLoading || !a) return <PageLoading />;
  const busy = act.update.isPending || act.log.isPending || act.remind.isPending;

  // Triage is one click, so every outcome says what happened and can be taken back.
  const move = async (o: Summary, patch: Record<string, unknown>, said: string, followUpDays?: number) => {
    try {
      await act.update.mutateAsync({ id: o.id, ...patch });
      const r = followUpDays ? await act.remind.mutateAsync({ id: o.id, due_at: inDays(followUpDays), note: "Follow up if no reply" }) : null;
      toast.ok(said, {
        label: "Undo",
        run: () => {
          act.update.mutate({ id: o.id, stage: o.stage });
          if (r) act.deleteReminder.mutate({ id: o.id, reminderId: r.id });
        },
      });
    } catch {
      // the mutation already showed the error
    }
  };

  const total = a.due_reminders.length + a.your_move.length + a.gone_quiet.length;
  const date = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  const hour = new Date().getHours();
  const hello = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  return (
    <>
      <PageHeader title={hello} sub={`${date} · ${total ? `${total} thing${total > 1 ? "s" : ""} need you` : "nothing urgent"}`}>
        {a.unread_notifications > 0 && (
          <Button size="sm" onClick={() => nav("/alerts")}>
            <BellRing size={14} className="text-rose-500" /> {a.unread_notifications} unread alert{a.unread_notifications > 1 ? "s" : ""}
          </Button>
        )}
        {a.needs_review > 0 && (
          <Button size="sm" onClick={() => nav("/review")}>
            <Sparkles size={14} className="text-accent" /> {a.needs_review} agent update{a.needs_review > 1 ? "s" : ""} to review
          </Button>
        )}
      </PageHeader>

      <div className="space-y-6">
        {a.due_reminders.length > 0 && (
          <Block title="Due" icon={<Bell size={15} />} count={a.due_reminders.length}>
            {a.due_reminders.map((r) => (
              <ReminderRow key={r.id} r={r} />
            ))}
          </Block>
        )}

        {a.your_move.length > 0 && (
          <Block title="Your move" hint="the client is waiting on you" icon={<Send size={15} />} count={a.your_move.length} accent="text-orange-500">
            {a.your_move.map((o) => (
              <OppRow
                key={o.id}
                opp={o}
                right={
                  <Button size="sm" disabled={busy} onClick={() => act.log.mutate({ id: o.id, kind: "my_message", body: "Replied" })} title="Mark that you replied — it becomes their move">
                    <Check size={14} /> I replied
                  </Button>
                }
              />
            ))}
          </Block>
        )}

        {a.gone_quiet.length > 0 && (
          <Block title="Gone quiet" hint="no next step scheduled — follow up or let go" icon={<Clock size={15} />} count={a.gone_quiet.length}>
            {a.gone_quiet.map((o) => (
              <OppRow
                key={o.id}
                opp={o}
                meta={<span className="text-rose-600/80 dark:text-rose-300/80">{o.idle_days}d silent</span>}
                right={
                  <>
                    <Button size="sm" disabled={busy} onClick={() => act.remind.mutate({ id: o.id, due_at: inDays(0), note: "Send a follow-up" })} title="Add a follow-up for today">
                      Follow up
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => move(o, { stage: "lost", lost_reason: "no_response" }, `${o.company} marked lost — no response`)}
                      title="Let it go — mark lost, no response"
                      aria-label="Mark lost, no response"
                    >
                      <X size={14} />
                    </Button>
                  </>
                }
              />
            ))}
          </Block>
        )}

        {total === 0 && (
          <Empty icon={<PartyPopper size={28} />} title="All caught up">
            No reminders due, nobody waiting on you. A good time to send a few new applications.
          </Empty>
        )}

        {a.new_leads.length > 0 && (
          <Block title="New leads" hint="apply or pass" icon={<Sparkles size={15} />} count={a.new_leads_total} accent="text-accent">
            {a.new_leads.slice(0, 10).map((o) => (
              <OppRow
                key={o.id}
                opp={o}
                showStage={false}
                right={
                  <>
                    <Button
                      size="sm"
                      disabled={busy}
                      onClick={() => move(o, { stage: o.channel === "toptal" ? "matcher" : "applied" }, `Applied to ${o.company} — follow-up in 3 days`, 3)}
                      title="I applied (adds a 3-day follow-up)"
                    >
                      <Check size={14} /> Applied
                    </Button>
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => move(o, { stage: "lost", lost_reason: "declined" }, `Passed on ${o.company}`)} title="Pass on this one">
                      Pass
                    </Button>
                  </>
                }
              />
            ))}
            {a.new_leads_total > 10 && (
              <button className="px-3 py-2 text-[13px] text-muted hover:text-fg" onClick={() => nav("/pipeline?stage=lead&view=list")}>
                See all {a.new_leads_total} leads →
              </button>
            )}
          </Block>
        )}

        {a.upcoming.length > 0 && (
          <Block title="Coming up" hint="next 7 days" icon={<Clock size={15} />} muted>
            {a.upcoming.map((r) => (
              <ReminderRow key={r.id} r={r} />
            ))}
          </Block>
        )}
      </div>
    </>
  );
}

function Block({ title, hint, icon, count, accent, muted, children }: {
  title: string;
  hint?: string;
  icon: ReactNode;
  count?: number;
  accent?: string;
  muted?: boolean;
  children: ReactNode;
}) {
  return (
    <section className={cx("rounded-2xl border border-line bg-panel p-2", muted && "opacity-90")}>
      <div className="flex items-center gap-2 px-3 pt-2 pb-1.5">
        <span className={cx("text-muted", accent)}>{icon}</span>
        <h2 className="font-semibold">{title}</h2>
        {count != null && <span className="text-[13px] text-muted">{count}</span>}
        {hint && <span className="hidden text-[13px] text-muted sm:inline">· {hint}</span>}
      </div>
      <div>{children}</div>
    </section>
  );
}

function ReminderRow({ r }: { r: AgendaReminder }) {
  const act = useOppActions();
  const toast = useToast();
  const d = due(r.due_at);
  const busy = act.reminder.isPending;
  return (
    <OppRow
      opp={r.opportunity}
      showNext={false}
      meta={
        <span className={cx("inline-flex items-center gap-1 font-medium", DUE_TONE[d.tone])}>
          {r.for_agent ? <Bot size={12} /> : <Bell size={12} />} {r.note || "Reminder"} · {d.text}
          {r.for_agent && <span className="font-normal text-muted">· {r.created_by} missed this</span>}
        </span>
      }
      right={
        <>
          <Button
            size="sm"
            disabled={busy}
            onClick={() =>
              act.reminder.mutate(
                { id: r.opportunity_id, reminderId: r.id, done: true },
                { onSuccess: () => toast.ok("Done", { label: "Undo", run: () => act.reminder.mutate({ id: r.opportunity_id, reminderId: r.id, done: false }) }) },
              )
            }
            title="Done"
          >
            <Check size={14} /> Done
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => act.reminder.mutate({ id: r.opportunity_id, reminderId: r.id, due_at: snoozed(r.due_at) })} title="Push back a day">
            +1d
          </Button>
        </>
      }
    />
  );
}
