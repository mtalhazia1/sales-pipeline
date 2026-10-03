import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { api, type Agenda, type Detail, type Reminder, type Summary } from "./api";
import { useToast } from "../components/ui";

export function useAgenda() {
  return useQuery({ queryKey: ["agenda"], queryFn: () => api.get<Agenda>("/agenda"), refetchInterval: 60_000 });
}

export function useOpportunities(params: Record<string, string | undefined> = {}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString();
  return useQuery({
    queryKey: ["opps", qs],
    queryFn: () => api.get<Summary[]>(`/opportunities${qs ? `?${qs}` : ""}`),
    refetchInterval: 60_000,
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
    if (id != null) qc.invalidateQueries({ queryKey: ["opp", id] });
  };
  const m = <A,>(fn: (a: A) => Promise<unknown>, done?: string | ((a: A) => string | undefined)) =>
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
    reviewAll: m((_: void) => api.post<{ reviewed: number }>("/review/approve-all"), "All marked reviewed"),
    remove: m(({ id }: { id: number }) => api.del(`/opportunities/${id}`), "Deleted"),
    refresh,
  };
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
    close: () =>
      setParams((p) => {
        p.delete("o");
        return p;
      }),
  };
}
