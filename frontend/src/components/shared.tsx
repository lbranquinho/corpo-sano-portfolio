import { Search, UserPlus } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { del, get, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cpf as fmtCpf, phone as fmtPhone } from "../lib/format";
import { useAction, useGet } from "../lib/hooks";
import { Button, Checkbox, ConfirmButton, DataTable, Field, Input, Modal, Select, Textarea, useToast, type Column } from "./ui";

/* ------------------------------------------------------------------ Busca de cliente */
export function CustomerPicker({ value, onChange, allowCreate = true }: {
  value: { id: string; full_name: string } | null; onChange: (c: { id: string; full_name: string } | null) => void; allowCreate?: boolean;
}) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const { can } = useAuth();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (q.trim().length < 2) return setItems([]);
    const t = setTimeout(() => get("/customers", { q, page_size: 8 }).then((r) => setItems(r.items)).catch(() => setItems([])), 220);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const h = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  if (value) {
    return (
      <div className="flex items-center justify-between rounded-xl border border-brand-100 bg-brand-50 px-3 py-2 text-sm dark:border-brand-900 dark:bg-brand-900/20">
        <span className="font-medium">{value.full_name}</span>
        <button type="button" className="text-xs text-brand-600" onClick={() => onChange(null)}>trocar</button>
      </div>
    );
  }
  return (
    <div ref={ref} className="relative">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <Input className="pl-9" placeholder="Nome, telefone ou CPF" value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} />
      {open && (q.length >= 2 || allowCreate) && (
        <div className="card absolute left-0 right-0 top-11 z-50 max-h-72 overflow-y-auto p-1">
          {items.map((c) => (
            <button type="button" key={c.id} className="block w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
              onClick={() => { onChange({ id: c.id, full_name: c.full_name }); setOpen(false); setQ(""); }}>
              <span className="font-medium">{c.full_name}</span>
              <span className="ml-2 text-xs text-slate-500">{fmtPhone(c.whatsapp || c.phone)} {c.cpf ? `· ${fmtCpf(c.cpf)}` : ""}</span>
            </button>
          ))}
          {q.length >= 2 && items.length === 0 && <p className="px-3 py-2 text-sm text-slate-500">Nenhum cliente encontrado.</p>}
          {allowCreate && can("customers.write") && (
            <button type="button" className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-brand-600 hover:bg-brand-50 dark:hover:bg-slate-800"
              onClick={() => { setCreating(true); setOpen(false); }}>
              <UserPlus className="h-4 w-4" /> Cadastrar novo cliente {q && `"${q}"`}
            </button>
          )}
        </div>
      )}
      <CustomerForm open={creating} onClose={() => setCreating(false)} initialName={q}
        onSaved={(c) => { onChange({ id: c.id, full_name: c.full_name }); setCreating(false); setQ(""); }} />
    </div>
  );
}

/* ------------------------------------------------------------------ Formulário de cliente */
const EMPTY = {
  full_name: "", cpf: "", birth_date: "", phone: "", whatsapp: "", email: "", zip_code: "", street: "", number: "", complement: "",
  district: "", city: "", state: "", ibge_code: "", source: "", notes: "", preferences: "", status: "ativo",
};
const SOURCES = ["Indicação", "Instagram", "Google", "WhatsApp", "Site", "Passagem em frente", "Convênio/parceria", "Outro"];

export function CustomerForm({ open, onClose, customer, onSaved, initialName = "" }: {
  open: boolean; onClose: () => void; customer?: any; onSaved?: (c: any) => void; initialName?: string;
}) {
  const [f, setF] = useState<any>(EMPTY);
  const [consents, setConsents] = useState({ tratamento_dados: true, whatsapp_transacional: true, whatsapp_marketing: false, email_marketing: false });
  const [busy, setBusy] = useState(false);
  const [cepBusy, setCepBusy] = useState(false);
  const toast = useToast();
  useEffect(() => {
    if (!open) return;
    setF(customer ? { ...EMPTY, ...Object.fromEntries(Object.entries(customer).map(([k, v]) => [k, v ?? ""])) } : { ...EMPTY, full_name: initialName });
  }, [open, customer, initialName]);
  const set = (k: string) => (e: any) => setF((x: any) => ({ ...x, [k]: e.target.value }));
  async function lookupCep() {
    const cep = (f.zip_code || "").replace(/\D/g, "");
    if (cep.length !== 8) return;
    setCepBusy(true);
    try {
      // consulta pública de CEP (ViaCEP) — apenas o CEP é enviado
      const r = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
      const d = await r.json();
      if (!d.erro) setF((x: any) => ({ ...x, street: d.logradouro || x.street, district: d.bairro || x.district, city: d.localidade || x.city, state: d.uf || x.state, ibge_code: d.ibge || x.ibge_code }));
    } catch {
      /* consulta opcional */
    } finally {
      setCepBusy(false);
    }
  }
  async function save() {
    setBusy(true);
    try {
      const body: any = Object.fromEntries(Object.entries(f).filter(([k]) => k in EMPTY).map(([k, v]) => [k, v === "" ? null : v]));
      body.status = f.status || "ativo";
      const saved = customer ? await put(`/customers/${customer.id}`, body) : await post("/customers", { ...body, consents });
      toast.success(customer ? "Cadastro atualizado." : "Cliente cadastrado.");
      onSaved?.(saved);
      onClose();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} title={customer ? "Editar cliente" : "Novo cliente"} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={busy} onClick={save} disabled={f.full_name.trim().length < 3}>Salvar</Button></>}>
      <div className="grid gap-3 sm:grid-cols-6">
        <Field label="Nome completo" required className="sm:col-span-4"><Input value={f.full_name} onChange={set("full_name")} autoFocus /></Field>
        <Field label="CPF" hint="Opcional; necessário para NFS-e com tomador identificado." className="sm:col-span-2"><Input value={f.cpf} onChange={set("cpf")} inputMode="numeric" /></Field>
        <Field label="Data de nascimento" className="sm:col-span-2"><Input type="date" value={f.birth_date} onChange={set("birth_date")} /></Field>
        <Field label="Telefone" className="sm:col-span-2"><Input value={f.phone} onChange={set("phone")} placeholder="(11) 99999-9999" /></Field>
        <Field label="WhatsApp" hint="Se vazio, usa o telefone." className="sm:col-span-2"><Input value={f.whatsapp} onChange={set("whatsapp")} /></Field>
        <Field label="E-mail" className="sm:col-span-3"><Input type="email" value={f.email} onChange={set("email")} /></Field>
        <Field label="Origem do contato" className="sm:col-span-3">
          <Select value={f.source} onChange={set("source")}><option value="">—</option>{SOURCES.map((s) => <option key={s}>{s}</option>)}</Select>
        </Field>
        <Field label="CEP" className="sm:col-span-2"><Input value={f.zip_code} onChange={set("zip_code")} onBlur={lookupCep} placeholder={cepBusy ? "Consultando..." : ""} /></Field>
        <Field label="Endereço" className="sm:col-span-3"><Input value={f.street} onChange={set("street")} /></Field>
        <Field label="Número" className="sm:col-span-1"><Input value={f.number} onChange={set("number")} /></Field>
        <Field label="Complemento" className="sm:col-span-2"><Input value={f.complement} onChange={set("complement")} /></Field>
        <Field label="Bairro" className="sm:col-span-2"><Input value={f.district} onChange={set("district")} /></Field>
        <Field label="Cidade" className="sm:col-span-1"><Input value={f.city} onChange={set("city")} /></Field>
        <Field label="UF" className="sm:col-span-1"><Input value={f.state} onChange={set("state")} maxLength={2} /></Field>
        <Field label="Preferências" className="sm:col-span-3"><Textarea value={f.preferences} onChange={set("preferences")} placeholder="Pressão preferida, música, temperatura, horários..." /></Field>
        <Field label="Observações" className="sm:col-span-3"><Textarea value={f.notes} onChange={set("notes")} /></Field>
        {customer && (
          <Field label="Situação" className="sm:col-span-2">
            <Select value={f.status} onChange={set("status")}><option value="ativo">Ativo</option><option value="inativo">Inativo</option></Select>
          </Field>
        )}
        {!customer && (
          <div className="space-y-2 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/50 sm:col-span-6">
            <p className="text-xs font-semibold uppercase text-slate-500">Consentimentos (LGPD) — confirme com o cliente</p>
            <Checkbox label="Tratamento de dados pessoais para atendimento" checked={consents.tratamento_dados} onChange={(v) => setConsents({ ...consents, tratamento_dados: v })} />
            <Checkbox label="WhatsApp: confirmações e lembretes de agendamento" checked={consents.whatsapp_transacional} onChange={(v) => setConsents({ ...consents, whatsapp_transacional: v })} />
            <Checkbox label="WhatsApp: aniversário, convites de retorno e campanhas" checked={consents.whatsapp_marketing} onChange={(v) => setConsents({ ...consents, whatsapp_marketing: v })} />
            <Checkbox label="E-mail: comunicações promocionais" checked={consents.email_marketing} onChange={(v) => setConsents({ ...consents, email_marketing: v })} />
          </div>
        )}
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------------ CRUD genérico */
const SPAN: Record<number, string> = { 1: "sm:col-span-1", 2: "sm:col-span-2", 3: "sm:col-span-3", 4: "sm:col-span-4", 5: "sm:col-span-5", 6: "sm:col-span-6" };

export type CrudField = {
  key: string; label: string; type?: "text" | "number" | "date" | "color" | "select" | "checkbox" | "textarea" | "money";
  options?: { value: string; label: string }[]; required?: boolean; hint?: string; span?: number; defaultValue?: any;
};

export function CrudList({ title, path, queryKey, columns, fields, canWrite, emptyText, transform }: {
  title: string; path: string; queryKey: string; columns: Column<any>[]; fields: CrudField[]; canWrite: boolean; emptyText?: string;
  transform?: (v: any) => any;
}) {
  const list = useGet<any[]>([queryKey], path);
  const [editing, setEditing] = useState<any | null>(null);
  const [form, setForm] = useState<any>({});
  const save = useAction((v: any) => (v.id ? put(`${path}/${v.id}`, v.body) : post(path, v.body)), {
    success: "Registro salvo.", invalidate: [[queryKey]], onDone: () => setEditing(null),
  });
  const remove = useAction((id: string) => del(`${path}/${id}`), { invalidate: [[queryKey]] });
  const open = (row?: any) => {
    const init: any = {};
    fields.forEach((f) => (init[f.key] = row ? row[f.key] ?? "" : f.defaultValue ?? (f.type === "checkbox" ? false : "")));
    setForm(init);
    setEditing(row || {});
  };
  const cols: Column<any>[] = canWrite
    ? [...columns, {
        key: "_a", label: "", className: "w-1 text-right", render: (r) => (
          <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
            <Button size="sm" variant="ghost" onClick={() => open(r)}>Editar</Button>
            <ConfirmButton size="sm" message="Excluir este registro? Se estiver em uso, será apenas inativado." onConfirm={() => remove.mutateAsync(r.id)}>Excluir</ConfirmButton>
          </div>
        ) }]
    : columns;
  return (
    <div className="card">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <h3 className="text-sm font-semibold">{title}</h3>
        {canWrite && <Button size="sm" onClick={() => open()}>Adicionar</Button>}
      </div>
      <DataTable rows={list.data || []} columns={cols} empty={<p className="px-4 py-6 text-sm text-slate-500">{emptyText || "Nenhum registro."}</p>} />
      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing?.id ? `Editar — ${title}` : `Novo — ${title}`}
        footer={<><Button variant="secondary" onClick={() => setEditing(null)}>Cancelar</Button>
          <Button loading={save.isPending} onClick={() => {
            const body: any = {};
            fields.forEach((f) => {
              const v = form[f.key];
              body[f.key] = f.type === "checkbox" ? !!v : v === "" ? null : f.type === "number" ? Number(v) : v;
            });
            save.mutate({ id: editing?.id, body: transform ? transform(body) : body });
          }}>Salvar</Button></>}>
        <div className="grid gap-3 sm:grid-cols-6">
          {fields.map((f) => (
            <div key={f.key} className={SPAN[f.span || 3]}>
              {f.type === "checkbox" ? (
                <Checkbox label={f.label} hint={f.hint} checked={!!form[f.key]} onChange={(v) => setForm({ ...form, [f.key]: v })} />
              ) : (
                <Field label={f.label} hint={f.hint} required={f.required}>
                  {f.type === "select" ? (
                    <Select value={form[f.key] ?? ""} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}>
                      <option value="">—</option>
                      {f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </Select>
                  ) : f.type === "textarea" ? (
                    <Textarea value={form[f.key] ?? ""} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
                  ) : (
                    <Input type={f.type === "money" ? "number" : f.type || "text"} step={f.type === "money" ? "0.01" : undefined}
                      value={form[f.key] ?? ""} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
                  )}
                </Field>
              )}
            </div>
          ))}
        </div>
      </Modal>
    </div>
  );
}

export function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
        {actions}
      </div>
      {children}
    </div>
  );
}

/** Seletor de período (início/fim). */
export function PeriodPicker({ start, end, onChange }: { start: string; end: string; onChange: (s: string, e: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Input type="date" className="!w-auto" value={start} onChange={(e) => onChange(e.target.value, end)} aria-label="Início" />
      <span className="text-sm text-slate-500">até</span>
      <Input type="date" className="!w-auto" value={end} onChange={(e) => onChange(start, e.target.value)} aria-label="Fim" />
    </div>
  );
}
