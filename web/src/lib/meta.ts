import { useQuery } from "@tanstack/react-query";
import { api, type Meta, type Option } from "./api";

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/meta"), staleTime: Infinity });
}

export function labelOf(options: Option[] | undefined, value: string | null | undefined): string {
  if (!value) return "";
  return options?.find((o) => o.value === value)?.label ?? value;
}

// Stage colours — dot + soft pill. Ordered like the pipeline, cool → warm → done.
export const STAGE_STYLE: Record<string, { dot: string; pill: string }> = {
  lead: { dot: "bg-zinc-400", pill: "bg-zinc-500/10 text-zinc-600 dark:text-zinc-300" },
  matcher: { dot: "bg-amber-400", pill: "bg-amber-500/12 text-amber-700 dark:text-amber-300" },
  applied: { dot: "bg-sky-400", pill: "bg-sky-500/12 text-sky-700 dark:text-sky-300" },
  replied: { dot: "bg-violet-400", pill: "bg-violet-500/12 text-violet-700 dark:text-violet-300" },
  call: { dot: "bg-indigo-400", pill: "bg-indigo-500/12 text-indigo-700 dark:text-indigo-300" },
  proposal: { dot: "bg-fuchsia-400", pill: "bg-fuchsia-500/12 text-fuchsia-700 dark:text-fuchsia-300" },
  won: { dot: "bg-emerald-400", pill: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300" },
  lost: { dot: "bg-rose-400", pill: "bg-rose-500/10 text-rose-700 dark:text-rose-300" },
};

export function channelFromUrl(url: string, meta: Meta | undefined): string | null {
  if (!meta || !url.trim()) return null;
  try {
    const host = new URL(url.includes("://") ? url : `https://${url}`).hostname.toLowerCase();
    for (const [h, ch] of Object.entries(meta.channel_by_host)) {
      if (host === h || host.endsWith(`.${h}`)) return ch;
    }
  } catch {
    /* not a URL yet */
  }
  return null;
}
