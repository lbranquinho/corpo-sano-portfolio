import clsx from "clsx";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Info, Loader2, X, XCircle } from "lucide-react";
import {
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { label as statusLabel } from "../lib/format";

/* ------------------------------------------------------------------ Botões e campos */
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  loading?: boolean;
  icon?: ReactNode;
  size?: "sm" | "md";
};

// classes literais (o Tailwind só gera classes encontradas no código-fonte)
const BTN = { primary: "btn-primary", secondary: "btn-secondary", ghost: "btn-ghost", danger: "btn-danger" } as const;

export function Button({ variant = "primary", loading, icon, size = "md", className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      className={clsx(BTN[variant], size === "sm" && "!px-2.5 !py-1.5 !text-xs", className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

/** Liga dica/erro ao campo dentro do Field (aria-describedby / aria-invalid) para leitores de tela. */
const FieldCtx = createContext<{ describedBy?: string; invalid?: boolean }>({});

function useFieldAria(p: { "aria-describedby"?: string; "aria-invalid"?: InputHTMLAttributes<HTMLInputElement>["aria-invalid"] }) {
  const f = useContext(FieldCtx);
  return {
    "aria-describedby": [p["aria-describedby"], f.describedBy].filter(Boolean).join(" ") || undefined,
    "aria-invalid": p["aria-invalid"] ?? (f.invalid || undefined),
  };
}

export function Field({ label, hint, error, children, className, required }: {
  label?: string; hint?: string; error?: string; children: ReactNode; className?: string; required?: boolean;
}) {
  const id = useId();
  const msgId = error || hint ? `${id}-msg` : undefined;
  return (
    <FieldCtx.Provider value={{ describedBy: msgId, invalid: !!error }}>
    <label className={clsx("block", className)}>
      {label && (
        <span className="label">
          {label}
          {required && <span className="text-rose-600 dark:text-rose-400" aria-hidden> *</span>}
        </span>
      )}
      {children}
      {hint && !error && <span id={msgId} className="mt-1 block text-xs text-slate-500 dark:text-slate-400">{hint}</span>}
      {error && <span id={msgId} role="alert" className="mt-1 block text-xs text-rose-600 dark:text-rose-400">{error}</span>}
    </label>
    </FieldCtx.Provider>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  const aria = useFieldAria(p);
  return <input ref={ref} className={clsx("input", className)} {...p} {...aria} />;
});

export function Select({ className, children, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  const aria = useFieldAria(p);
  return (
    <select className={clsx("input pr-8", className)} {...p} {...aria}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const aria = useFieldAria(p);
  return <textarea className={clsx("input min-h-[80px]", className)} {...p} {...aria} />;
}

export function Checkbox({ label, checked, onChange, hint }: { label: ReactNode; checked: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-sm">
      <input type="checkbox" className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-600" checked={checked}
        onChange={(e) => onChange(e.target.checked)} />
      <span>
        {label}
        {hint && <span className="block text-xs text-slate-500 dark:text-slate-400">{hint}</span>}
      </span>
    </label>
  );
}

/* ------------------------------------------------------------------ Estruturas */
export function Card({ title, actions, children, className, padded = true }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; padded?: boolean;
}) {
  return (
    <section className={clsx("card", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
          <h3 className="text-sm font-semibold">{title}</h3>
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        </div>
      )}
      <div className={clsx(padded && "p-4")}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const BADGE: Record<string, string> = {
  blue: "bg-brand-100 text-brand-900 dark:bg-brand-900/40 dark:text-brand-100",
  green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  yellow: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
  red: "bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-200",
  gray: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  violet: "bg-lavender text-violet-700 dark:bg-violet/20 dark:text-violet-200",
  pink: "bg-blossom-100 text-blossom-700 dark:bg-blossom-500/20 dark:text-blossom-200",
};

const STATUS_COLOR: Record<string, string> = {
  agendado: "blue", confirmado: "violet", em_atendimento: "yellow", concluido: "green", cancelado: "gray", falta: "red",
  aberto: "blue", parcial: "yellow", pago: "green", ativo: "green", expirado: "gray", rascunho: "gray",
  aguardando_transmissao: "yellow", transmitindo: "yellow", autorizada: "green", rejeitada: "red", cancelada: "gray",
  substituida: "gray", pendente: "blue", em_preparacao: "violet", enviado: "green", concluida: "green", atrasado: "red",
  nao_aplicavel: "gray", estimado: "yellow", validado: "blue", enviando: "yellow", enviada: "blue", entregue: "violet",
  lida: "green", falhou: "red", bloqueada: "gray", recebida: "pink", sucesso: "green", falha: "red", executando: "yellow",
  inativo: "gray", anonimizado: "gray",
};

export function Badge({ color = "gray", children, className }: { color?: string; children: ReactNode; className?: string }) {
  return <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", BADGE[color], className)}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge color={STATUS_COLOR[status] || "gray"}>{statusLabel(status)}</Badge>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("h-5 w-5 animate-spin text-brand-600", className)} />;
}

export function Loading({ text = "Carregando..." }: { text?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500 dark:text-slate-400" role="status">
      <Spinner /> {text}
    </div>
  );
}

/** Bloco cinza animado que reserva o espaço do conteúdo enquanto carrega (evita a página "pular"). */
export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-xl bg-slate-200/70 motion-reduce:animate-none dark:bg-slate-800", className)} aria-hidden />;
}

export function Empty({ title = "Nada por aqui ainda", text, action }: { title?: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      <svg viewBox="0 0 64 64" className="h-12 w-12 opacity-60" aria-hidden>
        <path d="M32 10 C38 18 40 28 32 42 C24 28 26 18 32 10 Z" fill="#DBEAFE" />
        <path d="M8 28 C20 26 28 32 32 42 C20 42 12 36 8 28 Z" fill="#EDE9FE" />
        <path d="M56 28 C44 26 36 32 32 42 C44 42 52 36 56 28 Z" fill="#FCE7F3" />
      </svg>
      <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{title}</p>
      {text && <p className="max-w-md text-xs text-slate-500 dark:text-slate-400">{text}</p>}
      {action}
    </div>
  );
}

export function Alert({ kind = "info", children, title }: { kind?: "info" | "warning" | "danger" | "success"; children: ReactNode; title?: string }) {
  const styles = {
    info: "border-brand-100 bg-brand-50 text-brand-900 dark:border-brand-900 dark:bg-brand-900/20 dark:text-brand-100",
    warning: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-900/20 dark:text-amber-100",
    danger: "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-900/20 dark:text-rose-100",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-900/20 dark:text-emerald-100",
  }[kind];
  const Icon = { info: Info, warning: AlertTriangle, danger: XCircle, success: CheckCircle2 }[kind];
  return (
    <div className={clsx("flex gap-2.5 rounded-xl border px-3 py-2.5 text-sm", styles)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        {title && <p className="font-medium">{title}</p>}
        <div className="text-[13px] leading-relaxed">{children}</div>
      </div>
    </div>
  );
}

export function StatCard({ label, value, hint, icon, tone = "blue", onClick }: {
  label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: "blue" | "violet" | "pink" | "green" | "amber" | "slate"; onClick?: () => void;
}) {
  const tones = {
    blue: "bg-brand-100 text-brand-700 dark:bg-brand-900/40 dark:text-brand-100",
    violet: "bg-lavender text-violet-700 dark:bg-violet/20 dark:text-violet-200",
    pink: "bg-blossom-100 text-blossom-700 dark:bg-blossom-500/20 dark:text-blossom-200",
    green: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-200",
    amber: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200",
    slate: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  }[tone];
  const body = (
    <>
      {/* no celular o ícone sai para o valor caber nos cartões em duas colunas */}
      {icon && <div className={clsx("hidden rounded-xl p-2.5 sm:block", tones)} aria-hidden>{icon}</div>}
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium leading-tight text-slate-500 dark:text-slate-400">{label}</p>
        <p className="mt-0.5 text-xl font-semibold tabular-nums text-slate-900 dark:text-white">{value}</p>
        {hint && <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
      </div>
    </>
  );
  // cartão clicável = botão de verdade (Tab + Enter) com seta indicando que leva a outra tela
  if (onClick)
    return (
      <button type="button" onClick={onClick}
        className="card group relative flex w-full items-start gap-3 p-4 pr-8 text-left transition hover:-translate-y-0.5 hover:border-brand-500/40 motion-reduce:transition-none motion-reduce:hover:translate-y-0">
        {body}
        <ChevronRight className="absolute right-3 top-4 h-4 w-4 text-slate-500 transition group-hover:translate-x-0.5 group-hover:text-brand-600 motion-reduce:transition-none" aria-hidden />
      </button>
    );
  return <div className="card flex items-start gap-3 p-4">{body}</div>;
}

export function Tabs({ tabs, value, onChange }: { tabs: { key: string; label: string; badge?: ReactNode }[]; value: string; onChange: (k: string) => void }) {
  const list = useRef<HTMLDivElement>(null);
  // setas, Home e End movem entre as abas (padrão WAI-ARIA)
  const onKey = (e: ReactKeyboardEvent) => {
    const i = tabs.findIndex((t) => t.key === value);
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const k = tabs[(next + tabs.length) % tabs.length].key;
    onChange(k);
    requestAnimationFrame(() => list.current?.querySelector<HTMLElement>(`[data-tab="${CSS.escape(k)}"]`)?.focus());
  };
  return (
    <div ref={list} role="tablist" onKeyDown={onKey} className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-800">
      {tabs.map((t) => (
        <button key={t.key} type="button" role="tab" data-tab={t.key} aria-selected={value === t.key} tabIndex={value === t.key ? 0 : -1}
          onClick={() => onChange(t.key)}
          className={clsx("-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition",
            value === t.key ? "border-brand-600 text-brand-700 dark:text-brand-100" : "border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200")}>
          {t.label}
          {t.badge}
        </button>
      ))}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return <p className="px-3 py-2 text-xs text-slate-500 dark:text-slate-400">{total} registro(s)</p>;
  return (
    <div className="flex items-center justify-between px-3 py-2 text-xs text-slate-500 dark:text-slate-400">
      <span>{total} registro(s)</span>
      <div className="flex items-center gap-1">
        <button className="btn-ghost h-11 w-11 !p-0 sm:h-8 sm:w-8" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Anterior"><ChevronLeft className="h-4 w-4" /></button>
        <span>Página {page} de {pages}</span>
        <button className="btn-ghost h-11 w-11 !p-0 sm:h-8 sm:w-8" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Próxima"><ChevronRight className="h-4 w-4" /></button>
      </div>
    </div>
  );
}

export type Column<T> = { key: string; label: string; render?: (row: T) => ReactNode; className?: string };

export function DataTable<T extends Record<string, any>>({ columns, rows, onRowClick, empty, rowKey = "id" }: {
  columns: Column<T>[]; rows: T[]; onRowClick?: (row: T) => void; empty?: ReactNode; rowKey?: string;
}) {
  if (!rows.length) return <>{empty ?? <Empty />}</>;
  return (
    <div className="overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>{columns.map((c) => <th key={c.key} className={c.className}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r[rowKey] ?? i} onClick={onRowClick ? () => onRowClick(r) : undefined} className={clsx(onRowClick && "cursor-pointer")}>
              {columns.map((c) => <td key={c.key} className={c.className}>{c.render ? c.render(r) : (r[c.key] ?? "—")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ Sobreposições */
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
const dialogStack: RefObject<HTMLDivElement>[] = [];

/**
 * Comportamento de diálogo acessível: foco vai para dentro ao abrir, Tab fica preso no diálogo,
 * Esc fecha e, ao fechar, o foco volta para o elemento que o abriu. Só o diálogo do topo reage.
 */
function useDialog(open: boolean, onClose: () => void, box: RefObject<HTMLDivElement>) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    dialogStack.push(box);
    // trava a rolagem da página atrás da janela (no iPhone, o teclado rolava a página de fundo e a janela
    // ficava deslocada/sem redesenhar depois que o teclado fechava)
    document.documentElement.style.overflow = "hidden";
    const el = box.current;
    if (el && !el.contains(document.activeElement)) {
      const auto = el.querySelector<HTMLElement>("[autofocus]");
      const first = el.querySelector<HTMLElement>(`[data-dialog-body] :is(${FOCUSABLE})`);
      (auto || first || el).focus();
    }
    const onKey = (e: KeyboardEvent) => {
      if (dialogStack[dialogStack.length - 1] !== box || !box.current) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const items = Array.from(box.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((x) => x.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || !box.current.contains(document.activeElement))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      const i = dialogStack.indexOf(box);
      if (i >= 0) dialogStack.splice(i, 1);
      if (!dialogStack.length) document.documentElement.style.overflow = "";
      if (opener?.isConnected) opener.focus();
    };
  }, [open, box]);
}
export function Modal({ open, onClose, title, children, footer, size = "md" }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; size?: "sm" | "md" | "lg" | "xl";
}) {
  const box = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useDialog(open, onClose, box);
  if (!open) return null;
  const width = { sm: "max-w-md", md: "max-w-2xl", lg: "max-w-4xl", xl: "max-w-6xl" }[size];
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 sm:items-center sm:bg-slate-900/40 sm:backdrop-blur-[2px] sm:p-4" onMouseDown={onClose}>
      <div ref={box} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className={clsx("card outline-none flex max-h-[92vh] max-h-[92dvh] w-full min-w-0 max-w-full flex-col rounded-b-none sm:rounded-2xl", width)}
        onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3.5 dark:border-slate-800 sm:px-5">
          <h2 id={titleId} className="min-w-0 truncate text-base font-semibold">{title}</h2>
          <button className="btn-ghost h-11 w-11 shrink-0 !p-0 sm:h-8 sm:w-8" onClick={onClose} aria-label="Fechar"><X className="h-4 w-4" /></button>
        </div>
        <div data-dialog-body className="min-w-0 overflow-y-auto overflow-x-hidden px-4 py-4 sm:px-5">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] dark:border-slate-800 sm:px-5">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useDialog(open, onClose, box);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onMouseDown={onClose}>
      <div ref={box} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className="flex h-full w-full min-w-0 max-w-lg flex-col bg-white shadow-2xl outline-none dark:bg-slate-900" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3.5 dark:border-slate-800 sm:px-5">
          <h2 id={titleId} className="min-w-0 truncate text-base font-semibold">{title}</h2>
          <button className="btn-ghost h-11 w-11 shrink-0 !p-0 sm:h-8 sm:w-8" onClick={onClose} aria-label="Fechar"><X className="h-4 w-4" /></button>
        </div>
        <div data-dialog-body className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-4 py-4 sm:px-5">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] dark:border-slate-800 sm:px-5">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------ Notificações */
type Toast = { id: number; kind: "success" | "error" | "info"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, kind, text }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-20 right-4 z-[60] lg:bottom-4 flex w-[min(92vw,380px)] flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={clsx("pointer-events-auto flex items-start gap-2 rounded-xl border px-3.5 py-3 text-sm shadow-lg",
            t.kind === "success" && "border-emerald-200 bg-white text-emerald-800 dark:border-emerald-900 dark:bg-slate-900 dark:text-emerald-200",
            t.kind === "error" && "border-rose-200 bg-white text-rose-700 dark:border-rose-900 dark:bg-slate-900 dark:text-rose-200",
            t.kind === "info" && "border-brand-100 bg-white text-brand-900 dark:border-brand-900 dark:bg-slate-900 dark:text-brand-100")}>
            {t.kind === "success" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : t.kind === "error" ? <XCircle className="mt-0.5 h-4 w-4 shrink-0" /> : <Info className="mt-0.5 h-4 w-4 shrink-0" />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const push = useContext(ToastCtx);
  return {
    success: (t: string) => push("success", t),
    error: (e: unknown) => push("error", e instanceof Error ? e.message : String(e)),
    info: (t: string) => push("info", t),
  };
}

export function ConfirmButton({ children, message, onConfirm, variant = "danger", confirmLabel = "Confirmar", requireText, size, icon }: {
  children: ReactNode; message: ReactNode; onConfirm: () => Promise<unknown> | void; variant?: BtnProps["variant"]; confirmLabel?: string;
  requireText?: string; size?: "sm" | "md"; icon?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [typed, setTyped] = useState("");
  const toast = useToast();
  return (
    <>
      <Button variant={variant === "danger" ? "secondary" : variant} size={size} icon={icon} onClick={() => setOpen(true)}>{children}</Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Confirmação" size="sm"
        footer={<>
          <Button variant="secondary" onClick={() => setOpen(false)}>Voltar</Button>
          <Button variant={variant} loading={busy} disabled={!!requireText && typed.trim().toUpperCase() !== requireText}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                setOpen(false);
              } catch (e) {
                toast.error(e);
              } finally {
                setBusy(false);
              }
            }}>{confirmLabel}</Button>
        </>}>
        <div className="space-y-3 text-sm">
          <div>{message}</div>
          {requireText && (
            <Field label={`Digite ${requireText} para confirmar`}>
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
            </Field>
          )}
        </div>
      </Modal>
    </>
  );
}
