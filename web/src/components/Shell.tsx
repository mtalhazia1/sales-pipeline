import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { BarChart3, Bell, Bot, CalendarCheck, Columns3, MessagesSquare, Moon, Plus, Search, Settings, Sun } from "lucide-react";
import { useAgenda } from "../lib/hooks";
import { CommandPalette } from "./CommandPalette";
import { Drawer } from "./Drawer";
import { QuickAdd } from "./QuickAdd";
import { Kbd, cx } from "./ui";
import { isDark, toggleTheme } from "./theme";

export function Shell() {
  const [palette, setPalette] = useState(false);
  const [adding, setAdding] = useState(false);
  const [dark, setDark] = useState(isDark);
  const { data: agenda } = useAgenda();
  const nav = useNavigate();
  const pendingG = useRef(false);

  const todayCount = agenda ? agenda.due_reminders.length + agenda.your_move.length : 0;
  const reviewCount = agenda?.needs_review ?? 0;
  const alertCount = agenda?.unread_notifications ?? 0;

  // Keyboard: ⌘K / "/" search · N new · G then T/A/P/R/M/I/S to navigate
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.closest?.("input,textarea,select,[contenteditable]");
      const dialogOpen = document.querySelector("[role=dialog]:not([data-palette])");
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k" && !dialogOpen) {
        e.preventDefault();
        setPalette((p) => !p);
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("[role=dialog]")) return;
      const k = e.key.toLowerCase();
      if (pendingG.current) {
        pendingG.current = false;
        const dest = { t: "/", a: "/alerts", p: "/pipeline", r: "/review", m: "/messages", i: "/insights", s: "/settings" }[k];
        if (dest) nav(dest);
        return;
      }
      if (k === "g") {
        pendingG.current = true;
        setTimeout(() => (pendingG.current = false), 1000);
      } else if (k === "n" || k === "c") {
        e.preventDefault();
        setAdding(true);
      } else if (k === "/") {
        e.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nav]);

  const items: { to: string; label: string; icon: ReactNode; badge?: number; tone?: string }[] = [
    { to: "/", label: "Today", icon: <CalendarCheck size={18} />, badge: todayCount, tone: "bg-orange-500 text-white" },
    { to: "/alerts", label: "Alerts", icon: <Bell size={18} />, badge: alertCount, tone: "bg-rose-500 text-white" },
    { to: "/pipeline", label: "Pipeline", icon: <Columns3 size={18} /> },
    { to: "/review", label: "Review", icon: <Bot size={18} />, badge: reviewCount, tone: "bg-accent text-accent-fg" },
    { to: "/messages", label: "Messages", icon: <MessagesSquare size={18} /> },
    { to: "/insights", label: "Insights", icon: <BarChart3 size={18} /> },
    { to: "/settings", label: "Settings", icon: <Settings size={18} /> },
  ];

  return (
    <div className="min-h-dvh md:pl-60">
      {/* desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-line bg-panel px-3 py-4 md:flex">
        <div className="mb-5 flex items-center gap-2.5 px-2">
          <Logo />
          <span className="text-[15px] font-semibold tracking-tight">Pipeline</span>
        </div>
        <button
          onClick={() => setPalette(true)}
          className="mb-2 flex h-9 items-center gap-2 rounded-lg border border-line bg-panel-2 px-2.5 text-[13px] text-muted hover:text-fg"
        >
          <Search size={15} /> Search
          <span className="ml-auto">
            <Kbd>⌘K</Kbd>
          </span>
        </button>
        <button
          onClick={() => setAdding(true)}
          className="mb-4 flex h-9 items-center gap-2 rounded-lg bg-accent px-2.5 text-[13px] font-medium text-accent-fg shadow-sm hover:brightness-110"
        >
          <Plus size={16} /> New opportunity
          <span className="ml-auto rounded bg-black/15 px-1.5 text-[11px]">N</span>
        </button>
        <nav className="flex flex-col gap-0.5">
          {items.map((i) => (
            <NavLink
              key={i.to}
              to={i.to}
              end={i.to === "/"}
              className={({ isActive }) =>
                cx(
                  "flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[14px] font-medium transition",
                  isActive ? "bg-panel-2 text-fg" : "text-muted hover:bg-panel-2/60 hover:text-fg",
                )
              }
            >
              {i.icon}
              {i.label}
              {!!i.badge && <span className={cx("ml-auto rounded-full px-1.5 text-[11px] font-semibold", i.tone)}>{i.badge}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto flex items-center gap-2 px-1 text-xs text-muted">
          <button
            onClick={() => {
              toggleTheme();
              setDark(isDark());
            }}
            className="rounded-lg p-2 hover:bg-panel-2 hover:text-fg"
            title="Toggle theme"
          >
            {dark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <span className="ml-auto">
            <Kbd>G</Kbd> then <Kbd>T</Kbd>/<Kbd>P</Kbd>/<Kbd>R</Kbd>
          </span>
        </div>
      </aside>

      {/* mobile top bar */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-line bg-panel/90 px-4 backdrop-blur md:hidden">
        <Logo />
        <span className="font-semibold">Pipeline</span>
        <button onClick={() => setPalette(true)} className="ml-auto rounded-lg p-2 text-muted" aria-label="Search">
          <Search size={20} />
        </button>
        <button onClick={() => setAdding(true)} className="rounded-lg bg-accent p-2 text-accent-fg" aria-label="New opportunity">
          <Plus size={20} />
        </button>
      </header>

      <main className="mx-auto max-w-6xl px-4 pt-5 pb-28 md:px-8 md:pt-8 md:pb-12">
        <Outlet />
      </main>

      {/* mobile bottom nav */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-7 border-t border-line bg-panel/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {items.map((i) => (
          <NavLink
            key={i.to}
            to={i.to}
            end={i.to === "/"}
            className={({ isActive }) => cx("relative flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium", isActive ? "text-accent" : "text-muted")}
          >
            {i.icon}
            {i.label}
            {!!i.badge && <span className={cx("absolute top-1 left-[calc(50%+6px)] rounded-full px-1 text-[10px] font-semibold", i.tone)}>{i.badge}</span>}
          </NavLink>
        ))}
      </nav>

      <Drawer />
      <QuickAdd open={adding} onClose={() => setAdding(false)} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} onNew={() => setAdding(true)} />
    </div>
  );
}

export function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <path d="M9 21l5-6 4 3 5-7" stroke="var(--accent-fg)" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function PageHeader({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {sub && <div className="mt-1 text-[14px] text-muted">{sub}</div>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}
