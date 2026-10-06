import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Copy, Globe, KeyRound, LogOut, Plug, Trash2 } from "lucide-react";
import { api, type Agents, type User } from "../lib/api";
import { ago } from "../lib/format";
import { useMeta } from "../lib/meta";
import { PageHeader } from "../components/Shell";
import { useCopy } from "../components/Drawer";
import { useConfirm } from "../components/confirm";
import { Button, Modal, Select, useToast } from "../components/ui";

export function Settings() {
  return (
    <>
      <PageHeader title="Settings" />
      <div className="space-y-6">
        <ConnectAgents />
        <Workspace />
        <Account />
      </div>
    </>
  );
}

function Card({ icon, title, sub, children }: { icon: ReactNode; title: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-5">
      <div className="mb-4 flex items-start gap-3">
        <span className="mt-0.5 text-muted">{icon}</span>
        <div>
          <h2 className="font-semibold">{title}</h2>
          {sub && <div className="mt-0.5 text-[13px] text-muted">{sub}</div>}
        </div>
      </div>
      {children}
    </section>
  );
}

function CopyLine({ text, label }: { text: string; label?: string }) {
  const copy = useCopy();
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-panel-2 py-1 pr-1 pl-3">
      <code className="flex-1 overflow-x-auto font-mono text-[12.5px] whitespace-nowrap scroll-thin">{text}</code>
      <Button size="sm" variant="ghost" onClick={() => copy(text, label ?? "Copied")} title="Copy">
        <Copy size={14} />
      </Button>
    </div>
  );
}

function ConnectAgents() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const { data } = useQuery({ queryKey: ["agents"], queryFn: () => api.get<Agents>("/agents") });
  const [name, setName] = useState("");
  const [created, setCreated] = useState<{ name: string; token: string } | null>(null);
  const create = useMutation({
    mutationFn: () => api.post<{ id: number; name: string; token: string }>("/agents/keys", { name }),
    onSuccess: (k) => {
      setCreated(k);
      setName("");
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: toast.error,
  });
  const revoke = useMutation({
    mutationFn: (path: string) => api.del(path),
    onSuccess: () => {
      toast.ok("Access removed");
      qc.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: toast.error,
  });
  const url = data?.mcp_url ?? "";

  return (
    <Card icon={<Plug size={18} />} title="Connect agents" sub="Agents add and update opportunities through MCP. Everything they change lands in Review.">
      <div className="space-y-5">
        <div>
          <div className="label">MCP server URL</div>
          <CopyLine text={url} label="MCP URL copied" />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-line p-4">
            <div className="mb-1 font-medium">Claude (web, desktop, Cowork)</div>
            <ol className="list-decimal space-y-1 pl-4 text-[13px] text-muted">
              <li>Settings → Connectors → Add custom connector</li>
              <li>Paste the URL above, click Add</li>
              <li>Approve on the screen that opens here</li>
            </ol>
          </div>
          <div className="rounded-xl border border-line p-4">
            <div className="mb-1 font-medium">Claude Code</div>
            <p className="mb-2 text-[13px] text-muted">Run once, then <code>/mcp</code> to sign in:</p>
            <CopyLine text={`claude mcp add --transport http --scope user sales ${url}`} />
          </div>
        </div>

        <div>
          <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
            <div>
              <div className="font-medium">API keys</div>
              <div className="text-[13px] text-muted">For headless agents, scripts and automations — sent as <code>Authorization: Bearer …</code>.</div>
            </div>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim()) create.mutate();
              }}
            >
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Agent name, e.g. Upwork scout" className="field h-9 w-56" />
              <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
                <KeyRound size={14} /> Create
              </Button>
            </form>
          </div>
          <List
            empty="No keys yet."
            rows={(data?.api_keys ?? []).map((k) => ({
              key: `k${k.id}`,
              title: k.name,
              sub: `${k.prefix}… · created ${ago(k.created_at)} · ${k.last_used_at ? `used ${ago(k.last_used_at)}` : "never used"}`,
              onRemove: async () =>
                (await confirm({ title: `Revoke “${k.name}”?`, body: "Anything using this key stops working immediately.", confirm: "Revoke", danger: true })) &&
                revoke.mutate(`/agents/keys/${k.id}`),
            }))}
          />
        </div>

        <div>
          <div className="mb-2 font-medium">Connected apps</div>
          <List
            empty="No apps connected yet — add the connector in Claude to see it here."
            rows={(data?.apps ?? []).map((a) => ({
              key: a.client_id,
              title: a.name,
              sub: `connected ${ago(a.connected_at)}${a.last_used_at ? ` · used ${ago(a.last_used_at)}` : ""}`,
              onRemove: async () =>
                (await confirm({ title: `Disconnect ${a.name}?`, body: "It will need to be approved again to reconnect.", confirm: "Disconnect", danger: true })) &&
                revoke.mutate(`/agents/apps/${encodeURIComponent(a.client_id)}`),
            }))}
          />
        </div>
      </div>

      {/* Not dismissable by a stray click or Esc: the key is shown exactly once. */}
      <Modal open={!!created} onClose={() => setCreated(null)} title={`Key for “${created?.name}”`} dismissable={false}>
        <div className="space-y-3 p-5">
          <p className="text-[13px] text-muted">Copy it now — it won't be shown again.</p>
          <CopyLine text={created?.token ?? ""} label="Key copied" />
          <div className="label pt-2">Claude Code with this key</div>
          <CopyLine text={`claude mcp add --transport http --scope user sales ${url} --header "Authorization: Bearer ${created?.token}"`} />
          <div className="flex justify-end pt-1">
            <Button variant="primary" onClick={() => setCreated(null)}>
              Done
            </Button>
          </div>
        </div>
      </Modal>
    </Card>
  );
}

function List({ rows, empty }: { rows: { key: string; title: string; sub: string; onRemove: () => void }[]; empty: string }) {
  if (!rows.length) return <div className="rounded-xl border border-dashed border-line px-4 py-3 text-[13px] text-muted">{empty}</div>;
  return (
    <div className="divide-y divide-line rounded-xl border border-line">
      {rows.map((r) => (
        <div key={r.key} className="flex items-center gap-3 px-4 py-2.5">
          <Bot size={16} className="text-accent" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">{r.title}</div>
            <div className="truncate text-xs text-muted">{r.sub}</div>
          </div>
          <Button size="sm" variant="ghost" onClick={r.onRemove} title="Remove access">
            <Trash2 size={14} />
          </Button>
        </div>
      ))}
    </div>
  );
}

function Workspace() {
  const { data: meta } = useMeta();
  const qc = useQueryClient();
  const toast = useToast();
  const zones = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone") ?? [];
  const save = useMutation({
    mutationFn: (timezone: string) => api.patch("/settings", { timezone }),
    onSuccess: () => {
      toast.ok("Timezone saved");
      qc.invalidateQueries();
    },
    onError: toast.error,
  });
  if (!meta) return null;
  // Chrome's list has no plain "UTC"; offer it, and keep the current zone even if the list lacks it.
  const all = ["UTC", ...zones.filter((z) => z !== "UTC")];
  const options = (all.includes(meta.timezone) ? all : [meta.timezone, ...all]).map((z) => ({ value: z, label: z.replace(/_/g, " ") }));
  return (
    <Card icon={<Globe size={18} />} title="Timezone" sub="What “today” means for reminders and the agenda — for you and your agents.">
      <Select className="max-w-xs" value={meta.timezone} onChange={(v) => save.mutate(v)} options={options} />
    </Card>
  );
}

function Account() {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: () => api.get<User>("/auth/me") });
  const toast = useToast();
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const change = useMutation({
    mutationFn: () => api.post("/auth/password", { current: cur, new: next }),
    onSuccess: () => {
      toast.ok("Password changed");
      setCur("");
      setNext("");
    },
    onError: toast.error,
  });
  return (
    <Card icon={<KeyRound size={18} />} title="Account" sub={me ? `${me.name} · ${me.email}` : undefined}>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          change.mutate();
        }}
      >
        <div>
          <label className="label">Current password</label>
          <input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} className="field h-9 w-52" />
        </div>
        <div>
          <label className="label">New password (10+ characters)</label>
          <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} className="field h-9 w-52" />
        </div>
        <Button type="submit" disabled={!cur || next.length < 10 || change.isPending}>
          Change password
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="ml-auto"
          onClick={async () => {
            try {
              await api.post("/auth/logout");
              location.assign("/login");
            } catch (e) {
              toast.error(e);
            }
          }}
        >
          <LogOut size={14} /> Log out
        </Button>
      </form>
    </Card>
  );
}
