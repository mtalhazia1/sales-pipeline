import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { BarChart3, Bot, CalendarCheck, Columns3, Moon, Plus, Search, Settings } from "lucide-react";
import { useDrawer, useOpportunities } from "../lib/hooks";
import { StagePill, cx } from "./ui";
import { toggleTheme } from "./theme";

type Item = { key: string; label: ReactNode; hint?: ReactNode; icon?: ReactNode; run: () => void; text: string };

export function CommandPalette({ open, onClose, onNew }: { open: boolean; onClose: () => void; onNew: () => void }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const nav = useNavigate();
  const drawer = useDrawer();
  const { data: opps } = useOpportunities();

  useEffect(() => {
    if (open) {
      setQ("");
      setSel(0);
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const go = (path: string) => () => nav(path);
    const actions: Item[] = [
      { key: "new", label: "New opportunity", icon: <Plus size={15} />, hint: "N", run: onNew, text: "new add create" },
      { key: "today", label: "Today", icon: <CalendarCheck size={15} />, hint: "G T", run: go("/"), text: "today agenda" },
      { key: "pipe", label: "Pipeline", icon: <Columns3 size={15} />, hint: "G P", run: go("/pipeline"), text: "pipeline board list" },
      { key: "rev", label: "Review agent changes", icon: <Bot size={15} />, hint: "G R", run: go("/review"), text: "review agents activity" },
      { key: "ins", label: "Insights", icon: <BarChart3 size={15} />, hint: "G I", run: go("/insights"), text: "insights stats analytics" },
      { key: "set", label: "Settings & agent access", icon: <Settings size={15} />, hint: "G S", run: go("/settings"), text: "settings api keys mcp connect" },
      { key: "theme", label: "Toggle dark mode", icon: <Moon size={15} />, run: toggleTheme, text: "theme dark light" },
    ];
    const needle = q.trim().toLowerCase();
    const oppItems: Item[] = (opps ?? [])
      .filter((o) => !needle || `${o.company} ${o.title ?? ""} ${o.application_url ?? ""}`.toLowerCase().includes(needle))
      .slice(0, needle ? 12 : 6)
      .map((o) => ({
        key: `o${o.id}`,
        label: (
          <span className="flex min-w-0 items-baseline gap-2">
            <span className="truncate font-medium">{o.company}</span>
            {o.title && <span className="truncate text-muted">{o.title}</span>}
          </span>
        ),
        hint: <StagePill stage={o.stage} />,
        run: () => drawer.open(o.id),
        text: o.company,
      }));
    const acts = actions.filter((a) => !needle || a.text.includes(needle) || String(a.label).toLowerCase().includes(needle));
    return needle ? [...oppItems, ...acts] : [...acts.slice(0, 2), ...oppItems, ...acts.slice(2)];
  }, [q, opps, nav, drawer, onNew]);

  useEffect(() => setSel(0), [q]);
  if (!open) return null;

  const run = (i: Item) => {
    onClose();
    i.run();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh] backdrop-blur-[2px]" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" className="anim-pop w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-panel shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Search size={16} className="text-muted" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "ArrowDown") (e.preventDefault(), setSel((s) => Math.min(s + 1, items.length - 1)));
              if (e.key === "ArrowUp") (e.preventDefault(), setSel((s) => Math.max(s - 1, 0)));
              if (e.key === "Enter" && items[sel]) run(items[sel]);
            }}
            placeholder="Search companies, jump anywhere…"
            className="h-12 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted"
          />
        </div>
        <div className="scroll-thin max-h-[50vh] overflow-y-auto p-1.5">
          {items.length === 0 && <div className="px-3 py-6 text-center text-muted">No matches</div>}
          {items.map((it, i) => (
            <button
              key={it.key}
              onMouseEnter={() => setSel(i)}
              onClick={() => run(it)}
              className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left", i === sel && "bg-panel-2")}
            >
              {it.icon && <span className="text-muted">{it.icon}</span>}
              <span className="min-w-0 flex-1">{it.label}</span>
              {it.hint && <span className="shrink-0 text-xs text-muted">{it.hint}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
