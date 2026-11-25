import clsx from "clsx";
import { Paperclip } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { GroupedBars } from "../components/charts";
import { CustomerPicker, PeriodPicker } from "../components/shared";
import {
  Alert, Badge, Button, Card, Checkbox, DataTable, Empty, Field, Input, Modal, PageHeader, Pagination, Select, StatCard, StatusBadge, Tabs, Textarea, useToast,
} from "../components/ui";
import { del, post, upload } from "../lib/api";
import { useAuth } from "../lib/auth";
import { addDays, date, dateTime, isoDay, money, monthEnd, monthStart } from "../lib/format";
import { useAction, useGet, useLookups } from "../lib/hooks";

export default function Finance() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const tabs = [
    ...(can("finance.read") ? [{ key: "visao", label: "Visão geral" }] : []),
    { key: "receber", label: "Contas a receber" },
    ...(can("finance.read") ? [
      { key: "pagar", label: "Contas a pagar e despesas" }, { key: "movimentos", label: "Movimentações" }, { key: "fluxo", label: "Fluxo de caixa" },
      { key: "fechamento", label: "Fechamento diário" }, { key: "conciliacao", label: "Conciliação" }, { key: "inadimplencia", label: "Inadimplência" },
    ] : []),
  ];
  const [tab, setTab] = useState(params.get("aba") || tabs[0].key);
  return (
    <div>
      <PageHeader title="Financeiro" subtitle="Receita contratada, faturada, recebida e pendente — agendamento nunca é considerado receita." />
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      {tab === "visao" && <Overview />}
      {tab === "receber" && <Receivables />}
      {tab === "pagar" && <Payables />}
      {tab === "movimentos" && <Transactions />}
      {tab === "fluxo" && <CashFlow />}
      {tab === "fechamento" && <Closing />}
      {tab === "conciliacao" && <Reconciliation />}
      {tab === "inadimplencia" && <Delinquency />}
    </div>
  );
}

function usePeriod() {
  const [p, setP] = useState({ start: monthStart(), end: monthEnd() });
  return [p, (s: string, e: string) => setP({ start: s, end: e })] as const;
}

function Overview() {
  const [p, setP] = usePeriod();
  const q = useGet<any>(["finance-summary"], "/finance/summary", p);
  const s = q.data;
  return (
    <div className="space-y-4">
      <PeriodPicker start={p.start} end={p.end} onChange={setP} />
      {s && (
        <>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <StatCard label="Receita contratada" value={money(s.contracted)} hint={s.notes.contracted} />
            <StatCard label="Receita faturada (NFS-e)" value={money(s.invoiced)} hint={`Não faturada: ${money(s.not_invoiced)}`} tone="violet" />
            <StatCard label="Receita recebida" value={money(s.received)} hint={s.notes.received} tone="green" />
            <StatCard label="Receita pendente" value={money(s.pending)} hint={`Em atraso (geral): ${money(s.overdue)}`} tone="amber" />
            <StatCard label="Despesas (competência)" value={money(s.expenses_competence)} tone="pink" />
            <StatCard label="Despesas pagas" value={money(s.expenses_paid)} tone="pink" />
            <StatCard label="Resultado por competência" value={money(s.operating_result_competence)} hint="estimado, antes de tributos sobre o lucro" tone="slate" />
            <StatCard label="Resultado de caixa" value={money(s.operating_result_cash)} tone="slate" />
          </div>
          <Card title="Saldos das contas">
            <div className="grid gap-2 sm:grid-cols-3">
              {s.accounts.map((a: any) => <div key={a.id} className="rounded-xl bg-slate-50 p-3 dark:bg-slate-800/50"><p className="text-xs text-slate-500">{a.name}</p><p className="text-lg font-semibold">{money(a.balance)}</p></div>)}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function PaymentModal({ title, balance, onSubmit, onClose, busy }: { title: string; balance: number; onSubmit: (b: any) => void; onClose: () => void; busy: boolean }) {
  const { methods } = useLookups();
  const accounts = useGet<any[]>(["accounts"], "/settings/financial-accounts", { active: true });
  const [f, setF] = useState({ amount: String(balance), payment_date: isoDay(), payment_method_id: "", account_id: "", document_ref: "", notes: "" });
  return (
    <Modal open onClose={onClose} title={title} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button>
        <Button loading={busy} disabled={!f.payment_method_id || !Number(f.amount)} onClick={() => onSubmit({ ...f, amount: String(f.amount), account_id: f.account_id || null, document_ref: f.document_ref || null, notes: f.notes || null })}>Registrar</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Valor" hint={`Saldo: ${money(balance)}`}><Input type="number" step="0.01" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Data do pagamento"><Input type="date" max={isoDay()} value={f.payment_date} onChange={(e) => setF({ ...f, payment_date: e.target.value })} /></Field>
        <Field label="Forma de pagamento" required><Select value={f.payment_method_id} onChange={(e) => setF({ ...f, payment_method_id: e.target.value })}><option value="">Selecione</option>{methods.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field>
        <Field label="Conta"><Select value={f.account_id} onChange={(e) => setF({ ...f, account_id: e.target.value })}><option value="">Conta padrão</option>{(accounts.data || []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
        <Field label="Documento/autorização" className="sm:col-span-2"><Input value={f.document_ref} onChange={(e) => setF({ ...f, document_ref: e.target.value })} placeholder="NSU, ID do PIX, recibo..." /></Field>
      </div>
    </Modal>
  );
}

function Receivables() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [filters, setFilters] = useState({ status: "aberto,parcial", overdue: params.get("atraso") === "1", q: params.get("q") || "" });
  const [page, setPage] = useState(1);
  const list = useGet<any>(["receivables"], "/finance/receivables", { status: filters.status || undefined, overdue: filters.overdue || undefined, q: filters.q || undefined, page });
  const [paying, setPaying] = useState<any>(null);
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState<any>(null);
  const pay = useAction((v: any) => post(`/finance/receivables/${paying.id}/payments`, v), { invalidate: [["receivables"], ["finance-summary"], ["dashboard"]], onDone: () => setPaying(null) });
  return (
    <Card padded={false} title="Contas a receber" actions={<>
      <Input className="!w-48" placeholder="Cliente ou descrição" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
      <Select className="!w-auto" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
        <option value="aberto,parcial">Em aberto</option><option value="pago">Pagas</option><option value="cancelado">Canceladas</option><option value="">Todas</option>
      </Select>
      <Checkbox label="Somente em atraso" checked={filters.overdue} onChange={(v) => setFilters({ ...filters, overdue: v })} />
      {can("finance.write") && <Button size="sm" onClick={() => setCreating(true)}>Nova receita avulsa</Button>}
    </>}>
      <DataTable rows={list.data?.items || []} empty={<Empty title="Nenhuma conta a receber" />} columns={[
        { key: "due_date", label: "Vencimento", render: (r) => <span className={clsx(r.overdue && "font-semibold text-rose-600")}>{date(r.due_date)}</span> },
        { key: "customer_name", label: "Cliente", render: (r) => r.customer_id ? <button className="text-brand-600" onClick={() => navigate(`/clientes/${r.customer_id}`)}>{r.customer_name}</button> : "—" },
        { key: "description", label: "Descrição" },
        { key: "origin", label: "Origem", render: (r) => <Badge color={r.origin === "pacote" ? "pink" : r.origin === "atendimento" ? "blue" : "gray"}>{r.origin}</Badge> },
        { key: "net_amount", label: "Valor", render: (r) => money(r.net_amount) },
        { key: "balance", label: "Saldo", render: (r) => money(r.balance) },
        { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
        { key: "nf", label: "NFS-e", render: (r) => r.invoice_status ? <StatusBadge status={r.invoice_status} /> : can("fiscal.issue") && r.status !== "cancelado" ? <button className="text-xs text-brand-600" onClick={() => navigate(`/fiscal/emissao?receber=${r.id}`)}>emitir</button> : "—" },
        { key: "a", label: "", render: (r) => (
          <div className="flex justify-end gap-1">
            {can("finance.payments") && ["aberto", "parcial"].includes(r.status) && <Button size="sm" onClick={() => setPaying(r)}>Receber</Button>}
            {can("finance.reverse") && r.status === "aberto" && <Button size="sm" variant="ghost" onClick={() => setCancelling(r)}>Cancelar</Button>}
          </div>) },
      ]} />
      <Pagination page={page} pageSize={50} total={list.data?.total || 0} onPage={setPage} />
      {paying && <PaymentModal title={`Receber — ${paying.description}`} balance={paying.balance} busy={pay.isPending} onClose={() => setPaying(null)} onSubmit={(b) => pay.mutate(b)} />}
      {creating && <ReceivableForm onClose={() => setCreating(false)} />}
      {cancelling && <CancelModal title="Cancelar conta a receber" path={`/finance/receivables/${cancelling.id}/cancel`} invalidate={["receivables"]} onClose={() => setCancelling(null)} />}
    </Card>
  );
}

function CancelModal({ title, path, invalidate, onClose }: { title: string; path: string; invalidate: string[]; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const run = useAction(() => post(path, { reason }), { invalidate: invalidate.map((k) => [k]), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={title} size="sm" footer={<Button variant="danger" loading={run.isPending} disabled={reason.length < 5} onClick={() => run.mutate(undefined)}>Confirmar</Button>}>
      <Field label="Motivo" required><Textarea value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
    </Modal>
  );
}

function ReceivableForm({ onClose }: { onClose: () => void }) {
  const cats = useGet<any[]>(["fin-cats"], "/settings/financial-categories");
  const ccs = useGet<any[]>(["cost-centers"], "/settings/cost-centers");
  const [customer, setCustomer] = useState<any>(null);
  const [f, setF] = useState({ description: "", total: "", discount: "0", competence_date: isoDay(), first_due_date: isoDay(), installments: 1, category_id: "", cost_center_id: "", notes: "" });
  const save = useAction(() => post("/finance/receivables", { ...f, customer_id: customer?.id || null, total: String(f.total), discount: String(f.discount || 0),
    installments: Number(f.installments), category_id: f.category_id || null, cost_center_id: f.cost_center_id || null, notes: f.notes || null }),
  { invalidate: [["receivables"], ["finance-summary"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title="Nova receita avulsa"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={save.isPending} disabled={!f.description || !Number(f.total)} onClick={() => save.mutate(undefined)}>Salvar</Button></>}>
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Cliente (opcional)" className="sm:col-span-4"><CustomerPicker value={customer} onChange={setCustomer} /></Field>
        <Field label="Descrição" required className="sm:col-span-4"><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Valor total" required><Input type="number" step="0.01" value={f.total} onChange={(e) => setF({ ...f, total: e.target.value })} /></Field>
        <Field label="Desconto"><Input type="number" step="0.01" value={f.discount} onChange={(e) => setF({ ...f, discount: e.target.value })} /></Field>
        <Field label="Parcelas"><Input type="number" min={1} max={24} value={f.installments} onChange={(e) => setF({ ...f, installments: Number(e.target.value) })} /></Field>
        <Field label="Competência"><Input type="date" value={f.competence_date} onChange={(e) => setF({ ...f, competence_date: e.target.value })} /></Field>
        <Field label="1º vencimento"><Input type="date" value={f.first_due_date} onChange={(e) => setF({ ...f, first_due_date: e.target.value })} /></Field>
        <Field label="Categoria"><Select value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}><option value="">Padrão</option>{(cats.data || []).filter((c) => c.kind === "receita").map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
        <Field label="Centro de custo" className="sm:col-span-2"><Select value={f.cost_center_id} onChange={(e) => setF({ ...f, cost_center_id: e.target.value })}><option value="">—</option>{(ccs.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
      </div>
    </Modal>
  );
}

function Payables() {
  const { can } = useAuth();
  const [params] = useSearchParams();
  const toast = useToast();
  const [status, setStatus] = useState("aberto,parcial");
  const [page, setPage] = useState(1);
  const list = useGet<any>(["payables"], "/finance/payables", { status: status || undefined, page });
  const [creating, setCreating] = useState(params.get("nova") === "1");
  const [paying, setPaying] = useState<any>(null);
  const [cancelling, setCancelling] = useState<any>(null);
  const pay = useAction((v: any) => post(`/finance/payables/${paying.id}/payments`, v), { invalidate: [["payables"], ["finance-summary"]], onDone: () => setPaying(null) });
  async function attach(expenseId: string) {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pdf,image/*,.xml";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      try { await upload(`/finance/expenses/${expenseId}/files`, fd); toast.success("Comprovante anexado."); } catch (e) { toast.error(e); }
    };
    input.click();
  }
  return (
    <Card padded={false} title="Contas a pagar" actions={<>
      <Select className="!w-auto" value={status} onChange={(e) => setStatus(e.target.value)}><option value="aberto,parcial">Em aberto</option><option value="pago">Pagas</option><option value="cancelado">Canceladas</option><option value="">Todas</option></Select>
      {can("finance.write") && <Button size="sm" onClick={() => setCreating(true)}>Cadastrar despesa</Button>}
    </>}>
      <DataTable rows={list.data?.items || []} empty={<Empty title="Nenhuma conta a pagar" />} columns={[
        { key: "due_date", label: "Vencimento", render: (r) => <span className={clsx(r.overdue && "font-semibold text-rose-600")}>{date(r.due_date)}</span> },
        { key: "description", label: "Descrição" },
        { key: "supplier_name", label: "Fornecedor", render: (r) => r.supplier_name || "—" },
        { key: "amount", label: "Valor", render: (r) => money(r.amount) },
        { key: "balance", label: "Saldo", render: (r) => money(r.balance) },
        { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
        { key: "a", label: "", render: (r) => (
          <div className="flex justify-end gap-1">
            {can("finance.write") && r.expense_id && <Button size="sm" variant="ghost" icon={<Paperclip className="h-3.5 w-3.5" />} onClick={() => attach(r.expense_id)}>Comprovante</Button>}
            {can("finance.write") && ["aberto", "parcial"].includes(r.status) && <Button size="sm" onClick={() => setPaying(r)}>Pagar</Button>}
            {can("finance.reverse") && r.status === "aberto" && <Button size="sm" variant="ghost" onClick={() => setCancelling(r)}>Cancelar</Button>}
          </div>) },
      ]} />
      <Pagination page={page} pageSize={50} total={list.data?.total || 0} onPage={setPage} />
      {creating && <ExpenseForm onClose={() => setCreating(false)} />}
      {paying && <PaymentModal title={`Pagar — ${paying.description}`} balance={paying.balance} busy={pay.isPending} onClose={() => setPaying(null)} onSubmit={(b) => pay.mutate(b)} />}
      {cancelling && <CancelModal title="Cancelar conta a pagar" path={`/finance/payables/${cancelling.id}/cancel`} invalidate={["payables"]} onClose={() => setCancelling(null)} />}
    </Card>
  );
}

function ExpenseForm({ onClose }: { onClose: () => void }) {
  const { methods } = useLookups();
  const cats = useGet<any[]>(["fin-cats"], "/settings/financial-categories");
  const ccs = useGet<any[]>(["cost-centers"], "/settings/cost-centers");
  const accounts = useGet<any[]>(["accounts"], "/settings/financial-accounts", { active: true });
  const [f, setF] = useState({ description: "", category_id: "", cost_center_id: "", supplier_name: "", supplier_document: "", competence_date: isoDay(), amount: "",
    first_due_date: isoDay(), installments: 1, payment_method_id: "", paid_now: false, account_id: "", notes: "" });
  const save = useAction(() => post("/finance/expenses", { ...f, amount: String(f.amount), installments: Number(f.installments), cost_center_id: f.cost_center_id || null,
    supplier_name: f.supplier_name || null, supplier_document: f.supplier_document || null, payment_method_id: f.payment_method_id || null,
    account_id: f.account_id || null, notes: f.notes || null }), { invalidate: [["payables"], ["finance-summary"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title="Cadastrar despesa" size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={save.isPending} disabled={!f.description || !f.category_id || !Number(f.amount)} onClick={() => save.mutate(undefined)}>Salvar</Button></>}>
      <div className="grid gap-3 sm:grid-cols-6">
        <Field label="Descrição" required className="sm:col-span-4"><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Categoria" required className="sm:col-span-2"><Select value={f.category_id} onChange={(e) => setF({ ...f, category_id: e.target.value })}><option value="">Selecione</option>{(cats.data || []).filter((c) => c.kind === "despesa" && c.is_active).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
        <Field label="Fornecedor" className="sm:col-span-3"><Input value={f.supplier_name} onChange={(e) => setF({ ...f, supplier_name: e.target.value })} /></Field>
        <Field label="CPF/CNPJ do fornecedor" className="sm:col-span-3"><Input value={f.supplier_document} onChange={(e) => setF({ ...f, supplier_document: e.target.value })} /></Field>
        <Field label="Valor total" required className="sm:col-span-2"><Input type="number" step="0.01" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Competência" className="sm:col-span-2"><Input type="date" value={f.competence_date} onChange={(e) => setF({ ...f, competence_date: e.target.value })} /></Field>
        <Field label="Centro de custo" className="sm:col-span-2"><Select value={f.cost_center_id} onChange={(e) => setF({ ...f, cost_center_id: e.target.value })}><option value="">—</option>{(ccs.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
        <Field label="1º vencimento" className="sm:col-span-2"><Input type="date" value={f.first_due_date} onChange={(e) => setF({ ...f, first_due_date: e.target.value })} /></Field>
        <Field label="Parcelas" className="sm:col-span-2"><Input type="number" min={1} max={24} value={f.installments} onChange={(e) => setF({ ...f, installments: Number(e.target.value) })} /></Field>
        <Field label="Forma de pagamento" className="sm:col-span-2"><Select value={f.payment_method_id} onChange={(e) => setF({ ...f, payment_method_id: e.target.value })}><option value="">—</option>{methods.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field>
        <div className="sm:col-span-3"><Checkbox label="Já foi paga (registra o pagamento da 1ª parcela)" checked={f.paid_now} onChange={(v) => setF({ ...f, paid_now: v })} /></div>
        {f.paid_now && <Field label="Conta de saída" className="sm:col-span-3"><Select value={f.account_id} onChange={(e) => setF({ ...f, account_id: e.target.value })}><option value="">Conta padrão</option>{(accounts.data || []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>}
        <Field label="Observações" className="sm:col-span-6"><Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      </div>
    </Modal>
  );
}

function Transactions() {
  const { can } = useAuth();
  const [p, setP] = usePeriod();
  const [page, setPage] = useState(1);
  const [reconciled, setReconciled] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [ref, setRef] = useState("");
  const [reversing, setReversing] = useState<any>(null);
  const { methods } = useLookups();
  const list = useGet<any>(["transactions"], "/finance/transactions", { ...p, page, reconciled: reconciled || undefined });
  const reconcile = useAction((v: boolean) => post("/finance/reconcile", { transaction_ids: selected, reconciled: v, reference: ref || null }),
    { invalidate: [["transactions"]], onDone: () => setSelected([]) });
  return (
    <Card padded={false} title="Movimentações de caixa" actions={<>
      <PeriodPicker start={p.start} end={p.end} onChange={setP} />
      <Select className="!w-auto" value={reconciled} onChange={(e) => setReconciled(e.target.value)}><option value="">Todas</option><option value="false">Não conciliadas</option><option value="true">Conciliadas</option></Select>
    </>}>
      {can("finance.close") && selected.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-brand-50 px-4 py-2 text-sm dark:border-slate-800 dark:bg-brand-900/20">
          {selected.length} selecionada(s) <Input className="!w-56" placeholder="Referência do extrato" value={ref} onChange={(e) => setRef(e.target.value)} />
          <Button size="sm" onClick={() => reconcile.mutate(true)}>Marcar conciliadas</Button>
          <Button size="sm" variant="secondary" onClick={() => reconcile.mutate(false)}>Desmarcar</Button>
        </div>
      )}
      <DataTable rows={list.data?.items || []} empty={<Empty title="Nenhuma movimentação no período" />} columns={[
        ...(can("finance.close") ? [{ key: "sel", label: "", render: (r: any) => <input type="checkbox" checked={selected.includes(r.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, r.id] : selected.filter((x) => x !== r.id))} /> }] : []),
        { key: "transaction_date", label: "Data", render: (r) => date(r.transaction_date) },
        { key: "description", label: "Descrição", render: (r) => <span>{r.description} {r.is_reversal && <Badge color="red">estorno</Badge>} {r.reversed && <Badge color="gray">estornado</Badge>}</span> },
        { key: "method", label: "Forma", render: (r) => methods.find((m) => m.id === r.payment_method_id)?.name || "—" },
        { key: "amount", label: "Valor", render: (r) => <span className={r.kind === "entrada" ? "text-emerald-700 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}>{r.kind === "entrada" ? "+" : "−"} {money(r.amount)}</span> },
        { key: "reconciled", label: "Conciliação", render: (r) => r.reconciled ? <Badge color="green">{r.reconciliation_ref || "conciliada"}</Badge> : <Badge color="gray">pendente</Badge> },
        { key: "a", label: "", render: (r) => can("finance.reverse") && !r.is_reversal && !r.reversed && <Button size="sm" variant="ghost" onClick={() => setReversing(r)}>Estornar</Button> },
      ]} />
      <Pagination page={page} pageSize={100} total={list.data?.total || 0} onPage={setPage} />
      {reversing && <CancelModal title={`Estornar ${money(reversing.amount)}`} path={`/finance/transactions/${reversing.id}/reverse`} invalidate={["transactions", "receivables", "payables", "finance-summary"]} onClose={() => setReversing(null)} />}
    </Card>
  );
}

function CashFlow() {
  const [p, setP] = useState({ start: addDays(isoDay(), -30), end: addDays(isoDay(), 30) });
  const q = useGet<any>(["cash-flow"], "/finance/cash-flow", p);
  const d = q.data;
  const past = (d?.days || []).filter((x: any) => x.date <= isoDay());
  return (
    <div className="space-y-4">
      <PeriodPicker start={p.start} end={p.end} onChange={(s, e) => setP({ start: s, end: e })} />
      {d && (
        <>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <StatCard label="Saldo inicial" value={money(d.opening_balance)} />
            <StatCard label="Saldo atual/final" value={money(d.closing_balance)} tone="green" />
            <StatCard label="A receber no período" value={money(d.projection.receivables.reduce((s: number, x: any) => s + x.amount, 0))} tone="violet" />
            <StatCard label="A pagar no período" value={money(d.projection.payables.reduce((s: number, x: any) => s + x.amount, 0))} tone="pink" />
          </div>
          <Card title="Entradas × saídas por dia (realizado)">
            <GroupedBars data={past.filter((x: any) => x.in || x.out).map((x: any) => ({ ...x, label: date(x.date).slice(0, 5) }))} x="label" series={[{ key: "in", label: "Entradas" }, { key: "out", label: "Saídas" }]} />
          </Card>
          <Card title="Detalhamento" padded={false}>
            <DataTable rowKey="date" rows={d.days.filter((x: any) => x.in || x.out)} columns={[
              { key: "date", label: "Data", render: (r) => date(r.date) },
              { key: "in", label: "Entradas", render: (r) => money(r.in) },
              { key: "out", label: "Saídas", render: (r) => money(r.out) },
              { key: "balance", label: "Saldo", render: (r) => money(r.balance) },
            ]} />
          </Card>
        </>
      )}
    </div>
  );
}

function Closing() {
  const { can } = useAuth();
  const accounts = useGet<any[]>(["accounts"], "/settings/financial-accounts", { active: true });
  const [f, setF] = useState({ account_id: "", closing_date: isoDay(), counted_balance: "", notes: "" });
  const acc = f.account_id || accounts.data?.[0]?.id || "";
  const preview = useGet<any>(["closing-preview"], acc && can("finance.close") ? "/finance/closings/preview" : null, { account_id: acc, closing_date: f.closing_date });
  const list = useGet<any[]>(["closings"], "/finance/closings");
  const close = useAction(() => post("/finance/closings", { account_id: acc, closing_date: f.closing_date, counted_balance: f.counted_balance === "" ? null : String(f.counted_balance), notes: f.notes || null }),
    { invalidate: [["closings"], ["closing-preview"]] });
  const reopen = useAction((id: string) => del(`/finance/closings/${id}`), { invalidate: [["closings"]] });
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      {can("finance.close") && (
        <Card title="Fechar o dia" className="lg:col-span-2">
          <div className="space-y-3">
            <Field label="Conta"><Select value={acc} onChange={(e) => setF({ ...f, account_id: e.target.value })}>{(accounts.data || []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
            <Field label="Data"><Input type="date" max={isoDay()} value={f.closing_date} onChange={(e) => setF({ ...f, closing_date: e.target.value })} /></Field>
            {preview.data && (
              <dl className="grid grid-cols-2 gap-2 rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-800/50">
                <dt>Saldo inicial</dt><dd className="text-right">{money(preview.data.opening_balance)}</dd>
                <dt>Entradas</dt><dd className="text-right text-emerald-700 dark:text-emerald-400">{money(preview.data.total_in)}</dd>
                <dt>Saídas</dt><dd className="text-right text-rose-600">{money(preview.data.total_out)}</dd>
                <dt className="font-semibold">Saldo esperado</dt><dd className="text-right font-semibold">{money(preview.data.expected_balance)}</dd>
              </dl>
            )}
            <Field label="Saldo conferido (contagem)" hint="Opcional; a diferença é registrada."><Input type="number" step="0.01" value={f.counted_balance} onChange={(e) => setF({ ...f, counted_balance: e.target.value })} /></Field>
            <Field label="Observações"><Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
            <Button loading={close.isPending} onClick={() => close.mutate(undefined)}>Fechar dia</Button>
            <p className="text-xs text-slate-500">Após o fechamento, não são aceitos lançamentos com data igual ou anterior nesta conta.</p>
          </div>
        </Card>
      )}
      <Card title="Fechamentos realizados" padded={false} className="lg:col-span-3">
        <DataTable rows={list.data || []} columns={[
          { key: "closing_date", label: "Data", render: (r) => date(r.closing_date) },
          { key: "account", label: "Conta", render: (r) => (accounts.data || []).find((a) => a.id === r.account_id)?.name || "—" },
          { key: "expected_balance", label: "Esperado", render: (r) => money(r.expected_balance) },
          { key: "counted_balance", label: "Conferido", render: (r) => money(r.counted_balance) },
          { key: "difference", label: "Diferença", render: (r) => r.difference ? <span className="text-rose-600">{money(r.difference)}</span> : "—" },
          { key: "closed_at", label: "Fechado em", render: (r) => dateTime(r.closed_at) },
          { key: "a", label: "", render: (r) => can("finance.reverse") && <Button size="sm" variant="ghost" onClick={() => reopen.mutate(r.id)}>Reabrir</Button> },
        ]} />
      </Card>
    </div>
  );
}

function Reconciliation() {
  const [p, setP] = usePeriod();
  const [onlyIssues, setOnlyIssues] = useState(true);
  const q = useGet<any>(["reconciliation"], "/finance/reconciliation/overview", p);
  const items = (q.data?.items || []).filter((i: any) => !onlyIssues || i.issues.length);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3"><PeriodPicker start={p.start} end={p.end} onChange={setP} /><Checkbox label="Somente divergências" checked={onlyIssues} onChange={setOnlyIssues} /></div>
      {q.data && <Alert kind={q.data.with_issues ? "warning" : "success"}>{q.data.with_issues} título(s) com divergência entre pagamento e nota fiscal · {q.data.unreconciled_transactions} movimentação(ões) ainda não conciliada(s) com o extrato.</Alert>}
      <Card padded={false}>
        <DataTable rowKey="receivable_id" rows={items} empty={<Empty title="Nenhuma divergência" />} columns={[
          { key: "competence_date", label: "Competência", render: (r) => date(r.competence_date) },
          { key: "customer", label: "Cliente", render: (r) => r.customer || "—" },
          { key: "description", label: "Descrição" },
          { key: "amount", label: "Valor", render: (r) => money(r.amount) },
          { key: "paid", label: "Recebido", render: (r) => money(r.paid) },
          { key: "inv", label: "NFS-e", render: (r) => r.invoices.length ? r.invoices.map((i: any) => <StatusBadge key={i.id} status={i.status} />) : "—" },
          { key: "issues", label: "Divergências", render: (r) => r.issues.map((x: string) => <Badge key={x} color="yellow" className="mr-1">{x}</Badge>) },
        ]} />
      </Card>
    </div>
  );
}

function Delinquency() {
  const navigate = useNavigate();
  const q = useGet<any>(["delinquency"], "/finance/delinquency");
  return (
    <Card padded={false} title={`Inadimplência — total ${money(q.data?.total)}`}>
      <DataTable rowKey="customer_id" rows={q.data?.customers || []} onRowClick={(r) => r.customer_id && navigate(`/clientes/${r.customer_id}`)} empty={<Empty title="Nenhum valor em atraso" />} columns={[
        { key: "name", label: "Cliente" },
        { key: "phone", label: "Telefone" },
        { key: "items", label: "Títulos" },
        { key: "oldest_due", label: "Vencimento mais antigo", render: (r) => date(r.oldest_due) },
        { key: "total", label: "Em atraso", render: (r) => <span className="font-semibold text-rose-600">{money(r.total)}</span> },
      ]} />
    </Card>
  );
}
