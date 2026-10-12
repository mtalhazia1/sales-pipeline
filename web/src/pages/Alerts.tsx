import { BellOff, Check, CheckCheck, ExternalLink, Undo2 } from "lucide-react";
import { useSearchParams } from "react-router";
import type { AppNotification } from "../lib/api";
import { ago, hostOf, href } from "../lib/format";
import { useDrawer, useMarkRead, useNotifications } from "../lib/hooks";
import { PageHeader } from "../components/Shell";
import { AgentBadge, Button, Empty, PageError, PageLoading, Segmented, cx } from "../components/ui";

/** Things an agent decided need you (MCP notify_owner) — read them when you're free. */
export function Alerts() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "unread" | "all") || "unread";
  const { data: list, isLoading, error, refetch } = useNotifications(tab === "unread");
  const mark = useMarkRead();
  const unread = (list ?? []).filter((n) => !n.read_at);

  return (
    <>
      <PageHeader title="Alerts" sub="What your agents flagged for you to act on.">
        {unread.length > 1 && (
          <Button size="sm" disabled={mark.isPending} onClick={() => mark.mutate({ ids: unread.map((n) => n.id) })}>
            <CheckCheck size={14} /> Mark all read
          </Button>
        )}
        <Segmented
          value={tab}
          onChange={(v) =>
            setParams((p) => {
              p.set("tab", v);
              return p;
            })
          }
          options={[
            { value: "unread", label: "Unread" },
            { value: "all", label: "All" },
          ]}
        />
      </PageHeader>
      {error && !list ? (
        <PageError error={error} onRetry={refetch} />
      ) : isLoading || !list ? (
        <PageLoading />
      ) : !list.length ? (
        <Empty icon={<BellOff size={28} />} title={tab === "unread" ? "You're all caught up" : "No alerts yet"}>
          When an agent needs you to act or decide on something, it sends an alert here.
        </Empty>
      ) : (
        <div className="space-y-2">
          {list.map((n) => (
            <AlertCard key={n.id} n={n} busy={mark.isPending} onRead={(read) => mark.mutate({ ids: [n.id], read })} />
          ))}
        </div>
      )}
    </>
  );
}

function AlertCard({ n, busy, onRead }: { n: AppNotification; busy: boolean; onRead: (read: boolean) => void }) {
  const drawer = useDrawer();
  const read = !!n.read_at;
  return (
    <div className={cx("rounded-2xl border border-line bg-panel p-4", read && "opacity-60")}>
      <div className="flex items-start gap-3">
        <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", read ? "bg-transparent" : "bg-rose-500")} />
        <div className="min-w-0 flex-1">
          <div className="font-medium">{n.title}</div>
          {n.message && <p className="mt-1 text-[14px] whitespace-pre-wrap text-muted">{n.message}</p>}
          <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-muted">
            <AgentBadge name={n.created_by} />
            <span>{ago(n.created_at)}</span>
            {n.opportunity && (
              <button onClick={() => drawer.open(n.opportunity!.id)} className="rounded-md bg-panel-2 px-1.5 py-0.5 font-medium text-fg hover:bg-line/70">
                {n.opportunity.company}
                {n.opportunity.title && <span className="text-muted"> · {n.opportunity.title}</span>}
              </button>
            )}
            {n.url && (
              <a href={href(n.url)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                <ExternalLink size={12} /> {hostOf(n.url)}
              </a>
            )}
          </div>
        </div>
        <Button size="sm" variant={read ? "ghost" : "primary"} disabled={busy} onClick={() => onRead(!read)}>
          {read ? <><Undo2 size={14} /> Unread</> : <><Check size={14} /> Mark read</>}
        </Button>
      </div>
    </div>
  );
}
