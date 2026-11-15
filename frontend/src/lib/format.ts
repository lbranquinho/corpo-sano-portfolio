const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const TZ = "America/Sao_Paulo";

export const money = (v: number | string | null | undefined) =>
  v === null || v === undefined || v === "" ? "—" : BRL.format(Number(v));

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${v.toLocaleString("pt-BR")}%`);

export function date(v: string | Date | null | undefined) {
  if (!v) return "—";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v)) {
    const [y, m, d] = v.split("-");
    return `${d}/${m}/${y}`;
  }
  return new Date(v).toLocaleDateString("pt-BR", { timeZone: TZ });
}

export function dateTime(v: string | Date | null | undefined) {
  if (!v) return "—";
  return new Date(v).toLocaleString("pt-BR", { timeZone: TZ, dateStyle: "short", timeStyle: "short" });
}

export function time(v: string | Date | null | undefined) {
  if (!v) return "—";
  return new Date(v).toLocaleTimeString("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
}

export const digits = (v: string | null | undefined) => (v || "").replace(/\D/g, "");

export function cpf(v: string | null | undefined) {
  const d = digits(v);
  if (d.length !== 11) return v || "—";
  return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
}

export function cnpj(v: string | null | undefined) {
  const d = digits(v);
  if (d.length !== 14) return v || "—";
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
}

export const doc = (v: string | null | undefined) => (digits(v).length === 14 ? cnpj(v) : digits(v).length === 11 ? cpf(v) : v || "—");

export function phone(v: string | null | undefined) {
  let d = digits(v);
  if (!d) return "—";
  if (d.startsWith("55") && d.length >= 12) d = d.slice(2);
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return v || "—";
}

/** Data local (fuso da clínica) em AAAA-MM-DD. */
export function isoDay(d: Date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  return parts; // en-CA => AAAA-MM-DD
}

export function addDays(day: string, n: number) {
  const [y, m, d] = day.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + n));
  return dt.toISOString().slice(0, 10);
}

export function monthStart(day: string = isoDay()) {
  return day.slice(0, 8) + "01";
}

export function monthEnd(day: string = isoDay()) {
  const [y, m] = day.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return `${day.slice(0, 8)}${String(last).padStart(2, "0")}`;
}

export function weekdayOf(day: string) {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = domingo
}

/** Converte "AAAA-MM-DD" + "HH:MM" (horário da clínica) para ISO com fuso -03:00/-02:00 calculado. */
export function localToIso(day: string, hhmm: string) {
  const [y, m, d] = day.split("-").map(Number);
  const [hh, mm] = hhmm.split(":").map(Number);
  const guess = new Date(Date.UTC(y, m - 1, d, hh, mm));
  const asLocal = new Date(guess.toLocaleString("en-US", { timeZone: TZ }));
  const asUtc = new Date(guess.toLocaleString("en-US", { timeZone: "UTC" }));
  const offsetMin = (asUtc.getTime() - asLocal.getTime()) / 60000;
  return new Date(guess.getTime() + offsetMin * 60000).toISOString();
}

/** Minutos desde 00:00 no fuso da clínica. */
export function minutesOfDay(v: string | Date) {
  const s = new Date(v).toLocaleTimeString("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
  const [h, m] = s.split(":").map(Number);
  return h * 60 + m;
}

export const WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];

export const STATUS_LABEL: Record<string, string> = {
  agendado: "Agendado",
  confirmado: "Confirmado",
  em_atendimento: "Em atendimento",
  concluido: "Concluído",
  cancelado: "Cancelado",
  falta: "Falta",
  aberto: "Em aberto",
  parcial: "Parcial",
  pago: "Pago",
  ativo: "Ativo",
  expirado: "Expirado",
  rascunho: "Rascunho",
  aguardando_transmissao: "Aguardando transmissão",
  transmitindo: "Transmitindo",
  autorizada: "Autorizada",
  rejeitada: "Rejeitada",
  cancelada: "Cancelada",
  substituida: "Substituída",
  pendente: "Pendente",
  em_preparacao: "Em preparação",
  enviado: "Enviado",
  atrasado: "Atrasado",
  nao_aplicavel: "Não aplicável",
  estimado: "Estimado",
  validado: "Validado",
  enviando: "Enviando",
  enviada: "Enviada",
  entregue: "Entregue",
  lida: "Lida",
  falhou: "Falhou",
  bloqueada: "Bloqueada",
  recebida: "Recebida",
  sucesso: "Sucesso",
  falha: "Falha",
  executando: "Executando",
  concluida: "Concluída",
  inativo: "Inativo",
  anonimizado: "Anonimizado",
};

export const label = (s: string | null | undefined) => (s ? STATUS_LABEL[s] || s : "—");
