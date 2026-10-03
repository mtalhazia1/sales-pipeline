import type { ReactNode } from "react";
import { Bell, Inbox } from "lucide-react";
import type { Summary } from "../lib/api";
import { ago, due, money } from "../lib/format";
import { labelOf, useMeta } from "../lib/meta";
import { useDrawer } from "../lib/hooks";
import { Chip, Fit, StagePill, YourMove, cx } from "./ui";

export const DUE_TONE = {
  overdue: "text-rose-600 dark:text-rose-400",
  today: "text-orange-600 dark:text-orange-300",
  soon: "text-fg",
  later: "text-muted",
};

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
  const rem = showNext && opp.next_reminder ? due(opp.next_reminder.due_at) : null;
  return (
    <div
      className="group flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 transition hover:bg-panel-2"
      onClick={() => drawer.open(opp.id)}
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
        </div>
      </div>
      <div className="hidden shrink-0 flex-col items-end gap-1 sm:flex">
        {showStage && <StagePill stage={opp.stage} />}
        {rem ? (
          <span className={cx("inline-flex items-center gap-1 text-xs", DUE_TONE[rem.tone])}>
            <Bell size={11} /> {rem.text}
          </span>
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

