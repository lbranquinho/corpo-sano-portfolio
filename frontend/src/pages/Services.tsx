import { useState } from "react";
import { CrudList } from "../components/shared";
import { Alert, Badge, Button, Card, Checkbox, ConfirmButton, DataTable, Field, Input, Modal, PageHeader, Select, Tabs, Textarea } from "../components/ui";
import { del, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { money } from "../lib/format";
import { useAction, useGet } from "../lib/hooks";

export default function Services() {
  const { can } = useAuth();
  const [tab, setTab] = useState("servicos");
  return (
    <div>
      <PageHeader title="Serviços e procedimentos" subtitle="Catálogo, categorias e planos de pacote. Códigos fiscais são configurados e validados pelo contador." />
      <Tabs value={tab} onChange={setTab} tabs={[{ key: "servicos", label: "Serviços" }, { key: "categorias", label: "Categorias" }, { key: "planos", label: "Planos de pacote" }]} />
      {tab === "servicos" && <ServiceList />}
      {tab === "categorias" && (
        <CrudList title="Categorias de serviço" path="/service-categories" queryKey="service-categories" canWrite={can("services.write")}
          columns={[{ key: "name", label: "Nome" }, { key: "description", label: "Descrição" },
            { key: "color", label: "Cor", render: (r) => <span className="inline-block h-4 w-4 rounded" style={{ background: r.color }} /> },
            { key: "is_active", label: "Ativa", render: (r) => (r.is_active ? "Sim" : "Não") }]}
          fields={[{ key: "name", label: "Nome", required: true }, { key: "color", label: "Cor", type: "color", defaultValue: "#2563EB" },
            { key: "description", label: "Descrição", span: 6 }, { key: "is_active", label: "Ativa", type: "checkbox", defaultValue: true }]} />
      )}
      {tab === "planos" && <PlanList />}
    </div>
  );
}

function ServiceList() {
  const { can } = useAuth();
  const services = useGet<any[]>(["services-all"], "/services");
  const cats = useGet<any[]>(["service-categories"], "/service-categories");
  const profs = useGet<any[]>(["professionals"], "/settings/professionals", { active: true });
  const codes = useGet<any[]>(["tax-codes"], "/tax-service-codes", undefined, can("fiscal.read") || can("services.read"));
  const suggestions = useGet<string[]>(["service-suggestions"], "/services/suggestions");
  const [editing, setEditing] = useState<any>(null);
  const remove = useAction((id: string) => del(`/services/${id}`), { invalidate: [["services-all"], ["services"]] });
  return (
    <>
      <Card padded={false} title="Serviços" actions={can("services.write") && <Button size="sm" onClick={() => setEditing({})}>Novo serviço</Button>}>
        <DataTable rows={services.data || []} onRowClick={can("services.write") ? setEditing : undefined} columns={[
          { key: "name", label: "Serviço", render: (r) => <span className="font-medium">{r.name}</span> },
          { key: "category_name", label: "Categoria", render: (r) => r.category_name || "—" },
          { key: "duration_minutes", label: "Duração", render: (r) => `${r.duration_minutes} min` + (r.buffer_minutes ? ` (+${r.buffer_minutes})` : "") },
          { key: "price", label: "Preço", render: (r) => money(r.price) },
          { key: "tax", label: "Código fiscal", render: (r) => r.tax_code_label ? <span className="text-xs">{r.tax_code_label} {r.tax_code_validated ? <Badge color="green">validado</Badge> : <Badge color="yellow">não validado</Badge>}</span> : <Badge color="gray">não definido</Badge> },
          { key: "pro", label: "Profissionais", render: (r) => r.professional_ids.length ? `${r.professional_ids.length} habilitado(s)` : "Todos" },
          { key: "is_active", label: "Status", render: (r) => <Badge color={r.is_active ? "green" : "gray"}>{r.is_active ? "Ativo" : "Inativo"}</Badge> },
          ...(can("services.write") ? [{ key: "a", label: "", render: (r: any) => <span onClick={(e) => e.stopPropagation()}>
            <ConfirmButton size="sm" message="Excluir o serviço? Se já foi utilizado, será apenas inativado." onConfirm={() => remove.mutateAsync(r.id)}>Excluir</ConfirmButton></span> }] : []),
        ]} />
      </Card>
      {editing && <ServiceForm service={editing} cats={cats.data || []} profs={profs.data || []} codes={codes.data || []} suggestions={suggestions.data || []} onClose={() => setEditing(null)} />}
    </>
  );
}

function ServiceForm({ service, cats, profs, codes, suggestions, onClose }: { service: any; cats: any[]; profs: any[]; codes: any[]; suggestions: string[]; onClose: () => void }) {
  const [f, setF] = useState<any>({
    name: service.name || "", description: service.description || "", category_id: service.category_id || "", duration_minutes: service.duration_minutes || 60,
    buffer_minutes: service.buffer_minutes || 0, price: service.price ?? "", tax_service_code_id: service.tax_service_code_id || "",
    nfse_description: service.nfse_description || "", professional_ids: service.professional_ids || [], is_active: service.is_active ?? true,
  });
  const save = useAction(() => {
    const body = { ...f, category_id: f.category_id || null, tax_service_code_id: f.tax_service_code_id || null, description: f.description || null,
      nfse_description: f.nfse_description || null, price: String(f.price || 0), duration_minutes: Number(f.duration_minutes), buffer_minutes: Number(f.buffer_minutes) };
    return service.id ? put(`/services/${service.id}`, body) : post("/services", body);
  }, { success: "Serviço salvo.", invalidate: [["services-all"], ["services"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title={service.id ? "Editar serviço" : "Novo serviço"} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={save.isPending} disabled={!f.name || f.price === ""} onClick={() => save.mutate(undefined)}>Salvar</Button></>}>
      <div className="grid gap-3 sm:grid-cols-6">
        <Field label="Nome" required className="sm:col-span-4"><Input list="svc-suggestions" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <datalist id="svc-suggestions">{suggestions.map((s) => <option key={s} value={s} />)}</datalist></Field>
        <Field label="Categoria" className="sm:col-span-2"><Select value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}><option value="">—</option>{cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
        <Field label="Duração (min)" required className="sm:col-span-2"><Input type="number" min={5} value={f.duration_minutes} onChange={(e) => setF({ ...f, duration_minutes: e.target.value })} /></Field>
        <Field label="Intervalo após (min)" hint="Preparação da sala/descanso" className="sm:col-span-2"><Input type="number" min={0} value={f.buffer_minutes} onChange={(e) => setF({ ...f, buffer_minutes: e.target.value })} /></Field>
        <Field label="Preço (R$)" required className="sm:col-span-2"><Input type="number" step="0.01" min={0} value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></Field>
        <Field label="Descrição" className="sm:col-span-6"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Código de serviço fiscal (NFS-e)" className="sm:col-span-3" hint="Cadastrado em Contábil > Cadastro fiscal; deve ser validado pelo contador.">
          <Select value={f.tax_service_code_id} onChange={(e) => setF({ ...f, tax_service_code_id: e.target.value })}>
            <option value="">Não definido</option>
            {codes.map((c) => <option key={c.id} value={c.id}>{c.national_code} — {c.description}{c.validated ? "" : " (não validado)"}</option>)}
          </Select>
        </Field>
        <Field label="Descrição padrão na nota" className="sm:col-span-3"><Input value={f.nfse_description} onChange={(e) => setF({ ...f, nfse_description: e.target.value })} /></Field>
        <div className="sm:col-span-6">
          <p className="label">Profissionais habilitados (nenhum marcado = todos)</p>
          <div className="flex flex-wrap gap-3">
            {profs.map((p) => <Checkbox key={p.id} label={p.name} checked={f.professional_ids.includes(p.id)}
              onChange={(v) => setF({ ...f, professional_ids: v ? [...f.professional_ids, p.id] : f.professional_ids.filter((x: string) => x !== p.id) })} />)}
          </div>
        </div>
        <div className="sm:col-span-6"><Checkbox label="Serviço ativo" checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} /></div>
        {codes.length === 0 && <div className="sm:col-span-6"><Alert kind="info">Nenhum código fiscal cadastrado. O código não é fixado pelo sistema: deve ser informado conforme o enquadramento validado pelo contador.</Alert></div>}
      </div>
    </Modal>
  );
}

function PlanList() {
  const { can } = useAuth();
  const services = useGet<any[]>(["services-all"], "/services");
  const opts = (services.data || []).map((s) => ({ value: s.id, label: s.name }));
  // desconto em relação ao preço avulso atual do serviço x quantidade de sessões
  const discount = (r: any) => {
    const svc = (services.data || []).find((s) => s.id === r.service_id);
    const full = Number(svc?.price || 0) * Number(r.sessions_count || 0);
    if (!full) return "—";
    const pct = (1 - Number(r.price || 0) / full) * 100;
    if (Math.abs(pct) < 0.05) return "0%";
    return `${pct.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;
  };
  return (
    <CrudList title="Planos de pacote" path="/package-plans" queryKey="package-plans" canWrite={can("services.write")}
      columns={[
        { key: "name", label: "Plano" },
        { key: "service_id", label: "Serviço", render: (r) => opts.find((o) => o.value === r.service_id)?.label || "—" },
        { key: "sessions_count", label: "Sessões" },
        { key: "price", label: "Valor", render: (r) => money(r.price) },
        { key: "discount", label: "Desconto", render: (r) => <span className="tabular-nums">{discount(r)}</span> },
        { key: "validity_days", label: "Validade", render: (r) => (r.validity_days ? `${r.validity_days} dias` : "Sem vencimento") },
        { key: "rules", label: "Regras", render: (r) => <span className="text-xs">{r.no_show_consumes ? "Falta desconta" : "Falta não desconta"} · {r.late_cancel_consumes ? `Cancelamento < ${r.late_cancel_hours}h desconta` : "Cancelamento não desconta"}</span> },
        { key: "is_active", label: "Ativo", render: (r) => (r.is_active ? "Sim" : "Não") },
      ]}
      transform={(b) => ({ ...b, price: String(b.price ?? 0), validity_days: b.validity_days || null, late_cancel_hours: b.late_cancel_hours ?? 24 })}
      fields={[
        { key: "name", label: "Nome do plano", required: true, span: 4 },
        { key: "service_id", label: "Serviço", type: "select", options: opts, required: true, span: 2 },
        { key: "sessions_count", label: "Quantidade de sessões", type: "number", required: true, span: 2 },
        { key: "price", label: "Valor (R$)", type: "money", required: true, span: 2 },
        { key: "validity_days", label: "Validade (dias)", type: "number", span: 2 },
        { key: "no_show_consumes", label: "Falta desconta sessão", type: "checkbox", defaultValue: true, span: 3 },
        { key: "late_cancel_consumes", label: "Cancelamento tardio desconta sessão", type: "checkbox", defaultValue: false, span: 3 },
        { key: "late_cancel_hours", label: "Antecedência mínima p/ cancelar (horas)", type: "number", defaultValue: 24, span: 3 },
        { key: "description", label: "Descrição", type: "textarea", span: 6 },
        { key: "is_active", label: "Ativo", type: "checkbox", defaultValue: true, span: 3 },
      ]} />
  );
}
