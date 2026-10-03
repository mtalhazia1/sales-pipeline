import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { X, Bot, Star } from "lucide-react";
import { STAGE_STYLE, labelOf, useMeta } from "../lib/meta";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "soft" | "danger";
  size?: "sm" | "md";
};

export function Button({ variant = "soft", size = "md", className, ...p }: BtnProps) {
  return (
    <button
      {...p}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition active:scale-[.98] disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap",
        size === "sm" ? "h-8 px-2.5 text-[13px]" : "h-9 px-3.5 text-[14px]",
        variant === "primary" && "bg-accent text-accent-fg hover:brightness-110 shadow-sm",
        variant === "soft" && "bg-panel-2 hover:bg-line/70 text-fg border border-line",
        variant === "ghost" && "hover:bg-panel-2 text-muted hover:text-fg",
        variant === "danger" && "bg-rose-500/10 text-rose-600 dark:text-rose-300 hover:bg-rose-500/20",
        className,
      )}
    />
  );
}

export function StagePill({ stage, className }: { stage: string; className?: string }) {
  const { data: meta } = useMeta();
  const s = STAGE_STYLE[stage] ?? STAGE_STYLE.lead;
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium", s.pill, className)}>
      <span className={cx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {labelOf(meta?.stages, stage)}
    </span>
  );
}

export function Chip({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded-md bg-panel-2 px-1.5 py-0.5 text-xs text-muted", className)}>
      {children}
    </span>
  );
}

export function AgentBadge({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-accent/12 px-1.5 py-0.5 text-xs font-medium text-accent">
      <Bot size={12} /> {name}
    </span>
  );
}

export function YourMove() {
  return <span className="rounded-md bg-orange-500/15 px-1.5 py-0.5 text-xs font-semibold text-orange-600 dark:text-orange-300">Your move</span>;
}

export function Fit({ value, onChange }: { value: number | null; onChange?: (v: number | null) => void }) {
  return (
    <span className="inline-flex items-center" aria-label={`Fit ${value ?? 0} of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          disabled={!onChange}
          onClick={() => onChange?.(value === n ? null : n)}
          className={cx("p-0.5 disabled:cursor-default", onChange && "hover:scale-110 transition")}
          title={onChange ? `Fit ${n}/5` : undefined}
        >
          <Star size={13} className={n <= (value ?? 0) ? "fill-amber-400 text-amber-400" : "text-line"} />
        </button>
      ))}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-line bg-panel-2 px-1.5 py-px font-sans text-[11px] text-muted">{children}</kbd>;
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line px-6 py-10 text-center">
      {icon && <div className="text-muted">{icon}</div>}
      <div className="font-medium">{title}</div>
      {children && <div className="max-w-sm text-[13px] text-muted">{children}</div>}
    </div>
  );
}

export function Spinner() {
  return <div className="h-5 w-5 animate-spin rounded-full border-2 border-line border-t-accent" />;
}

export function PageLoading() {
  return (
    <div className="flex h-60 items-center justify-center">
      <Spinner />
    </div>
  );
}

// ---------------------------------------------------------------- modal

export function Modal({ open, onClose, title, children, width = "max-w-lg" }: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  width?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[10vh] backdrop-blur-[2px]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        className={cx("anim-pop w-full rounded-2xl border border-line bg-panel shadow-2xl", width)}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {title && (
          <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <div className="font-semibold">{title}</div>
            <button onClick={onClose} className="rounded-md p-1 text-muted hover:bg-panel-2 hover:text-fg" aria-label="Close">
              <X size={16} />
            </button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- toasts

type Toast = { id: number; text: string; tone: "ok" | "error"; action?: { label: string; run: () => void } };
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = ++seq.current;
    setToasts((all) => [...all.slice(-2), { ...t, id }]);
    setTimeout(() => setToasts((all) => all.filter((x) => x.id !== id)), t.action ? 6000 : 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 md:bottom-6">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cx(
              "anim-pop pointer-events-auto flex items-center gap-3 rounded-xl px-4 py-2.5 text-[13px] font-medium shadow-lg",
              t.tone === "ok" ? "bg-fg text-bg" : "bg-rose-600 text-white",
            )}
          >
            {t.text}
            {t.action && (
              <button
                className="rounded-md px-1.5 py-0.5 font-semibold underline-offset-2 hover:underline"
                onClick={() => {
                  t.action!.run();
                  setToasts((all) => all.filter((x) => x.id !== t.id));
                }}
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastCtx);
  return {
    ok: (text: string, action?: Toast["action"]) => push({ text, tone: "ok", action }),
    error: (e: unknown) => push({ text: e instanceof Error ? e.message : String(e), tone: "error" }),
  };
}

export function Select({ value, onChange, options, className, placeholder }: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  className?: string;
  placeholder?: string;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={cx("field cursor-pointer pr-8", className)}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Segmented<T extends string>({ value, onChange, options }: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode }[];
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-panel-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cx(
            "inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition",
            value === o.value ? "bg-panel text-fg shadow-sm" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
