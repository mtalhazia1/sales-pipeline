import { useQuery } from "@tanstack/react-query";
import { Bot, Check, CheckCheck, User as UserIcon } from "lucide-react";
import { useSearchParams } from "react-router";
import { api, type TimelineEvent } from "../lib/api";
import { ago } from "../lib/format";
import { useDrawer, useOppActions, useOpportunities } from "../lib/hooks";
import { OppRow } from "../components/OppRow";
import { PageHeader } from "../components/Shell";
import { eventTitle, useChangeLabels } from "../components/Drawer";
import { Button, Empty, PageLoading, Segmented, cx } from "../components/ui";

/** Agents do the data entry; this is where a human keeps an eye on them. */
export function Review() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "review" | "activity") || "review";
  return (
    <>
      <PageHeader title="Review" sub="What your agents added and changed — approve it or fix it.">
        <Segmented
          value={tab}
          onChange={(v) =>
            setParams((p) => {
              p.set("tab", v);
              return p;
            })
          }
          options={[
            { value: "review", label: "Needs review" },
            { value: "activity", label: "All activity" },
          ]}
        />
      </PageHeader>
      {tab === "review" ? <NeedsReview /> : <Activity />}
    </>
  );
}

function useFeed(actorType?: string) {
  return useQuery({
    queryKey: ["activity", actorType ?? "all"],
    queryFn: () => api.get<TimelineEvent[]>(`/activity?limit=200${actorType ? `&actor_type=${actorType}` : ""}`),
    refetchInterval: 30_000,
  });
}

function NeedsReview() {
  const { data: opps, isLoading } = useOpportunities({ needs_review: "true" });
  const { data: feed } = useFeed("agent");
  const act = useOppActions();
  const labels = useChangeLabels();
  if (isLoading || !opps) return <PageLoading />;
  if (!opps.length)
    return (
      <Empty icon={<CheckCheck size={28} />} title="Nothing to review">
        When an agent adds or changes something, it shows up here until you've looked at it.
      </Empty>
    );
  return (
    <>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[13px] text-muted">{opps.length} to review</span>
        <Button size="sm" onClick={() => act.reviewAll.mutate()}>
          <CheckCheck size={14} /> Approve all
        </Button>
      </div>
      <div className="space-y-2">
        {opps.map((o) => {
          const recent = (feed ?? []).filter((e) => e.opportunity_id === o.id && e.kind !== "reviewed").slice(0, 3);
          return (
            <div key={o.id} className="rounded-2xl border border-line bg-panel p-1.5">
              <OppRow
                opp={o}
                right={
                  <Button size="sm" variant="primary" onClick={() => act.review.mutate({ id: o.id })}>
                    <Check size={14} /> Looks good
                  </Button>
                }
              />
              {recent.length > 0 && (
                <ul className="mx-3 mb-2 space-y-1 border-l-2 border-accent/30 pl-3">
                  {recent.map((e) => (
                    <li key={e.id} className="text-[13px]">
                      <span className="mr-1.5 inline-flex items-center gap-1 text-accent">
                        <Bot size={12} />
                        {e.actor_name}
                      </span>
                      <span>{eventTitle(e, labels)}</span>
                      {e.body && !["updated", "reminder"].includes(e.kind) && <span className="text-muted"> — {e.body.slice(0, 140)}</span>}
                      <span className="ml-1.5 text-xs text-muted">{ago(e.occurred_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

function Activity() {
  const [who, setWho] = useSearchParams();
  const actor = who.get("who") || "";
  const { data: feed, isLoading } = useFeed(actor || undefined);
  const drawer = useDrawer();
  const labels = useChangeLabels();
  return (
    <>
      <div className="mb-3">
        <Segmented
          value={actor || "all"}
          onChange={(v) =>
            setWho((p) => {
              if (v === "all") p.delete("who");
              else p.set("who", v);
              return p;
            })
          }
          options={[
            { value: "all", label: "Everyone" },
            { value: "agent", label: <><Bot size={13} /> Agents</> },
            { value: "human", label: <><UserIcon size={13} /> People</> },
          ]}
        />
      </div>
      {isLoading || !feed ? (
        <PageLoading />
      ) : !feed.length ? (
        <Empty title="No activity yet" />
      ) : (
        <div className="rounded-2xl border border-line bg-panel p-1.5">
          {feed.map((e) => (
            <button key={e.id} onClick={() => drawer.open(e.opportunity_id)} className="flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left hover:bg-panel-2">
              <span className={cx("mt-0.5 shrink-0", e.actor_type === "agent" ? "text-accent" : "text-muted")}>
                {e.actor_type === "agent" ? <Bot size={16} /> : <UserIcon size={16} />}
              </span>
              <span className="min-w-0 flex-1 text-[13px]">
                <span className="font-medium">{e.company}</span>
                <span className="text-muted"> · {e.actor_name}</span>
                <span className="mt-0.5 block">{eventTitle(e, labels)}</span>
                {e.body && !["updated", "reminder"].includes(e.kind) && <span className="mt-0.5 block truncate text-muted">{e.body}</span>}
              </span>
              <span className="shrink-0 text-xs text-muted">{ago(e.occurred_at)}</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
