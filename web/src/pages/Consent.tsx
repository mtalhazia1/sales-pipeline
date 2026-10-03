import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { Bot, ShieldCheck } from "lucide-react";
import { api } from "../lib/api";
import { Logo } from "../components/Shell";
import { Button, Spinner } from "../components/ui";

/** The "allow this app?" step of the OAuth flow an MCP client (e.g. Claude) starts. */
export function Consent() {
  const [params] = useSearchParams();
  const id = params.get("request") ?? "";
  const { data, error, isLoading } = useQuery({
    queryKey: ["consent", id],
    queryFn: () => api.get<{ client_name: string; redirect_host: string; client_uri: string | null }>(`/oauth/requests/${encodeURIComponent(id)}`),
    retry: false,
  });
  const [busy, setBusy] = useState(false);
  const answer = async (allow: boolean) => {
    setBusy(true);
    const r = await api.post<{ redirect_to: string }>(`/oauth/requests/${encodeURIComponent(id)}`, { allow });
    location.assign(r.redirect_to);
  };

  return (
    <div className="flex min-h-dvh items-center justify-center p-4">
      <div className="anim-pop w-full max-w-md rounded-2xl border border-line bg-panel p-7 shadow-xl">
        <div className="mb-5 flex items-center gap-3">
          <Logo />
          <span className="text-muted">⟷</span>
          <span className="flex h-[26px] w-[26px] items-center justify-center rounded-lg bg-panel-2 text-accent">
            <Bot size={16} />
          </span>
        </div>
        {isLoading && <Spinner />}
        {error && <p className="text-[14px] text-muted">{(error as Error).message}</p>}
        {data && (
          <>
            <h1 className="text-lg font-semibold tracking-tight">Connect {data.client_name}?</h1>
            <p className="mt-2 text-[14px] text-muted">
              It will be able to read your pipeline and add or update opportunities, messages and reminders. Its changes show up in
              Review, and you can disconnect it any time in Settings.
            </p>
            <div className="mt-4 flex items-center gap-2 rounded-lg bg-panel-2 px-3 py-2 text-[13px] text-muted">
              <ShieldCheck size={15} /> Returns to <span className="font-medium text-fg">{data.redirect_host}</span>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="ghost" disabled={busy} onClick={() => answer(false)}>
                Deny
              </Button>
              <Button variant="primary" disabled={busy} onClick={() => answer(true)}>
                Allow
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
