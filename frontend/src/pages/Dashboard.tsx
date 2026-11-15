import {
  AlertTriangle,
  CalendarCheck,
  CalendarClock,
  CalendarX,
  FileCheck2,
  FileClock,
  Receipt,
  TrendingUp,
  UserPlus,
  Users,
  Wallet,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { GroupedBars, MoneyLines, RankBars } from "../components/charts";
import { Alert, Badge, Card, Empty, Loading, PageHeader, StatCard, StatusBadge } from "../components/ui";
import { useAuth } from "../lib/auth";
import { date, money, pct, time } from "../lib/format";
import { useGet } from "../lib/hooks";

function Delta({ now, prev }: { now: number; prev: number }) {
  if (!prev) return <span className="text-slate-400">sem base no mês anterior</span>;
  const d = ((now - prev) / Math.abs(prev)) * 100;
  return (
    <span className={d >= 0 ? "text-emerald-600" : "text-rose-600"}>
      {d >= 0 ? "▲" : "▼"} {Math.abs(d).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% vs mês anterior
    </span>
  );
}

export default function Dashboard() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { data, isLoading, error } = useGet<any>(["dashboard"], "/dashboard");
  if (isLoading) return <Loading />;
  if (error || !data) return <Alert kind="danger">Não foi possível carregar o painel: {(error as Error)?.message}</Alert>;
  const op = data.operational;
  const fin = data.financial;
  const fis = data.fiscal;
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite";

  return (
    <div className="space-y-5">
      <PageHeader title={`${greet}, ${me?.name.split(" ")[0]}`} subtitle="Visão geral da clínica, atualizada em tempo real." />

      {data.alerts.length > 0 && (
        <div className="grid gap-2 md:grid-cols-2">
          {data.alerts.map((a: any, i: number) => (
            <button key={i} className="text-left" onClick={() => navigate(a.url)}>
              <Alert kind={a.level === "danger" ? "danger" : a.level === "warning" ? "warning" : "info"}>{a.text}</Alert>
            </button>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-5">
        <StatCard label="Atendimentos hoje" value={op.appointments_today} icon={<CalendarClock className="h-5 w-5" />} onClick={() => navigate("/agenda")} />
        <StatCard label="Total de clientes" value={op.total_customers} hint={`${op.active_customers} ativos`} icon={<Users className="h-5 w-5" />} tone="violet" />
        <StatCard label="Novos clientes no mês" value={op.new_customers_month} icon={<UserPlus className="h-5 w-5" />} tone="pink" />
        <StatCard label="Concluídos no mês" value={op.completed_month} hint={<Delta now={op.completed_month} prev={op.completed_prev_month} />}
          icon={<CalendarCheck className="h-5 w-5" />} tone="green" />
        <StatCard label="Cancelamentos / faltas" value={`${op.cancellations_month} / ${op.no_shows_month}`} hint="no mês" icon={<CalendarX className="h-5 w-5" />} tone="amber" />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label="Ocupação da agenda hoje" value={pct(op.occupancy_today)} hint={`Próximos 7 dias: ${pct(op.occupancy_week)}`} tone="slate" />
        <StatCard label="Taxa de retorno (180 dias)" value={pct(op.return_rate)} hint="clientes com 2+ atendimentos" tone="slate" />
        <StatCard label="Próximo atendimento" value={data.upcoming[0] ? time(data.upcoming[0].start_at) : "—"}
          hint={data.upcoming[0] ? `${date(data.upcoming[0].start_at)} · ${data.upcoming[0].customer}` : "sem agendamentos futuros"} tone="slate" />
      </div>

      {fin && (
        <>
          <h2 className="pt-1 text-sm font-semibold uppercase tracking-wide text-slate-500">Financeiro</h2>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <StatCard label="Recebido hoje" value={money(fin.received_today)} hint={`Contratado hoje: ${money(fin.contracted_today)}`} icon={<Wallet className="h-5 w-5" />} />
            <StatCard label="Faturamento do mês (contratado)" value={money(fin.contracted_month)} hint={<Delta now={fin.contracted_month} prev={fin.prev.contracted} />}
              icon={<TrendingUp className="h-5 w-5" />} tone="violet" />
            <StatCard label="Recebido no mês" value={money(fin.received_month)} hint={`Pendente: ${money(fin.pending_month)}`} icon={<Receipt className="h-5 w-5" />} tone="green" />
            <StatCard label="Valores em atraso" value={money(fin.overdue)} icon={<AlertTriangle className="h-5 w-5" />} tone="amber"
              onClick={() => navigate("/financeiro?aba=receber&atraso=1")} />
            <StatCard label="Despesas do mês" value={money(fin.expenses_month)} hint={`Pagas: ${money(fin.expenses_paid_month)}`} tone="pink" />
            <StatCard label="Resultado operacional estimado" value={money(fin.result_month)} hint={<Delta now={fin.result_month} prev={fin.prev.result} />} tone="slate" />
            <StatCard label="Ticket médio (avulso)" value={money(fin.ticket_avg)} tone="slate" />
            <StatCard label="Mês anterior" value={money(fin.prev.contracted)} hint={`Recebido ${money(fin.prev.received)}`} tone="slate" />
          </div>
        </>
      )}

      {fis && (
        <>
          <h2 className="pt-1 text-sm font-semibold uppercase tracking-wide text-slate-500">Fiscal</h2>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <StatCard label="NFS-e autorizadas no mês" value={fis.authorized_month} hint={`Canceladas: ${fis.cancelled_month}`} icon={<FileCheck2 className="h-5 w-5" />}
              onClick={() => navigate("/fiscal/notas")} />
            <StatCard label="Notas pendentes" value={fis.pending} hint="rascunho, rejeitadas ou aguardando" icon={<FileClock className="h-5 w-5" />} tone="amber"
              onClick={() => navigate("/fiscal/notas")} />
            <StatCard label="Receita documentada (mês)" value={money(fis.invoiced_month)} hint={`Ainda não faturada: ${money(fis.not_invoiced_month)}`} tone="green"
              onClick={() => navigate("/fiscal/emissao")} />
            <StatCard label="Tributos estimados (mês)" value={money(fis.taxes_estimated_month)} hint="estimativa — validar com o contador" tone="violet"
              onClick={() => navigate("/fiscal/tributos")} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Obrigações próximas do vencimento" actions={<button className="text-xs text-brand-600" onClick={() => navigate("/fiscal/obrigacoes")}>Ver todas</button>}>
              {fis.obligations_due.length === 0 ? <p className="text-sm text-slate-500">Nenhuma obrigação nos próximos 15 dias.</p> : (
                <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                  {fis.obligations_due.map((o: any) => (
                    <li key={o.id} className="flex items-center justify-between py-2 text-sm">
                      <span>{o.name}</span>
                      <span className="flex items-center gap-2 text-xs text-slate-500">{date(o.due_date)} <StatusBadge status={o.status} /></span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Documentos para a contabilidade">
              <p className="text-3xl font-semibold">{fis.pending_accounting_docs}</p>
              <p className="mt-1 text-sm text-slate-500">pendência(s): despesas sem comprovante anexado
                {fis.last_month_exported ? "" : " e pacote do mês anterior ainda não gerado"}.</p>
              <button className="mt-3 text-sm font-medium text-brand-600" onClick={() => navigate("/fiscal/exportacao")}>Ir para exportação →</button>
            </Card>
          </div>
        </>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Agenda de hoje" className="xl:col-span-1" actions={<button className="text-xs text-brand-600" onClick={() => navigate("/agenda")}>Abrir agenda</button>}>
          {data.today.length === 0 ? <Empty title="Sem atendimentos hoje" /> : (
            <ul className="space-y-2">
              {data.today.map((a: any) => (
                <li key={a.id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-2.5 dark:border-slate-800">
                  <span className="h-9 w-1 rounded-full" style={{ background: a.color }} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{time(a.start_at)} · {a.customer}</p>
                    <p className="truncate text-xs text-slate-500">{a.service} · {a.professional}</p>
                  </div>
                  <StatusBadge status={a.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        {fin && (
          <Card title="Faturamento mensal (12 meses)" className="xl:col-span-2">
            <MoneyLines data={data.charts.revenue} x="month" series={[
              { key: "contracted", label: "Contratado" }, { key: "received", label: "Recebido" }, { key: "invoiced", label: "Faturado (NFS-e)" }]} />
          </Card>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {fin && (
          <Card title="Receitas recebidas × despesas (competência)">
            <GroupedBars data={data.charts.revenue} x="month" series={[{ key: "received", label: "Recebido" }, { key: "expenses", label: "Despesas" }]} />
          </Card>
        )}
        <Card title="Novos clientes por mês">
          <GroupedBars data={data.charts.customers} x="month" series={[{ key: "new", label: "Novos clientes" }]} isMoney={false} />
          <p className="mt-1 text-xs text-slate-500">Base atual: {data.charts.customers.at(-1)?.total ?? 0} clientes cadastrados.</p>
        </Card>
        <Card title="Serviços mais realizados (3 meses)">
          {data.charts.top_services.length ? <RankBars data={data.charts.top_services} /> : <Empty title="Sem atendimentos concluídos" />}
        </Card>
        <Card title="Atendimentos por profissional (mês)">
          {data.charts.by_professional.length ? <RankBars data={data.charts.by_professional} /> : <Empty title="Sem atendimentos concluídos no mês" />}
        </Card>
        {fin && (
          <Card title="Recebimentos por forma de pagamento (mês)">
            {data.charts.payment_methods.length ? <RankBars data={data.charts.payment_methods} isMoney /> : <Empty title="Sem recebimentos no mês" />}
          </Card>
        )}
        <Card title="Próximos agendamentos">
          {data.upcoming.length === 0 ? <Empty title="Nenhum agendamento futuro" /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.upcoming.map((a: any) => (
                <li key={a.id} className="flex items-center justify-between py-2 text-sm">
                  <span className="truncate">{a.customer} <span className="text-slate-500">· {a.service}</span></span>
                  <Badge color="blue">{date(a.start_at)} {time(a.start_at)}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
