import type { ReactNode } from "react";
import { Bell, Bot, Inbox } from "lucide-react";
import type { ReminderRef, Summary } from "../lib/api";
import { ago, due, money } from "../lib/format";
import { labelOf, useMeta } from "../lib/meta";
import { useDrawer } from "../lib/hooks";
import { Chip, Fit, StagePill, YourMove, cx, pressable } from "./ui";

export const DUE_TONE = {
  overdue: "text-rose-600 dark:text-rose-400",
  today: "text-orange-600 dark:text-orange-300",
  soon: "text-fg",
  later: "text-muted",
};

/** A deal's next step: the owner's own (bell, coloured by how due it is) or, when they have none, an agent's
 *  follow-up (bot, muted: it's the agent's to do, and reaches Today only if missed). */
export function NextStep({ r, className }: { r: ReminderRef; className?: string }) {
  const d = due(r.due_at);
  return (
    <span
      className={cx("inline-flex items-center gap-1", r.for_agent ? "text-muted" : DUE_TONE[d.tone], className)}
      title={r.for_agent ? `${r.agent}'s follow-up: ${r.note}` : r.note || undefined}
    >
      {r.for_agent ? <Bot size={11} /> : <Bell size={11} />} {d.text}
    </span>
  );
}

/** One opportunity as a row: used on Today, Review and the list view. */
export function OppRow({ opp, right, meta: extra, showStage = true, showNext = true }: {
  opp: Summary;
  right?: ReactNode;
  meta?: ReactNode;
  showStage?: boolean;
  showNext?: boolean;
}) {
  const { data: meta } = useMeta();
  const drawer = useDrawer();
  const rem = showNext ? opp.next_reminder : null;
  return (
    <div
      className="group flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 transition outline-none hover:bg-panel-2 focus-visible:ring-2 focus-visible:ring-accent"
      {...pressable(() => drawer.open(opp.id))}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{opp.company}</span>
          {opp.waiting_on === "me" && opp.stage !== "won" && opp.stage !== "lost" && <YourMove />}
          {opp.needs_review && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" title="Changed by an agent — needs review" />}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted">
          {opp.title && <span className="max-w-[28ch] truncate">{opp.title}</span>}
          <Chip>{labelOf(meta?.channels, opp.channel)}</Chip>
          {opp.network !== "none" && <Chip title="Network">via {labelOf(meta?.networks, opp.network)}</Chip>}
          {opp.inbound && (
            <Chip title="The client reached out first">
              <Inbox size={11} /> inbound
            </Chip>
          )}
          {(opp.value || opp.budget) && <span>{opp.value ? money(opp.value) : opp.budget}</span>}
          {opp.fit && <Fit value={opp.fit} />}
          {extra}
          {/* phones: the stage and next step live here, the right-hand column is hidden */}
          {showStage && <StagePill stage={opp.stage} className="sm:hidden" />}
          {rem && <NextStep r={rem} className="text-xs sm:hidden" />}
        </div>
      </div>
      <div className="hidden shrink-0 flex-col items-end gap-1 sm:flex">
        {showStage && <StagePill stage={opp.stage} />}
        {rem ? (
          <NextStep r={rem} className="text-xs" />
        ) : (
          <span className="text-xs text-muted">{ago(opp.last_activity_at)}</span>
        )}
      </div>
      {right && (
        <div className="flex shrink-0 items-center gap-1" onClick={(e) => e.stopPropagation()}>
          {right}
        </div>
      )}
    </div>
  );
}

