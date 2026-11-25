import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Ban, CalendarPlus, Check, CheckCheck, ChevronLeft, ChevronRight, Lock, Play, UserX, X, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CustomerPicker } from "../components/shared";
import {
  Alert, Badge, Button, Checkbox, Drawer, Empty, Field, Input, Modal, PageHeader, Select, StatusBadge, Tabs, Textarea, useToast,
} from "../components/ui";
import { del, get, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { addDays, dateTime, isoDay, label, localToIso, minutesOfDay, money, monthEnd, monthStart, time, weekdayOf } from "../lib/format";
import { useAction, useGet, useLookups } from "../lib/hooks";

const PX = 1.4; // pixels por minuto
const STATUS_STYLE: Record<string, string> = {
  agendado: "bg-brand-50 border-brand-600 text-brand-900 dark:bg-brand-900/30 dark:text-brand-100",
  confirmado: "bg-lavender border-violet text-slate-800 dark:bg-violet/20 dark:text-slate-100",
  em_atendimento: "bg-amber-50 border-amber-500 text-amber-900 dark:bg-amber-900/30 dark:text-amber-100",
  concluido: "bg-emerald-50 border-emerald-500 text-emerald-900 dark:bg-emerald-900/30 dark:text-emerald-100",
  cancelado: "bg-slate-100 border-slate-400 text-slate-500 line-through dark:bg-slate-800",
  falta: "bg-rose-50 border-rose-500 text-rose-800 dark:bg-rose-900/30 dark:text-rose-100",
};

// além da cor, cada status tem um ícone (quem não distingue cores também identifica o status)
const STATUS_ICON: Record<string, LucideIcon | undefined> = {
  confirmado: Check, em_atendimento: Play, concluido: CheckCheck, cancelado: X, falta: UserX,
};

function StatusIcon({ status }: { status: string }) {
  const Icon = STATUS_ICON[status];
  return Icon ? <Icon className="inline h-3 w-3 shrink-0 align-[-2px]" aria-label={label(status)} /> : null;
}

/** Minutos desde a meia-noite, atualizado a cada minuto (linha da hora atual). */
function useNowMinutes() {
  const calc = () => { const d = new Date(); return d.getHours() * 60 + d.getMinutes(); };
  const [now, setNow] = useState(calc);
  useEffect(() => {
    const t = setInterval(() => setNow(calc()), 60_000);
    return () => clearInterval(t);
  }, []);
  return now;
}

const isSmallScreen = () => typeof window !== "undefined" && window.matchMedia?.("(max-width: 639px)").matches;

function weekStart(day: string) {
  const wd = weekdayOf(day); // 0 = domingo
  return addDays(day, wd === 0 ? -6 : 1 - wd);
}

function lanes<T extends { start_at: string; end_at: string }>(items: T[]) {
  const sorted = [...items].sort((a, b) => a.start_at.localeCompare(b.start_at));
  const ends: number[] = [];
  const out = sorted.map((it) => {
    const s = new Date(it.start_at).getTime();
    let lane = ends.findIndex((e) => e <= s);
    if (lane === -1) { lane = ends.length; ends.push(0); }
    ends[lane] = new Date(it.end_at).getTime();
    return { it, lane };
  });
  return { placed: out, count: Math.max(1, ends.length) };
}

export default function Agenda() {
  const { can, me } = useAuth();
  const [params, setParams] = useSearchParams();
  // no celular a agenda abre como lista do dia (as colunas por profissional obrigam a rolar para o lado)
  const [view, setView] = useState<"lista" | "dia" | "semana" | "mes">(() => (isSmallScreen() ? "lista" : "dia"));
  const nowMin = useNowMinutes();
  const today = isoDay();
  const [day, setDay] = useState(params.get("data") || isoDay());
  const [prof, setProf] = useState("");
  const [showCancelled, setShowCancelled] = useState(false);
  const [creating, setCreating] = useState<null | { day: string; time: string; professional_id?: string; customer?: { id: string; full_name: string } }>(null);
  const [selected, setSelected] = useState<string | null>(params.get("agendamento"));
  const [blocking, setBlocking] = useState(false);
  const { professionals } = useLookups();
  const hours = useGet<any[]>(["business-hours"], "/settings/business-hours");
  useRefreshOnEvent();

  useEffect(() => {
    if (params.get("novo") === "1") {
      const cid = params.get("cliente");
      setCreating({ day, time: "09:00", customer: cid ? { id: cid, full_name: params.get("nome") || "Cliente" } : undefined });
      ["novo", "cliente", "nome"].forEach((k) => params.delete(k));
      setParams(params, { replace: true });
    }
  }, [params, setParams, day]);

  const [start, end] = view === "dia" || view === "lista" ? [day, day] : view === "semana" ? [weekStart(day), addDays(weekStart(day), 6)] : [monthStart(day), monthEnd(day)];
  const appts = useGet<any[]>(["appointments"], "/agenda/appointments", { start, end, professional_id: prof || undefined });
  const blocks = useGet<any[]>(["blocks"], "/agenda/blocks", { start, end });
  const visible = (appts.data || []).filter((a) => showCancelled || a.status !== "cancelado");

  const bhFor = (d: string) => {
    const wd = (weekdayOf(d) + 6) % 7; // 0 = segunda
    return (hours.data || []).find((h) => h.weekday === wd);
  };
  const [openMin, closeMin] = useMemo(() => {
    const open = (hours.data || []).filter((h) => h.is_open);
    if (!open.length) return [8 * 60, 19 * 60];
    const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
    const lo = Math.min(...open.map((h) => toMin(h.open_time)));
    const hi = Math.max(...open.map((h) => toMin(h.close_time)));
    const allMins = visible.flatMap((a) => [minutesOfDay(a.start_at), minutesOfDay(a.end_at)]);
    return [Math.min(lo, ...allMins), Math.max(hi, ...allMins)];
  }, [hours.data, visible]);
  const slots: number[] = [];
  for (let m = Math.floor(openMin / 30) * 30; m < closeMin; m += 30) slots.push(m);

  const shift = (n: number) => {
    if (view === "dia" || view === "lista") setDay(addDays(day, n));
    else if (view === "semana") setDay(addDays(day, 7 * n));
    else {
      const [y, mo] = day.split("-").map(Number);
      const d = new Date(Date.UTC(y, mo - 1 + n, 1));
      setDay(d.toISOString().slice(0, 10));
    }
  };
  const cols = view === "dia"
    ? professionals.filter((p) => (!prof || p.id === prof) && (can("agenda.read_all") || p.id === me?.professional_id)).map((p) => ({ key: p.id, title: p.name, color: p.color, day }))
    : Array.from({ length: 7 }, (_, i) => { const d = addDays(start, i); return { key: d, title: `${["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][i]} ${d.slice(8, 10)}/${d.slice(5, 7)}`, color: undefined, day: d }; });

  const title = view === "mes"
    ? new Date(`${day}T12:00:00`).toLocaleDateString("pt-BR", { month: "long", year: "numeric" })
    : view === "semana" ? `${start.split("-").reverse().join("/")} – ${end.split("-").reverse().join("/")}`
    : new Date(`${day}T12:00:00`).toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });

  return (
    <div>
      <PageHeader title="Agenda" subtitle="Clique em um horário livre para agendar. Conflitos de profissional e sala são bloqueados automaticamente."
        actions={<>
          {can("agenda.write") && <Button variant="secondary" icon={<Lock className="h-4 w-4" />} onClick={() => setBlocking(true)}>Bloquear horário</Button>}
          {can("agenda.write") && <Button icon={<CalendarPlus className="h-4 w-4" />} onClick={() => setCreating({ day, time: "09:00" })}>Novo agendamento</Button>}
        </>} />
      <div className="card mb-4 flex flex-wrap items-center gap-2 p-3">
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={() => shift(-1)} aria-label="Anterior"><ChevronLeft className="h-4 w-4" /></Button>
          <Button variant="secondary" size="sm" onClick={() => setDay(isoDay())}>Hoje</Button>
          <Button variant="ghost" size="sm" onClick={() => shift(1)} aria-label="Próximo"><ChevronRight className="h-4 w-4" /></Button>
        </div>
        <p className="min-w-[200px] text-sm font-semibold capitalize">{title}</p>
        <Input type="date" className="!w-auto" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
        {can("agenda.read_all") && (
          <Select className="!w-auto" value={prof} onChange={(e) => setProf(e.target.value)}>
            <option value="">Todos os profissionais</option>
            {professionals.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        )}
        <Checkbox label="Mostrar cancelados" checked={showCancelled} onChange={setShowCancelled} />
        <div className="ml-auto flex rounded-xl border border-slate-200 p-0.5 dark:border-slate-700" role="group" aria-label="Visualização">
          {(["lista", "dia", "semana", "mes"] as const).map((v) => (
            <button key={v} type="button" onClick={() => setView(v)} aria-pressed={view === v}
              className={clsx("min-h-10 rounded-lg px-3 py-1.5 text-sm capitalize sm:min-h-0", view === v ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800")}>
              {v === "mes" ? "Mês" : v}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        {Object.keys(STATUS_STYLE).map((s) => (
          <span key={s} className={clsx("inline-flex items-center gap-1 rounded-md border-l-4 px-2 py-0.5", STATUS_STYLE[s])}>
            {STATUS_ICON[s] && <span aria-hidden><StatusIcon status={s} /></span>}{label(s)}
          </span>
        ))}
      </div>

      {view === "mes" ? (
        <MonthGrid day={day} appts={visible} onPickDay={(d) => { setDay(d); setView(isSmallScreen() ? "lista" : "dia"); }} />
      ) : view === "lista" ? (
        <DayList appts={visible.filter((a) => isoDay(new Date(a.start_at)) === day && (!prof || a.professional_id === prof))}
          onOpen={setSelected} onNew={can("agenda.write") ? () => setCreating({ day, time: "09:00" }) : undefined} />
      ) : cols.length === 0 ? (
        <Alert kind="info">Cadastre profissionais em Configurações para visualizar a agenda.</Alert>
      ) : (
        <div className="card overflow-x-auto">
          <div className="flex min-w-max">
            <div className="sticky left-0 z-10 w-14 shrink-0 border-r border-slate-100 bg-white dark:border-slate-800 dark:bg-slate-900">
              <div className="h-10 border-b border-slate-100 dark:border-slate-800" />
              {slots.map((m) => (
                <div key={m} className="relative text-right text-xs text-slate-500 dark:text-slate-400" style={{ height: 30 * PX }}>
                  <span className="absolute -top-1.5 right-1.5">{m % 60 === 0 ? `${String(Math.floor(m / 60)).padStart(2, "0")}:00` : ""}</span>
                </div>
              ))}
            </div>
            {cols.map((c) => {
              const colAppts = visible.filter((a) => (view === "dia" ? a.professional_id === c.key && isoDay(new Date(a.start_at)) === day : isoDay(new Date(a.start_at)) === c.day));
              const { placed, count } = lanes(colAppts);
              const bh = bhFor(c.day);
              const colBlocks = (blocks.data || []).filter((b) => isoDay(new Date(b.start_at)) <= c.day && isoDay(new Date(b.end_at)) >= c.day &&
                (view === "semana" || !b.professional_id || b.professional_id === c.key));
              return (
                <div key={c.key} className="w-48 shrink-0 border-r border-slate-100 dark:border-slate-800 sm:w-56">
                  <div className="sticky top-0 flex h-10 items-center gap-2 border-b border-slate-100 px-2 text-xs font-semibold dark:border-slate-800">
                    {c.color && <span className="h-2.5 w-2.5 rounded-full" style={{ background: c.color }} />}
                    <span className="truncate">{c.title}</span>
                    {bh && !bh.is_open && <Badge color="gray">fechado</Badge>}
                  </div>
                  <div className="relative" style={{ height: slots.length * 30 * PX }}>
                    {slots.map((m, i) => (
                      <button key={m} className={clsx("absolute left-0 right-0 border-b border-slate-100 transition hover:bg-brand-50/60 dark:border-slate-800/70 dark:hover:bg-slate-800/50",
                        m % 60 !== 0 && "border-dashed")} style={{ top: i * 30 * PX, height: 30 * PX }}
                        disabled={!can("agenda.write")} aria-label={`Agendar às ${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}`}
                        onClick={() => setCreating({ day: c.day, time: `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`, professional_id: view === "dia" ? c.key : undefined })} />
                    ))}
                    {colBlocks.map((b) => {
                      const s = isoDay(new Date(b.start_at)) < c.day ? openMin : minutesOfDay(b.start_at);
                      const e = isoDay(new Date(b.end_at)) > c.day ? closeMin : minutesOfDay(b.end_at);
                      return (
                        <div key={b.id} className="pointer-events-none absolute left-0 right-0 flex items-start gap-1 bg-[repeating-linear-gradient(45deg,#e2e8f0_0,#e2e8f0_6px,transparent_6px,transparent_12px)] p-1 text-xs text-slate-600 dark:text-slate-300 dark:bg-[repeating-linear-gradient(45deg,#1e293b_0,#1e293b_6px,transparent_6px,transparent_12px)]"
                          style={{ top: (s - Math.floor(openMin / 30) * 30) * PX, height: Math.max(12, (e - s) * PX) }}>
                          <Ban className="h-3 w-3" /> {b.reason || "Bloqueado"}
                        </div>
                      );
                    })}
                    {c.day === today && nowMin >= Math.floor(openMin / 30) * 30 && nowMin < closeMin && (
                      <div className="pointer-events-none absolute left-0 right-0 z-[5] h-0.5 bg-rose-600" style={{ top: (nowMin - Math.floor(openMin / 30) * 30) * PX }} aria-hidden>
                        <span className="absolute -left-1 -top-[3px] h-2 w-2 rounded-full bg-rose-600" />
                      </div>
                    )}
                    {placed.map(({ it: a, lane }) => {
                      const s = minutesOfDay(a.start_at);
                      const top = (s - Math.floor(openMin / 30) * 30) * PX;
                      return (
                        <button key={a.id} onClick={() => setSelected(a.id)}
                          className={clsx("absolute overflow-hidden rounded-lg border-l-4 px-1.5 py-1 text-left text-xs leading-tight shadow-sm transition hover:z-10 hover:shadow-md", STATUS_STYLE[a.status])}
                          style={{ top: top + 1, height: Math.max(22, a.duration_minutes * PX - 2), left: `calc(${(lane / count) * 100}% + 2px)`, width: `calc(${100 / count}% - 4px)`,
                            borderLeftColor: view === "semana" ? a.professional_color : undefined }}>
                          <p className="truncate font-semibold"><StatusIcon status={a.status} /> {time(a.start_at)} {a.customer_name}</p>
                          <p className="truncate opacity-80">{a.service_name}{view === "semana" ? ` · ${a.professional_name.split(" ")[0]}` : a.room_name ? ` · ${a.room_name}` : ""}</p>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {creating && <AppointmentForm initial={creating} onClose={() => setCreating(null)} />}
      {selected && <AppointmentDrawer id={selected} onClose={() => { setSelected(null); if (params.get("agendamento")) { params.delete("agendamento"); setParams(params, { replace: true }); } }} />}
      {blocking && <BlockForm day={day} onClose={() => setBlocking(false)} />}
    </div>
  );
}

function DayList({ appts, onOpen, onNew }: { appts: any[]; onOpen: (id: string) => void; onNew?: () => void }) {
  const sorted = [...appts].sort((a, b) => a.start_at.localeCompare(b.start_at));
  if (!sorted.length)
    return (
      <div className="card">
        <Empty title="Nenhum agendamento neste dia" action={onNew && <Button size="sm" icon={<CalendarPlus className="h-4 w-4" />} onClick={onNew}>Novo agendamento</Button>} />
      </div>
    );
  return (
    <ul className="space-y-2">
      {sorted.map((a) => (
        <li key={a.id}>
          <button onClick={() => onOpen(a.id)}
            className={clsx("card flex w-full items-center gap-3 !border-l-4 p-3 text-left transition hover:shadow-md", a.status === "cancelado" && "opacity-60")}
            style={{ borderLeftColor: a.professional_color || undefined }}>
            <span className="w-12 shrink-0 text-sm font-semibold tabular-nums">{time(a.start_at)}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">{a.customer_name}</span>
              <span className="block truncate text-xs text-slate-500 dark:text-slate-400">{a.service_name} · {a.professional_name}{a.room_name ? ` · ${a.room_name}` : ""}</span>
            </span>
            <StatusBadge status={a.status} />
          </button>
        </li>
      ))}
    </ul>
  );
}

function MonthGrid({ day, appts, onPickDay }: { day: string; appts: any[]; onPickDay: (d: string) => void }) {
  const first = monthStart(day);
  const gridStart = weekStart(first);
  const days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
  const today = isoDay();
  return (
    <div className="card overflow-hidden">
      <div className="grid grid-cols-7 border-b border-slate-100 text-center text-xs font-semibold text-slate-500 dark:border-slate-800">
        {["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"].map((d) => <div key={d} className="py-2">{d}</div>)}
      </div>
      <div className="grid grid-cols-7">
        {days.map((d) => {
          const list = appts.filter((a) => isoDay(new Date(a.start_at)) === d);
          const out = d.slice(0, 7) !== day.slice(0, 7);
          return (
            <button key={d} onClick={() => onPickDay(d)} className={clsx("min-h-[96px] border-b border-r border-slate-100 p-1.5 text-left align-top transition hover:bg-brand-50/50 dark:border-slate-800 dark:hover:bg-slate-800/40", out && "opacity-40")}>
              <span className={clsx("inline-flex h-6 w-6 items-center justify-center rounded-full text-xs", d === today && "bg-brand-600 font-semibold text-white")}>{Number(d.slice(8))}</span>
              <div className="mt-1 space-y-0.5">
                {list.slice(0, 3).map((a) => (
                  <p key={a.id} className={clsx("truncate rounded border-l-2 px-1 text-xs", STATUS_STYLE[a.status])}>{time(a.start_at)} {a.customer_name}</p>
                ))}
                {list.length > 3 && <p className="text-xs text-slate-500 dark:text-slate-400">+{list.length - 3} atendimento(s)</p>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function AppointmentForm({ initial, editing, onClose }: { initial?: { day: string; time: string; professional_id?: string; customer?: any }; editing?: any; onClose: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const { professionals, rooms, services, methods } = useLookups();
  const startLocal = editing ? { day: isoDay(new Date(editing.start_at)), time: time(editing.start_at) } : initial!;
  const [customer, setCustomer] = useState<any>(editing ? { id: editing.customer_id, full_name: editing.customer_name } : initial?.customer || null);
  const [f, setF] = useState<any>(() => ({
    service_id: editing?.service_id || "", professional_id: editing?.professional_id || initial?.professional_id || "",
    room_id: editing?.room_id || "", day: startLocal.day, time: startLocal.time, duration_minutes: editing?.duration_minutes || "",
    price: editing?.price ?? "", discount: editing?.discount ?? 0, payment_method_id: editing?.payment_method_id || "",
    notes: editing?.notes || "", is_evaluation: false, package_id: editing?.package_id || "", recurrence: "", occurrences: 4,
    skip_conflicts: false, override_hours: false, reason: "",
  }));
  const [check, setCheck] = useState<any>(null);
  const [slots, setSlots] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const service = services.find((s) => s.id === f.service_id);
  const allowedProfs = service?.professional_ids?.length ? professionals.filter((p) => service.professional_ids.includes(p.id)) : professionals;
  const pkgs = useGet<any[]>(["packages", "customer", customer?.id], customer && !editing ? "/packages" : null, { customer_id: customer?.id, status: "ativo" });
  const customerPkgs = (pkgs.data || []).filter((p) => p.service_id === f.service_id && p.sessions_remaining - p.reserved > 0);
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (service && !editing) setF((x: any) => ({ ...x, duration_minutes: service.duration_minutes, price: service.price }));
  }, [service, editing]);
  const durationNum = Number(f.duration_minutes) || 0;
  const validDuration = durationNum >= 5 && durationNum <= 600 ? durationNum : undefined;
  useEffect(() => {
    if (!f.service_id || !f.professional_id || !f.day) return setSlots([]);
    let alive = true;
    // horários livres calculados com a duração escolhida (não só a padrão do serviço)
    const t = setTimeout(() => get("/agenda/availability", {
      day: f.day, service_id: f.service_id, professional_id: f.professional_id, room_id: f.room_id || undefined,
      duration_minutes: validDuration,
    }).then((r) => alive && setSlots(r.slots)).catch(() => alive && setSlots([])), 250);
    return () => { alive = false; clearTimeout(t); };
  }, [f.service_id, f.professional_id, f.room_id, f.day, validDuration]);
  const endTime = (() => {
    if (!f.time || !validDuration) return "";
    const [h, m] = f.time.split(":").map(Number);
    const total = h * 60 + m + validDuration;
    return `${String(Math.floor(total / 60) % 24).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
  })();
  const bump = (delta: number) => set("duration_minutes", Math.min(600, Math.max(5, (durationNum || service?.duration_minutes || 60) + delta)));
  useEffect(() => {
    if (!customer || !f.service_id || !f.professional_id || !f.day || !f.time) return setCheck(null);
    const t = setTimeout(() => {
      post("/agenda/check", { customer_id: customer.id, service_id: f.service_id, professional_id: f.professional_id, room_id: f.room_id || null,
        start_at: localToIso(f.day, f.time), duration_minutes: Number(f.duration_minutes) || null })
        .then((r) => setCheck({ ...r, conflicts: r.conflicts.filter((c: any) => c.appointment_id !== editing?.id) }))
        .catch(() => setCheck(null));
    }, 300);
    return () => clearTimeout(t);
  }, [customer, f.service_id, f.professional_id, f.room_id, f.day, f.time, f.duration_minutes, editing]);

  async function submit() {
    setBusy(true);
    try {
      const start_at = localToIso(f.day, f.time);
      if (editing) {
        await put(`/agenda/appointments/${editing.id}`, {
          start_at, professional_id: f.professional_id, room_id: f.room_id || null, duration_minutes: Number(f.duration_minutes),
          price: String(f.price || 0), discount: String(f.discount || 0), payment_method_id: f.payment_method_id || null, notes: f.notes || null,
          reason: f.reason || null, override_hours: f.override_hours,
        });
        toast.success("Agendamento atualizado.");
      } else {
        const r = await post("/agenda/appointments", {
          customer_id: customer.id, service_id: f.service_id, professional_id: f.professional_id, room_id: f.room_id || null, start_at,
          duration_minutes: Number(f.duration_minutes) || null, price: f.package_id ? null : String(f.price || 0), discount: String(f.discount || 0),
          payment_method_id: f.payment_method_id || null, notes: f.notes || null, is_evaluation: f.is_evaluation, package_id: f.package_id || null,
          recurrence: f.recurrence || null, occurrences: f.recurrence ? Number(f.occurrences) : 1, skip_conflicts: f.skip_conflicts, override_hours: f.override_hours,
        });
        toast.success(r.message);
      }
      window.dispatchEvent(new Event("cs:agenda-changed"));
      onClose();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }
  const ok = customer && f.service_id && f.professional_id && f.day && f.time;
  return (
    <Modal open onClose={onClose} title={editing ? "Editar / remarcar agendamento" : "Novo agendamento"} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={busy} disabled={!ok} onClick={submit}>{editing ? "Salvar alterações" : "Agendar"}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-6">
        <Field label="Cliente" required className="sm:col-span-6">
          {editing ? <Input value={editing.customer_name} disabled /> : <CustomerPicker value={customer} onChange={setCustomer} />}
        </Field>
        <Field label="Serviço" required className="sm:col-span-3">
          <Select value={f.service_id} onChange={(e) => set("service_id", e.target.value)} disabled={!!editing}>
            <option value="">Selecione</option>
            {services.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.duration_minutes} min</option>)}
          </Select>
        </Field>
        <Field label="Profissional" required className="sm:col-span-3">
          <Select value={f.professional_id} onChange={(e) => set("professional_id", e.target.value)}>
            <option value="">Selecione</option>
            {allowedProfs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        <Field label="Data" required className="sm:col-span-2"><Input type="date" value={f.day} onChange={(e) => set("day", e.target.value)} /></Field>
        <Field label="Horário" required className="sm:col-span-2"><Input type="time" step={300} value={f.time} onChange={(e) => set("time", e.target.value)} /></Field>
        <Field label="Duração (min)" className="sm:col-span-2"
          hint={endTime ? `Termina às ${endTime}${service && validDuration && validDuration !== service.duration_minutes ? ` · padrão do serviço: ${service.duration_minutes} min` : ""}` : undefined}>
          <div className="flex items-center gap-1">
            <Button type="button" variant="secondary" className="h-11 w-11 shrink-0 !p-0" aria-label="Diminuir 5 minutos" onClick={() => bump(-5)}>−</Button>
            <Input type="number" inputMode="numeric" min={5} max={600} step={5} className="text-center" value={f.duration_minutes}
              onChange={(e) => set("duration_minutes", e.target.value)} />
            <Button type="button" variant="secondary" className="h-11 w-11 shrink-0 !p-0" aria-label="Aumentar 5 minutos" onClick={() => bump(5)}>+</Button>
          </div>
        </Field>
        {slots.length > 0 && (
          <div className="sm:col-span-6">
            <p className="label">Horários livres neste dia</p>
            <div className="flex flex-wrap gap-1.5">
              {slots.slice(0, 24).map((s) => (
                <button key={s} type="button" onClick={() => set("time", time(s))}
                  className={clsx("rounded-lg border px-2 py-1 text-xs", f.time === time(s) ? "border-brand-600 bg-brand-600 text-white" : "border-slate-200 hover:border-brand-600 dark:border-slate-700")}>{time(s)}</button>
              ))}
            </div>
          </div>
        )}
        <Field label="Sala" className="sm:col-span-2">
          <Select value={f.room_id} onChange={(e) => set("room_id", e.target.value)}>
            <option value="">Sem sala</option>
            {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </Select>
        </Field>
        {!editing && customerPkgs.length > 0 && (
          <Field label="Usar pacote" className="sm:col-span-4" hint="A sessão só é baixada quando o atendimento for concluído.">
            <Select value={f.package_id} onChange={(e) => set("package_id", e.target.value)}>
              <option value="">Não usar pacote (cobrança avulsa)</option>
              {customerPkgs.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.sessions_remaining - p.reserved} sessão(ões) livre(s)</option>)}
            </Select>
          </Field>
        )}
        {!f.package_id && !(editing?.package_id) && (
          <>
            <Field label="Valor (R$)" className="sm:col-span-2"><Input type="number" step="0.01" min={0} value={f.price} onChange={(e) => set("price", e.target.value)} /></Field>
            <Field label="Desconto (R$)" className="sm:col-span-2"><Input type="number" step="0.01" min={0} value={f.discount} onChange={(e) => set("discount", e.target.value)} /></Field>
            <Field label="Forma de pagamento prevista" className="sm:col-span-2">
              <Select value={f.payment_method_id} onChange={(e) => set("payment_method_id", e.target.value)}>
                <option value="">—</option>{methods.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </Select>
            </Field>
          </>
        )}
        <Field label="Observações" className="sm:col-span-6"><Textarea value={f.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Informações operacionais (não registre dados de saúde aqui)." /></Field>
        {editing ? (
          <Field label="Motivo da alteração" className="sm:col-span-6"><Input value={f.reason} onChange={(e) => set("reason", e.target.value)} /></Field>
        ) : (
          <div className="grid gap-3 sm:col-span-6 sm:grid-cols-3">
            <Checkbox label="Avaliação inicial" checked={f.is_evaluation} onChange={(v) => set("is_evaluation", v)} />
            <Field label="Repetir">
              <Select value={f.recurrence} onChange={(e) => set("recurrence", e.target.value)}>
                <option value="">Não repetir</option><option value="semanal">Semanalmente</option><option value="quinzenal">Quinzenalmente</option><option value="mensal">Mensalmente</option>
              </Select>
            </Field>
            {f.recurrence && <Field label="Ocorrências"><Input type="number" min={2} max={52} value={f.occurrences} onChange={(e) => set("occurrences", e.target.value)} /></Field>}
            {f.recurrence && <Checkbox label="Pular datas com conflito" checked={f.skip_conflicts} onChange={(v) => set("skip_conflicts", v)} />}
          </div>
        )}
        {can("agenda.override") && (
          <div className="sm:col-span-6"><Checkbox label="Permitir fora do horário de funcionamento (exceção autorizada)" checked={f.override_hours} onChange={(v) => set("override_hours", v)} /></div>
        )}
        {check && !check.ok && (
          <div className="space-y-1 sm:col-span-6">
            {check.hours_problems.map((p: string) => <Alert key={p} kind="warning">{p}</Alert>)}
            {check.conflicts.map((c: any, i: number) => <Alert key={i} kind="danger">{c.message}</Alert>)}
          </div>
        )}
        {check && check.ok && <div className="sm:col-span-6"><Alert kind="success">Horário disponível.</Alert></div>}
      </div>
    </Modal>
  );
}

/** Recarrega listas da agenda quando um agendamento muda. */
function useRefreshOnEvent() {
  const qc = useQueryClient();
  useEffect(() => {
    const h = () => ["appointments", "dashboard", "blocks", "appointment", "packages"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    window.addEventListener("cs:agenda-changed", h);
    return () => window.removeEventListener("cs:agenda-changed", h);
  }, [qc]);
}

function AppointmentDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const { methods } = useLookups();
  const q = useGet<any>(["appointment", id], `/agenda/appointments/${id}`);
  const [editing, setEditing] = useState(false);
  const [action, setAction] = useState<null | "cancelar" | "concluir">(null);
  const [reason, setReason] = useState("");
  const [pay, setPay] = useState({ enabled: false, amount: "", method: "" });
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("detalhes");
  const a = q.data?.appointment;
  async function run(act: string, extra: any = {}) {
    setBusy(true);
    try {
      await post(`/agenda/appointments/${id}/status`, { action: act, ...extra });
      toast.success({ confirmar: "Presença confirmada.", iniciar: "Atendimento iniciado.", concluir: "Atendimento concluído.", falta: "Falta registrada.", cancelar: "Agendamento cancelado." }[act] || "Atualizado.");
      setAction(null);
      q.refetch();
      window.dispatchEvent(new Event("cs:agenda-changed"));
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }
  const active = a && ["agendado", "confirmado"].includes(a.status);
  return (
    <Drawer open onClose={onClose} title="Agendamento">
      {!a ? <p className="text-sm text-slate-500">Carregando...</p> : (
        <div className="space-y-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-lg font-semibold">{a.customer_name}</p>
              <p className="text-sm text-slate-500">{a.service_name} · {a.duration_minutes} min</p>
            </div>
            <StatusBadge status={a.status} />
          </div>
          <Tabs value={tab} onChange={setTab} tabs={[{ key: "detalhes", label: "Detalhes" }, { key: "historico", label: "Histórico" }]} />
          {tab === "detalhes" ? (
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div><dt className="label">Início</dt><dd>{dateTime(a.start_at)}</dd></div>
              <div><dt className="label">Término</dt><dd>{time(a.end_at)}</dd></div>
              <div><dt className="label">Profissional</dt><dd>{a.professional_name}</dd></div>
              <div><dt className="label">Sala</dt><dd>{a.room_name || "—"}</dd></div>
              <div><dt className="label">Valor</dt><dd>{a.package_id ? "Coberto por pacote" : money(a.price - a.discount)}</dd></div>
              <div><dt className="label">Cobrança</dt><dd>{a.receivable_status ? <StatusBadge status={a.receivable_status} /> : "—"}</dd></div>
              {a.notes && <div className="col-span-2"><dt className="label">Observações</dt><dd className="whitespace-pre-wrap">{a.notes}</dd></div>}
              {a.cancel_reason && <div className="col-span-2"><dt className="label">Motivo do cancelamento</dt><dd>{a.cancel_reason}</dd></div>}
            </dl>
          ) : (
            <ol className="space-y-2 text-sm">
              {q.data.history.map((h: any, i: number) => (
                <li key={i} className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/50">
                  <p className="font-medium capitalize">{h.action} <span className="text-xs font-normal text-slate-500">· {dateTime(h.changed_at)}</span></p>
                  {h.old_start_at && <p className="text-xs text-slate-500">De {dateTime(h.old_start_at)} para {dateTime(h.new_start_at)}</p>}
                  {h.reason && <p className="text-xs text-slate-500">{h.reason}</p>}
                </li>
              ))}
            </ol>
          )}
          <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
            {can("agenda.write") && a.status === "agendado" && <Button size="sm" variant="secondary" loading={busy} onClick={() => run("confirmar")}>Confirmar presença</Button>}
            {active && <Button size="sm" variant="secondary" loading={busy} onClick={() => run("iniciar")}>Iniciar atendimento</Button>}
            {(active || a.status === "em_atendimento") && <Button size="sm" loading={busy} onClick={() => { setPay({ enabled: false, amount: String(a.price - a.discount), method: methods[0]?.id || "" }); setAction("concluir"); }}>Finalizar atendimento</Button>}
            {can("agenda.write") && active && <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>Editar / remarcar</Button>}
            {can("agenda.write") && active && <Button size="sm" variant="secondary" loading={busy} onClick={() => run("falta")}>Registrar falta</Button>}
            {can("agenda.write") && active && <Button size="sm" variant="danger" onClick={() => { setReason(""); setAction("cancelar"); }}>Cancelar</Button>}
            {can("clinical.read") && ["em_atendimento", "concluido"].includes(a.status) && <Button size="sm" variant="ghost" onClick={() => navigate(`/atendimentos?agendamento=${a.id}&cliente=${a.customer_id}`)}>Ficha do atendimento</Button>}
            {can("customers.read") && <Button size="sm" variant="ghost" onClick={() => navigate(`/clientes/${a.customer_id}`)}>Perfil do cliente</Button>}
            {can("finance.payments") && a.receivable_id && a.receivable_status !== "pago" && <Button size="sm" variant="ghost" onClick={() => navigate(`/financeiro?aba=receber&q=${encodeURIComponent(a.customer_name)}`)}>Receber pagamento</Button>}
          </div>
        </div>
      )}
      {editing && a && <AppointmentForm editing={a} onClose={() => { setEditing(false); q.refetch(); }} />}
      <Modal open={action === "cancelar"} onClose={() => setAction(null)} title="Cancelar agendamento" size="sm"
        footer={<><Button variant="secondary" onClick={() => setAction(null)}>Voltar</Button><Button variant="danger" loading={busy} disabled={reason.trim().length < 3} onClick={() => run("cancelar", { reason })}>Cancelar agendamento</Button></>}>
        <Field label="Motivo" required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} autoFocus /></Field>
        {a?.package_id && <p className="mt-2 text-xs text-slate-500">Se o pacote tiver regra de cancelamento tardio, a sessão poderá ser descontada.</p>}
      </Modal>
      <Modal open={action === "concluir"} onClose={() => setAction(null)} title="Finalizar atendimento" size="sm"
        footer={<><Button variant="secondary" onClick={() => setAction(null)}>Voltar</Button>
          <Button loading={busy} onClick={() => run("concluir", pay.enabled ? { payment: { amount: String(pay.amount), payment_method_id: pay.method } } : {})}>Concluir</Button></>}>
        <div className="space-y-3 text-sm">
          <p>{a?.package_id ? "A sessão será baixada do pacote do cliente." : "Será gerada a conta a receber deste atendimento."}</p>
          {!a?.package_id && a && a.price - a.discount > 0 && can("finance.payments") && (
            <>
              <Checkbox label="Registrar o pagamento agora" checked={pay.enabled} onChange={(v) => setPay({ ...pay, enabled: v })} />
              {pay.enabled && (
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Valor"><Input type="number" step="0.01" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></Field>
                  <Field label="Forma"><Select value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}>{methods.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field>
                </div>
              )}
            </>
          )}
        </div>
      </Modal>
    </Drawer>
  );
}

function BlockForm({ day, onClose }: { day: string; onClose: () => void }) {
  const { professionals, rooms } = useLookups();
  const [f, setF] = useState({ scope: "profissional", professional_id: "", room_id: "", day, start: "12:00", end: "13:00", end_day: day, reason: "" });
  const list = useGet<any[]>(["blocks"], "/agenda/blocks", { start: day, end: addDays(day, 30) });
  const save = useAction(() => post("/agenda/blocks", {
    professional_id: f.scope === "profissional" ? f.professional_id || null : null, room_id: f.scope === "sala" ? f.room_id || null : null,
    start_at: localToIso(f.day, f.start), end_at: localToIso(f.end_day, f.end), reason: f.reason || null,
  }), { success: "Horário bloqueado.", invalidate: [["blocks"]] });
  const remove = useAction((id: string) => del(`/agenda/blocks/${id}`), { success: "Bloqueio removido.", invalidate: [["blocks"]] });
  return (
    <Modal open onClose={onClose} title="Bloqueio de horários" footer={<><Button variant="secondary" onClick={onClose}>Fechar</Button><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Bloquear</Button></>}>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Bloquear" className="sm:col-span-2">
          <Select value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })}>
            <option value="profissional">Um profissional</option><option value="sala">Uma sala</option><option value="clinica">Clínica inteira</option>
          </Select>
        </Field>
        {f.scope === "profissional" && <Field label="Profissional" className="sm:col-span-2"><Select value={f.professional_id} onChange={(e) => setF({ ...f, professional_id: e.target.value })}><option value="">Selecione</option>{professionals.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>}
        {f.scope === "sala" && <Field label="Sala" className="sm:col-span-2"><Select value={f.room_id} onChange={(e) => setF({ ...f, room_id: e.target.value })}><option value="">Selecione</option>{rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select></Field>}
        <Field label="Início (data)"><Input type="date" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value, end_day: e.target.value > f.end_day ? e.target.value : f.end_day })} /></Field>
        <Field label="Hora"><Input type="time" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></Field>
        <Field label="Fim (data)"><Input type="date" value={f.end_day} onChange={(e) => setF({ ...f, end_day: e.target.value })} /></Field>
        <Field label="Hora"><Input type="time" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></Field>
        <Field label="Motivo" className="sm:col-span-4"><Input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} placeholder="Ex.: curso, manutenção, férias" /></Field>
      </div>
      <h4 className="mb-2 mt-5 text-sm font-semibold">Próximos bloqueios</h4>
      {(list.data || []).length === 0 ? <p className="text-sm text-slate-500">Nenhum bloqueio nos próximos 30 dias.</p> : (
        <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {(list.data || []).map((b) => (
            <li key={b.id} className="flex items-center justify-between py-2">
              <span>{dateTime(b.start_at)} → {dateTime(b.end_at)} · {b.professional_id ? professionals.find((p) => p.id === b.professional_id)?.name : b.room_id ? rooms.find((r) => r.id === b.room_id)?.name : "Clínica"} {b.reason && `· ${b.reason}`}</span>
              <Button size="sm" variant="ghost" onClick={() => remove.mutate(b.id)}>Remover</Button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
