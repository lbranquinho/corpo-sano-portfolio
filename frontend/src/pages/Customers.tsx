import { Search, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CustomerForm } from "../components/shared";
import { Badge, Button, Card, DataTable, Input, Loading, PageHeader, Pagination, Select, StatusBadge } from "../components/ui";
import { useAuth } from "../lib/auth";
import { cpf, date, phone } from "../lib/format";
import { useGet } from "../lib/hooks";

const STAGES: Record<string, string> = {
  novo_contato: "Novo contato", interessado: "Interessado", avaliacao_agendada: "Avaliação agendada", primeiro_atendimento: "1º atendimento",
  cliente_recorrente: "Recorrente", pacote_contratado: "Pacote", cliente_inativo: "Inativo",
};

export default function Customers() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [segment, setSegment] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => { setDebounced(q); setPage(1); }, 250);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    if (params.get("novo") === "1") {
      setCreating(true);
      params.delete("novo");
      setParams(params, { replace: true });
    }
  }, [params, setParams]);
  const list = useGet<any>(["customers"], "/customers", { q: debounced, segment, page, page_size: 25 });
  return (
    <div>
      <PageHeader title="Clientes" subtitle="Pesquisa instantânea por nome, telefone ou CPF."
        actions={can("customers.write") && <Button icon={<UserPlus className="h-4 w-4" />} onClick={() => setCreating(true)}>Novo cliente</Button>} />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-3 dark:border-slate-800">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" aria-hidden />
            <Input className="pl-9" placeholder="Buscar..." value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
          </div>
          <Select className="!w-auto" value={segment} onChange={(e) => { setSegment(e.target.value); setPage(1); }}>
            <option value="">Todos</option>
            <option value="novos">Novos (30 dias)</option>
            <option value="ativos">Ativos</option>
            <option value="inativos">Inativos</option>
            <option value="recorrentes">Recorrentes</option>
          </Select>
        </div>
        {list.isLoading ? <Loading /> : (
          <>
            <DataTable rows={list.data?.items || []} onRowClick={(r) => navigate(`/clientes/${r.id}`)} columns={[
              { key: "full_name", label: "Nome", render: (r) => <span className="font-medium">{r.full_name}</span> },
              { key: "phone", label: "Telefone", render: (r) => phone(r.whatsapp || r.phone) },
              { key: "cpf", label: "CPF", render: (r) => (r.cpf ? cpf(r.cpf) : "—") },
              { key: "visits", label: "Atendimentos" },
              { key: "last", label: "Último atendimento", render: (r) => date(r.last_visit_at) },
              { key: "next", label: "Próximo", render: (r) => (r.next_appointment_at ? <Badge color="blue">{date(r.next_appointment_at)}</Badge> : "—") },
              { key: "stage", label: "Relacionamento", render: (r) => (r.crm_stage ? <Badge color="violet">{STAGES[r.crm_stage]}</Badge> : "—") },
              { key: "status", label: "Situação", render: (r) => <StatusBadge status={r.status} /> },
            ]} />
            <Pagination page={page} pageSize={25} total={list.data?.total || 0} onPage={setPage} />
          </>
        )}
      </Card>
      <CustomerForm open={creating} onClose={() => setCreating(false)} onSaved={(c) => { list.refetch(); navigate(`/clientes/${c.id}`); }} />
    </div>
  );
}
