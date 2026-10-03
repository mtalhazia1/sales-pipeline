import { useEffect, useState } from "react";
import { Bell } from "lucide-react";
import { api, type Summary } from "../lib/api";
import { inDays } from "../lib/format";
import { channelFromUrl, useMeta } from "../lib/meta";
import { useDrawer, useOppActions } from "../lib/hooks";
import { Button, Modal, Segmented, Select, useToast } from "./ui";

const EMPTY = { application_url: "", company: "", title: "", kind: "job", channel: "", network: "none", stage: "applied" };

/** Fast manual add: paste the link, type the company, Enter. Everything else can wait. */
export function QuickAdd({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: meta } = useMeta();
  const act = useOppActions();
  const drawer = useDrawer();
  const toast = useToast();
  const [f, setF] = useState(EMPTY);
  const [channelTouched, setChannelTouched] = useState(false);
  const [followUp, setFollowUp] = useState(true);
  const [days, setDays] = useState(3);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setF(EMPTY);
      setChannelTouched(false);
      setFollowUp(true);
    }
  }, [open]);

  const set = (k: keyof typeof EMPTY, v: string) => setF((p) => ({ ...p, [k]: v }));
  const onUrl = (url: string) => {
    set("application_url", url);
    const ch = channelFromUrl(url, meta);
    if (ch && !channelTouched) set("channel", ch);
  };
  const channel = f.channel || "linkedin";
  const stages = (meta?.stages ?? []).filter((s) => s.value !== "matcher" || channel === "toptal");
  const remind = followUp && ["applied", "matcher", "proposal"].includes(f.stage);

  const submit = async () => {
    if (!f.company.trim() || busy) return;
    setBusy(true);
    try {
      const body: Record<string, unknown> = { ...f, channel };
      for (const k of ["application_url", "title"]) if (!body[k]) delete body[k];
      if (remind) {
        body.reminder_at = inDays(days);
        body.reminder_note = "Follow up if no reply";
      }
      const res = await api.post<{ created: boolean; opportunity: Summary }>("/opportunities", body);
      act.refresh(res.opportunity.id);
      onClose();
      if (res.created) toast.ok(`Added ${res.opportunity.company}`, { label: "Open", run: () => drawer.open(res.opportunity.id) });
      else {
        toast.ok("Already in your pipeline — opened it");
        drawer.open(res.opportunity.id);
      }
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="New opportunity">
      <form
        className="space-y-3 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div>
          <label className="label">Link to the job / project</label>
          <input autoFocus className="field" value={f.application_url} onChange={(e) => onUrl(e.target.value)} placeholder="Paste a URL — channel fills itself" />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="label">Client / company *</label>
            <input className="field" value={f.company} onChange={(e) => set("company", e.target.value)} placeholder="Acme AI" required />
          </div>
          <div>
            <label className="label">Title</label>
            <input className="field" value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="Senior AI engineer" />
          </div>
          <div>
            <label className="label">Channel</label>
            <Select
              value={channel}
              onChange={(v) => {
                setChannelTouched(true);
                set("channel", v);
              }}
              options={meta?.channels ?? []}
            />
          </div>
          <div>
            <label className="label">Network</label>
            <Select value={f.network} onChange={(v) => set("network", v)} options={meta?.networks ?? []} />
          </div>
          <div>
            <label className="label">Stage</label>
            <Select value={f.stage} onChange={(v) => set("stage", v)} options={stages} />
          </div>
          <div>
            <label className="label">Type</label>
            <Segmented value={f.kind} onChange={(v) => set("kind", v)} options={meta?.kinds ?? []} />
          </div>
        </div>
        {["applied", "matcher", "proposal"].includes(f.stage) && (
          <label className="flex cursor-pointer items-center gap-2 rounded-lg bg-panel-2 px-3 py-2 text-[13px]">
            <input type="checkbox" checked={followUp} onChange={(e) => setFollowUp(e.target.checked)} className="accent-[var(--accent)]" />
            <Bell size={14} className="text-muted" />
            Remind me to follow up in
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded bg-transparent font-medium">
              {[1, 2, 3, 5, 7, 14].map((d) => (
                <option key={d} value={d}>
                  {d} day{d > 1 ? "s" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={!f.company.trim() || busy}>
            Add
          </Button>
        </div>
      </form>
    </Modal>
  );
}
