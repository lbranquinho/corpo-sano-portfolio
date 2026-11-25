import clsx from "clsx";
import {
  BarChart3,
  Bell,
  CalendarDays,
  ClipboardList,
  Contact,
  CreditCard,
  FileText,
  HeartHandshake,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageCircle,
  Moon,
  Package,
  Plus,
  Search,
  Settings,
  Sparkles,
  Sun,
  UserCog,
  Users,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { get } from "../lib/api";
import { useGet } from "../lib/hooks";
import { useAuth } from "../lib/auth";
import { Logo } from "./Logo";

type Item = { to: string; label: string; icon: ReactNode; perms: string[]; group?: string };

export const MENU: Item[] = [
  { to: "/", label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, perms: ["dashboard.view"] },
  { to: "/agenda", label: "Agenda", icon: <CalendarDays className="h-4 w-4" />, perms: ["agenda.read"], group: "Atendimento" },
  { to: "/clientes", label: "Clientes", icon: <Users className="h-4 w-4" />, perms: ["customers.read"], group: "Atendimento" },
  { to: "/crm", label: "CRM", icon: <HeartHandshake className="h-4 w-4" />, perms: ["crm.read"], group: "Atendimento" },
  { to: "/atendimentos", label: "Atendimentos", icon: <ClipboardList className="h-4 w-4" />, perms: ["clinical.read"], group: "Atendimento" },
  { to: "/servicos", label: "Serviços", icon: <Sparkles className="h-4 w-4" />, perms: ["services.read"], group: "Negócio" },
  { to: "/pacotes", label: "Pacotes", icon: <Package className="h-4 w-4" />, perms: ["packages.read"], group: "Negócio" },
  { to: "/financeiro", label: "Financeiro", icon: <CreditCard className="h-4 w-4" />, perms: ["finance.read", "finance.payments"], group: "Negócio" },
  { to: "/fiscal", label: "Contábil e Fiscal", icon: <FileText className="h-4 w-4" />, perms: ["fiscal.read"], group: "Negócio" },
  { to: "/relatorios", label: "Relatórios", icon: <BarChart3 className="h-4 w-4" />, perms: ["reports.operational", "reports.financial", "reports.fiscal"], group: "Negócio" },
  { to: "/whatsapp", label: "WhatsApp", icon: <MessageCircle className="h-4 w-4" />, perms: ["whatsapp.read"], group: "Sistema" },
  { to: "/usuarios", label: "Usuários", icon: <UserCog className="h-4 w-4" />, perms: ["users.manage", "audit.read"], group: "Sistema" },
  { to: "/configuracoes", label: "Configurações", icon: <Settings className="h-4 w-4" />, perms: ["settings.manage", "agenda.settings", "finance.settings", "backups.manage"], group: "Sistema" },
];

const BOTTOM = ["/", "/agenda", "/clientes", "/financeiro"];

const FISCAL_SUB = [
  { to: "/fiscal/emissao", label: "Emissão de NFS-e", perms: ["fiscal.issue"] },
  { to: "/fiscal/notas", label: "Notas emitidas", perms: ["fiscal.read"] },
  { to: "/fiscal/recebidas", label: "Notas recebidas", perms: ["fiscal.read"] },
  { to: "/fiscal/tributos", label: "Tributos", perms: ["fiscal.read"] },
  { to: "/fiscal/receitas-despesas", label: "Receitas e despesas", perms: ["fiscal.read"] },
  { to: "/fiscal/obrigacoes", label: "Obrigações fiscais", perms: ["fiscal.read"] },
  { to: "/fiscal/documentos", label: "Documentos contábeis", perms: ["fiscal.read"] },
  { to: "/fiscal/exportacao", label: "Exportação para contador", perms: ["fiscal.export"] },
  { to: "/fiscal/configuracoes", label: "Cadastro fiscal", perms: ["fiscal.read"] },
];

const QUICK = [
  { label: "Novo cliente", to: "/clientes?novo=1", perms: ["customers.write"] },
  { label: "Novo agendamento", to: "/agenda?novo=1", perms: ["agenda.write"] },
  { label: "Registrar atendimento", to: "/atendimentos", perms: ["clinical.write"] },
  { label: "Registrar pagamento", to: "/financeiro?aba=receber", perms: ["finance.payments"] },
  { label: "Emitir nota fiscal", to: "/fiscal/emissao", perms: ["fiscal.issue"] },
  { label: "Cadastrar despesa", to: "/financeiro?aba=pagar&nova=1", perms: ["finance.write"] },
  { label: "Consultar agenda", to: "/agenda", perms: ["agenda.read"] },
  { label: "Consultar CRM", to: "/crm", perms: ["crm.read"] },
  { label: "Consultar financeiro", to: "/financeiro", perms: ["finance.read"] },
  { label: "Obrigações fiscais", to: "/fiscal/obrigacoes", perms: ["fiscal.read"] },
];

/** Fecha um menu suspenso ao clicar fora dele ou apertar Esc. */
function useDismiss(ref: RefObject<HTMLElement>, open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && close();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, open, close]);
}

const ICON_BTN = "btn-ghost h-11 w-11 shrink-0 !p-0 sm:h-10 sm:w-10";

/** Sino: mostra os alertas do painel (os mesmos da página inicial) sem sair da tela atual. */
function AlertsMenu() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  useDismiss(box, open, () => setOpen(false));
  // mesma chave de cache do painel: só busca ao abrir; se o painel já carregou, a contagem aparece sem nova chamada
  const { data, isLoading } = useGet<any>(["dashboard"], "/dashboard", undefined, open);
  const alerts: any[] = data?.alerts || [];
  const dot = { danger: "bg-rose-600", warning: "bg-amber-500", info: "bg-brand-600" } as Record<string, string>;
  return (
    <div ref={box} className="relative">
      <button className={clsx(ICON_BTN, "relative")} onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="true"
        aria-label={alerts.length ? `Alertas (${alerts.length})` : "Alertas"}>
        <Bell className="h-5 w-5" />
        {alerts.length > 0 && (
          <span className="absolute right-1.5 top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-600 px-1 text-[0.625rem] font-semibold leading-none text-white" aria-hidden>
            {alerts.length}
          </span>
        )}
      </button>
      {open && (
        <div className="card absolute right-0 top-12 z-30 w-80 max-w-[calc(100vw-1rem)] p-1.5">
          <p className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Alertas</p>
          {isLoading ? (
            <p className="px-3 py-3 text-sm text-slate-500 dark:text-slate-400">Carregando...</p>
          ) : alerts.length === 0 ? (
            <p className="px-3 py-3 text-sm text-slate-500 dark:text-slate-400">Nenhum alerta no momento.</p>
          ) : (
            alerts.map((a, i) => (
              <button key={i} className="flex w-full items-start gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
                onClick={() => { setOpen(false); navigate(a.url); }}>
                <span className={clsx("mt-1.5 h-2 w-2 shrink-0 rounded-full", dot[a.level] || dot.info)} aria-hidden />
                <span>{a.text}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/** Avatar com o menu da conta: minha conta, tema e sair (no celular, libera espaço no cabeçalho). */
function UserMenu({ dark, setDark }: { dark: boolean; setDark: (v: boolean) => void }) {
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  useDismiss(box, open, () => setOpen(false));
  const initials = me?.name.split(" ").map((p) => p[0]).slice(0, 2).join("");
  const item = "flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800";
  return (
    <div ref={box} className="relative sm:ml-1 sm:border-l sm:border-slate-200 sm:pl-2 sm:dark:border-slate-700">
      <button className="flex min-h-11 items-center gap-2 rounded-xl px-1 hover:bg-slate-100 dark:hover:bg-slate-800 sm:min-h-10 sm:px-2"
        onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="true" aria-label="Menu da conta">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-lavender text-xs font-semibold text-violet-700" aria-hidden>{initials}</span>
        <span className="hidden text-left leading-tight md:block">
          <span className="block text-sm font-medium">{me?.name}</span>
          <span className="block text-xs text-slate-500 dark:text-slate-400">{me?.role_name}</span>
        </span>
      </button>
      {open && (
        <div className="card absolute right-0 top-12 z-30 w-60 max-w-[calc(100vw-1rem)] p-1.5">
          <div className="border-b border-slate-100 px-3 pb-2 pt-1.5 dark:border-slate-800 md:hidden">
            <p className="truncate text-sm font-medium">{me?.name}</p>
            <p className="truncate text-xs text-slate-500 dark:text-slate-400">{me?.role_name}</p>
          </div>
          <button className={item} onClick={() => { setOpen(false); navigate("/minha-conta"); }}><Contact className="h-4 w-4" aria-hidden /> Minha conta</button>
          <button className={item} onClick={() => setDark(!dark)}>
            {dark ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />} {dark ? "Tema claro" : "Tema escuro"}
          </button>
          <button className={clsx(item, "text-rose-700 dark:text-rose-300")} onClick={() => logout()}><LogOut className="h-4 w-4" aria-hidden /> Sair</button>
        </div>
      )}
    </div>
  );
}

function QuickMenu({ items }: { items: typeof QUICK }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  useDismiss(box, open, () => setOpen(false));
  return (
    <div ref={box} className="relative">
      <button className="btn-primary min-h-11 min-w-11 !rounded-full !px-3 sm:min-h-10" onClick={() => setOpen((v) => !v)} aria-label="Atalhos rápidos"
        aria-expanded={open} aria-haspopup="true">
        {open ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
        <span className="hidden sm:inline">Atalhos</span>
      </button>
      {open && (
        <div className="card absolute right-0 top-12 z-30 w-60 max-w-[calc(100vw-1rem)] p-1.5">
          {items.map((q) => (
            <button key={q.label} className="block w-full rounded-lg px-3 py-2.5 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
              onClick={() => { setOpen(false); navigate(q.to); }}>{q.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("cs-theme", dark ? "dark" : "light");
    } catch {
      /* navegação privada */
    }
  }, [dark]);
  return [dark, setDark] as const;
}

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    const t = setTimeout(() => {
      get("/search", { q }).then(setResults).catch(() => setResults([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        box.current?.querySelector("input")?.focus();
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  const typeLabel: Record<string, string> = { cliente: "Cliente", agendamento: "Agendamento", nota: "NFS-e", servico: "Serviço" };
  return (
    <div ref={box} className="relative min-w-0 flex-1 sm:max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" aria-hidden />
      <input className="input !rounded-full !bg-slate-50 pl-9 dark:!bg-slate-800" placeholder="Pesquisar..." title="Pesquisar cliente, telefone, CPF, nota... (Ctrl+K)"
        value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} aria-label="Pesquisa global" />
      {open && q.trim().length >= 2 && (
        <div className="card absolute left-0 right-0 top-11 z-30 max-h-96 overflow-y-auto p-1">
          {results.length === 0 ? (
            <p className="px-3 py-3 text-sm text-slate-500">Nenhum resultado.</p>
          ) : (
            results.map((r) => (
              <button key={r.type + r.id} className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800"
                onClick={() => { setOpen(false); setQ(""); navigate(r.url); }}>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{r.title}</span>
                  <span className="block truncate text-xs text-slate-500">{r.subtitle}</span>
                </span>
                <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{typeLabel[r.type]}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export function AppLayout() {
  const { me, canAny } = useAuth();
  const [dark, setDark] = useTheme();
  const [mobile, setMobile] = useState(false);
  const location = useLocation();
  useEffect(() => setMobile(false), [location.pathname]);
  useEffect(() => {
    if (!mobile) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMobile(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobile]);
  const items = MENU.filter((m) => canAny(...m.perms));
  const quickItems = QUICK.filter((q) => canAny(...q.perms));

  const sidebar = (
    <nav className="flex h-full flex-col">
      {me?.has_logo ? (
        <div className="flex h-20 items-center justify-center border-b border-slate-100 bg-white px-5 dark:border-slate-800">
          <Logo hasLogo className="!h-16" />
        </div>
      ) : (
        <div className="brand-gradient flex h-20 items-center px-5">
          <Logo hasLogo={false} light />
        </div>
      )}
      <div className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
        {items.map((m, i) => (
          <div key={m.to}>
            {m.group && m.group !== items[i - 1]?.group && (
              <p className="px-3 pb-1 pt-4 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{m.group}</p>
            )}
            <NavLink to={m.to} end={m.to === "/"}
              className={({ isActive }) => clsx("flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition",
                isActive ? "bg-brand-100 text-brand-900 dark:bg-brand-900/50 dark:text-white" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800")}>
              <span aria-hidden>{m.icon}</span>
              {m.label}
            </NavLink>
            {m.to === "/fiscal" && location.pathname.startsWith("/fiscal") && (
              <div className="ml-6 mt-0.5 space-y-0.5 border-l border-slate-200 pl-3 dark:border-slate-800">
                {FISCAL_SUB.filter((s) => canAny(...s.perms)).map((s) => (
                  <NavLink key={s.to} to={s.to}
                    className={({ isActive }) => clsx("block rounded-lg px-2.5 py-2 text-[13px]",
                      isActive ? "font-medium text-brand-700 dark:text-brand-100" : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200")}>
                    {s.label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        Corpo Sano · gestão para massoterapia
      </div>
    </nav>
  );

  return (
    <div className="flex h-full">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 lg:block">{sidebar}</aside>
      {mobile && (
        <div className="fixed inset-0 z-40 bg-slate-900/40 lg:hidden" onClick={() => setMobile(false)}>
          <aside role="dialog" aria-modal="true" aria-label="Menu principal" className="h-full w-72 max-w-[85vw] overflow-y-auto bg-white dark:bg-slate-900"
            onClick={(e) => e.stopPropagation()}>{sidebar}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-2 border-b border-slate-200 bg-white/90 px-2 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90 sm:gap-3 sm:px-6">
          <button className={clsx(ICON_BTN, "lg:hidden")} onClick={() => setMobile(true)} aria-label="Abrir menu" aria-expanded={mobile}><Menu className="h-5 w-5" /></button>
          <GlobalSearch />
          <div className="ml-auto flex shrink-0 items-center gap-0.5 sm:gap-1.5">
            {quickItems.length > 0 && <QuickMenu items={quickItems} />}
            {canAny("dashboard.view") && <AlertsMenu />}
            <button className={clsx(ICON_BTN, "hidden sm:inline-flex")} onClick={() => setDark(!dark)} aria-label={dark ? "Usar tema claro" : "Usar tema escuro"} title={dark ? "Tema claro" : "Tema escuro"}>
              {dark ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>
            <UserMenu dark={dark} setDark={setDark} />
          </div>
        </header>
        <main className="mx-auto w-full min-w-0 max-w-[1500px] flex-1 px-3 py-4 pb-24 sm:px-6 sm:py-5 sm:pb-24 lg:pb-5">
          <Outlet />
        </main>
        {/* celular e tablet: as telas do dia a dia a um toque */}
        <nav aria-label="Navegação rápida"
          className="fixed inset-x-0 bottom-0 z-20 flex border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur dark:border-slate-800 dark:bg-slate-900/95 lg:hidden">
          {items.filter((m) => BOTTOM.includes(m.to)).map((m) => (
            <NavLink key={m.to} to={m.to} end={m.to === "/"}
              className={({ isActive }) => clsx("flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-xs font-medium",
                isActive ? "text-brand-700 dark:text-brand-100" : "text-slate-600 dark:text-slate-400")}>
              <span aria-hidden className="[&>svg]:h-5 [&>svg]:w-5">{m.icon}</span>
              {m.label}
            </NavLink>
          ))}
          <button className="flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-xs font-medium text-slate-600 dark:text-slate-400"
            onClick={() => setMobile(true)} aria-expanded={mobile}>
            <Menu className="h-5 w-5" aria-hidden />
            Menu
          </button>
        </nav>
      </div>
    </div>
  );
}
