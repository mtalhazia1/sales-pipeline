import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import {
  api,
  type Agenda,
  type AgentRun,
  type AppNotification,
  type Detail,
  type MessageCategory,
  type MessageTemplate,
  type Reminder,
  type StateChangeResult,
  type StateView,
  type TemplateWithUsage,
  type Summary,
} from "./api";
import { useToast } from "../components/ui";

export function useAgenda() {
  return useQuery({ queryKey: ["agenda"], queryFn: () => api.get<Agenda>("/agenda"), refetchInterval: 60_000 });
}

export function useOpportunities(params: Record<string, string | undefined> = {}, enabled = true) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString();
  return useQuery({
    queryKey: ["opps", qs],
    queryFn: () => api.get<Summary[]>(`/opportunities${qs ? `?${qs}` : ""}`),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData, // changing a filter keeps the old results up instead of a spinner
    enabled,
  });
}

export function useOpportunity(id: number | null) {
  return useQuery({
    queryKey: ["opp", id],
    queryFn: () => api.get<Detail>(`/opportunities/${id}`),
    enabled: id != null,
  });
}

/** Everything that changes an opportunity — each invalidates every view that could show it. */
export function useOppActions() {
  const qc = useQueryClient();
  const toast = useToast();
  const refresh = (id?: number) => {
    qc.invalidateQueries({ queryKey: ["opps"] });
    qc.invalidateQueries({ queryKey: ["agenda"] });
    qc.invalidateQueries({ queryKey: ["activity"] });
    qc.invalidateQueries({ queryKey: ["stats"] });
    qc.invalidateQueries({ queryKey: ["templates"] }); // per-variant reply counts
    if (id != null) qc.invalidateQueries({ queryKey: ["opp", id] });
  };
  const m = <A, R>(fn: (a: A) => Promise<R>, done?: string | ((a: A) => string | undefined)) =>
    useMutation({
      mutationFn: fn,
      onSuccess: (_d, a) => {
        const id = (a as { id?: number })?.id;
        refresh(id);
        const msg = typeof done === "function" ? done(a) : done;
        if (msg) toast.ok(msg);
      },
      onError: (e) => toast.error(e),
    });

  return {
    update: m(({ id, ...patch }: { id: number } & Record<string, unknown>) => api.patch<Detail>(`/opportunities/${id}`, patch)),
    log: m(
      ({ id, kind, body, occurred_at }: { id: number; kind: string; body?: string; occurred_at?: string }) =>
        api.post<Detail>(`/opportunities/${id}/activities`, { kind, body, occurred_at }),
      "Logged",
    ),
    remind: m(
      ({ id, due_at, note }: { id: number; due_at: string; note?: string }) =>
        api.post<Reminder>(`/opportunities/${id}/reminders`, { due_at, note: note ?? "" }),
      "Reminder set",
    ),
    reminder: m(({ reminderId, ...patch }: { id?: number; reminderId: number; done?: boolean; due_at?: string; note?: string }) =>
      api.patch<Reminder>(`/reminders/${reminderId}`, patch),
    ),
    deleteReminder: m(({ reminderId }: { id?: number; reminderId: number }) => api.del(`/reminders/${reminderId}`)),
    review: m(({ id }: { id: number }) => api.post(`/opportunities/${id}/review`), "Marked reviewed"),
    reviewAll: m(({ ids }: { ids: number[] }) => api.post<{ reviewed: number }>("/review/approve-all", { ids }), "All marked reviewed"),
    remove: m(({ id }: { id: number }) => api.del(`/opportunities/${id}`), "Deleted"),
    refresh,
  };
}

export function useNotifications(unreadOnly: boolean) {
  return useQuery({
    queryKey: ["notifications", unreadOnly],
    queryFn: () => api.get<AppNotification[]>(`/notifications${unreadOnly ? "?unread=true" : ""}`),
    refetchInterval: 60_000,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ ids, read = true }: { ids: number[]; read?: boolean }) => api.post("/notifications/read", { ids, read }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
      qc.invalidateQueries({ queryKey: ["agenda"] });
    },
    onError: (e) => toast.error(e),
  });
}

/** The opportunity drawer lives in the URL (?o=12) so it opens over any page and survives reloads. */
export function useDrawer() {
  const [params, setParams] = useSearchParams();
  const id = params.get("o") ? Number(params.get("o")) : null;
  return {
    id,
    open: (oid: number) =>
      setParams((p) => {
        p.set("o", String(oid));
        return p;
      }),
    // Closing replaces the history entry, so Back after closing doesn't reopen the drawer.
    close: () =>
      setParams(
        (p) => {
          p.delete("o");
          return p;
        },
        { replace: true },
      ),
  };
}

export function useTemplates(includeArchived = false) {
  return useQuery({
    queryKey: ["templates", includeArchived],
    queryFn: () => api.get<TemplateWithUsage[]>(`/templates${includeArchived ? "?include_archived=true" : ""}`),
  });
}

export function useTemplateCategories(includeArchived = false) {
  return useQuery({
    queryKey: ["template-categories", includeArchived],
    queryFn: () => api.get<MessageCategory[]>(`/template-categories${includeArchived ? "?include_archived=true" : ""}`),
  });
}

/** Create / edit / pick current / delete message variants and their categories. Saving one unchanged marks it reviewed. */
export function useTemplateActions() {
  const qc = useQueryClient();
  const toast = useToast();
  const m = <A, R>(fn: (a: A) => Promise<R>, done?: string) =>
    useMutation({
      mutationFn: fn,
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: ["templates"] });
        qc.invalidateQueries({ queryKey: ["template-categories"] });
        qc.invalidateQueries({ queryKey: ["stats"] }); // Insights labels variants by name
        qc.invalidateQueries({ queryKey: ["agenda"] }); // the Messages review badge
        qc.invalidateQueries({ queryKey: ["opp"] }); // timelines name the template a message was based on
        qc.invalidateQueries({ queryKey: ["activity"] });
        if (done) toast.ok(done);
      },
      onError: (e) => {
        toast.error(e);
        // A refused stale save (409): show what the agent changed instead of the old text.
        qc.invalidateQueries({ queryKey: ["templates"] });
        qc.invalidateQueries({ queryKey: ["template-categories"] });
      },
    });
  return {
    create: m((body: { category: string; name: string; subject?: string; body: string; is_current?: boolean }) => api.post<MessageTemplate>("/templates", body), "Message added"),
    // `updated_at` is the version on screen: the server refuses the save if an agent changed it since.
    update: m(({ id, ...patch }: { id: number; updated_at: string } & Partial<Pick<MessageTemplate, "name" | "subject" | "body" | "is_current">>) =>
      api.patch<MessageTemplate>(`/templates/${id}`, patch),
    ),
    remove: m(({ id }: { id: number }) => api.del(`/templates/${id}`), "Message deleted"),
    createCategory: m((body: { name: string; purpose?: string; has_subject: boolean }) => api.post<MessageCategory>("/template-categories", body), "Category added"),
    updateCategory: m(({ key, ...patch }: { key: string; updated_at: string } & Partial<Pick<MessageCategory, "name" | "purpose" | "has_subject">>) =>
      api.patch<MessageCategory>(`/template-categories/${key}`, patch),
    ),
    removeCategory: m(({ key }: { key: string }) => api.del(`/template-categories/${key}`), "Category deleted"),
  };
}

const query = (params: Record<string, string | number | undefined>) =>
  new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])).toString();

/** Agent state rows (filtered) plus namespaces, sections in use and current counters. */
export function useAgentState(params: { ns?: string; section?: string; q?: string; limit?: number }) {
  const qs = query(params);
  return useQuery({
    queryKey: ["state", qs],
    queryFn: () => api.get<StateView>(`/state${qs ? `?${qs}` : ""}`),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });
}

export function useRuns(params: { ns?: string; status?: string; limit?: number }) {
  const qs = query(params);
  return useQuery({
    queryKey: ["runs", qs],
    queryFn: () => api.get<AgentRun[]>(`/state/runs${qs ? `?${qs}` : ""}`),
    refetchInterval: 60_000,
    placeholderData: keepPreviousData,
  });
}

/** due / expires: omitted = unchanged, null = cleared. */
export type StateChange = {
  ns: string;
  section: string;
  key: string;
  value?: unknown;
  op?: "set" | "delete";
  due?: string | null;
  expires?: string | null;
  locked?: boolean;
};

/** Owner edits to agent state. The server applies or rejects each change; a rejection becomes the error toast. */
export function useStateActions() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: async ({ ns, ...change }: StateChange) => {
      const r = await api.post<StateChangeResult>("/state", { ns, changes: [change] });
      if (r.rejected?.length) throw new Error(r.rejected[0].reason);
      return r;
    },
    onSuccess: (_r, c) => {
      qc.invalidateQueries({ queryKey: ["state"] });
      toast.ok(c.op === "delete" ? "Row deleted" : "Saved");
    },
    onError: (e) => toast.error(e),
  });
}

/** Retire an agent: delete everything in its namespace (rows, counters, seen ids, runs). */
export function useForgetNamespace() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (ns: string) => api.del<{ deleted: number }>(`/state/namespaces/${encodeURIComponent(ns)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["state"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      toast.ok("Namespace forgotten");
    },
    onError: (e) => toast.error(e),
  });
}
