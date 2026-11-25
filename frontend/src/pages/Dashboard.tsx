import {
  AlertTriangle,
  ArrowDownCircle,
  Clock,
  FileText,
  Gauge,
  History,
  Landmark,
  Repeat,
  Scale,
  Tag,
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
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { GroupedBars, MoneyLines, RankBars } from "../components/charts";
import { Alert, Badge, Card, Empty, PageHeader, Skeleton, StatCard, StatusBadge, Tabs } from "../components/ui";
import { useAuth } from "../lib/auth";
import { date, money, pct, time } from "../lib/format";
import { useGet } from "../lib/hooks";

function Delta({ now, prev }: { now: number; prev: number }) {
  if (!prev) return <span className="text-slate-500 dark:text-slate-400">sem base no mês anterior</span>;
  const d = ((now - prev) / Math.abs(prev)) * 100;
  return (
    <span className={d >= 0 ? "text-emerald-700 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}>
      <span aria-hidden>{d >= 0 ? "▲" : "▼"}</span> {Math.abs(d).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% vs mês anterior
    </span>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="Carregando painel">
      <Skeleton className="h-8 w-56" />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[88px]" />)}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    </div>
  );
}

const LINK = "btn-ghost !px-2.5 !py-1.5 text-xs text-brand-700 dark:text-brand-100";

export default function Dashboard() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState("operacao");
  const { data, isLoading, error } = useGet<any>(["dashboard"], "/dashboard");
  if (isLoading) return <DashboardSkeleton />;
  if (error || !data) return <Alert kind="danger">Não foi possível carregar o painel: {(error as Error)?.message}</Alert>;
  const op = data.operational;
  const fin = data.financial;
  const fis = data.fiscal;
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Bom dia" : hour < 18 ? "Boa tarde" : "Boa noite";
  const next = data.upcoming[0];
  const tabs = [
    { key: "operacao", label: "Operação" },
    ...(fin ? [{ key: "financeiro", label: "Financeiro" }] : []),
    ...(fis ? [{ key: "fiscal", label: "Fiscal" }] : []),
  ];
  const current = tabs.some((t) => t.key === tab) ? tab : "operacao";

  return (
    <div className="space-y-5">
      <PageHeader title={`${greet}, ${me?.name.split(" ")[0]}`} subtitle="Visão geral da clínica, atualizada em tempo real." />

      {data.alerts.length > 0 && (
        <div className="grid gap-2 md:grid-cols-2">
          {data.alerts.map((a: any, i: number) => (
            <button key={i} className="rounded-xl text-left" onClick={() => navigate(a.url)}>
              <Alert kind={a.level === "danger" ? "danger" : a.level === "warning" ? "warning" : "info"}>{a.text}</Alert>
            </button>
          ))}
        </div>
      )}

      {/* hoje: o que a recepção precisa ver primeiro */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="Atendimentos hoje" value={op.appointments_today} hint={`Ocupação: ${pct(op.occupancy_today)}`}
          icon={<CalendarClock className="h-5 w-5" />} onClick={() => navigate("/agenda")} />
        <StatCard label="Próximo atendimento" value={next ? time(next.start_at) : "—"}
          hint={next ? `${date(next.start_at)} · ${next.customer}` : "sem agendamentos futuros"} icon={<Clock className="h-5 w-5" />} tone="violet" />
        {fin ? (
          <>
            <StatCard label="Recebido hoje" value={money(fin.received_today)} hint={`Contratado hoje: ${money(fin.contracted_today)}`}
              icon={<Wallet className="h-5 w-5" />} tone="green" />
            <StatCard label="Valores em atraso" value={money(fin.overdue)} icon={<AlertTriangle className="h-5 w-5" />} tone="amber"
              onClick={() => navigate("/financeiro?aba=receber&atraso=1")} />
          </>
        ) : (
          <>
            <StatCard label="Novos clientes no mês" value={op.new_customers_month} icon={<UserPlus className="h-5 w-5" />} tone="pink" />
            <StatCard label="Ocupação próximos 7 dias" value={pct(op.occupancy_week)} icon={<Gauge className="h-5 w-5" />} tone="slate" />
          </>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Agenda de hoje" actions={<button className={LINK} onClick={() => navigate("/agenda")}>Abrir agenda</button>}>
          {data.today.length === 0 ? <Empty title="Sem atendimentos hoje" /> : (
            <ul className="space-y-2">
              {data.today.map((a: any) => (
                <li key={a.id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-2.5 dark:border-slate-800">
                  <span className="h-9 w-1 rounded-full" style={{ background: a.color }} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{time(a.start_at)} · {a.customer}</p>
                    <p className="truncate text-xs text-slate-500 dark:text-slate-400">{a.service} · {a.professional}</p>
                  </div>
                  <StatusBadge status={a.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Próximos agendamentos">
          {data.upcoming.length === 0 ? <Empty title="Nenhum agendamento futuro" /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.upcoming.map((a: any) => (
                <li key={a.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span className="min-w-0 truncate">{a.customer} <span className="text-slate-500 dark:text-slate-400">· {a.service}</span></span>
                  <Badge color="blue" className="shrink-0">{date(a.start_at)} {time(a.start_at)}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div>
        {tabs.length > 1 && <Tabs tabs={tabs} value={current} onChange={setTab} />}

        {current === "operacao" && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              <StatCard label="Total de clientes" value={op.total_customers} hint={`${op.active_customers} ativos`} icon={<Users className="h-5 w-5" />} tone="violet" />
              <StatCard label="Novos clientes no mês" value={op.new_customers_month} icon={<UserPlus className="h-5 w-5" />} tone="pink" />
              <StatCard label="Concluídos no mês" value={op.completed_month} hint={<Delta now={op.completed_month} prev={op.completed_prev_month} />}
                icon={<CalendarCheck className="h-5 w-5" />} tone="green" />
              <StatCard label="Cancelamentos / faltas" value={`${op.cancellations_month} / ${op.no_shows_month}`} hint="no mês" icon={<CalendarX className="h-5 w-5" />} tone="amber" />
              <StatCard label="Taxa de retorno (180 dias)" value={pct(op.return_rate)} hint="clientes com 2+ atendimentos" icon={<Repeat className="h-5 w-5" />} tone="slate" />
              {fin && <StatCard label="Ocupação próximos 7 dias" value={pct(op.occupancy_week)} icon={<Gauge className="h-5 w-5" />} tone="slate" />}
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card title="Novos clientes por mês">
                <GroupedBars data={data.charts.customers} x="month" series={[{ key: "new", label: "Novos clientes" }]} isMoney={false} />
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Base atual: {data.charts.customers.at(-1)?.total ?? 0} clientes cadastrados.</p>
              </Card>
              <Card title="Serviços mais realizados (3 meses)">
                {data.charts.top_services.length ? <RankBars data={data.charts.top_services} /> : <Empty title="Sem atendimentos concluídos" />}
              </Card>
              <Card title="Atendimentos por profissional (mês)">
                {data.charts.by_professional.length ? <RankBars data={data.charts.by_professional} /> : <Empty title="Sem atendimentos concluídos no mês" />}
              </Card>
            </div>
          </div>
        )}

        {current === "financeiro" && fin && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
              <StatCard label="Faturamento do mês (contratado)" value={money(fin.contracted_month)} hint={<Delta now={fin.contracted_month} prev={fin.prev.contracted} />}
                icon={<TrendingUp className="h-5 w-5" />} tone="violet" />
              <StatCard label="Recebido no mês" value={money(fin.received_month)} hint={`Pendente: ${money(fin.pending_month)}`} icon={<Receipt className="h-5 w-5" />} tone="green" />
              <StatCard label="Despesas do mês" value={money(fin.expenses_month)} hint={`Pagas: ${money(fin.expenses_paid_month)}`} icon={<ArrowDownCircle className="h-5 w-5" />} tone="pink" />
              <StatCard label="Resultado operacional estimado" value={money(fin.result_month)} hint={<Delta now={fin.result_month} prev={fin.prev.result} />}
                icon={<Scale className="h-5 w-5" />} tone="slate" />
              <StatCard label="Ticket médio (avulso)" value={money(fin.ticket_avg)} icon={<Tag className="h-5 w-5" />} tone="slate" />
              <StatCard label="Mês anterior" value={money(fin.prev.contracted)} hint={`Recebido ${money(fin.prev.received)}`} icon={<History className="h-5 w-5" />} tone="slate" />
            </div>
            <Card title="Faturamento mensal (12 meses)">
              <MoneyLines data={data.charts.revenue} x="month" series={[
                { key: "contracted", label: "Contratado" }, { key: "received", label: "Recebido" }, { key: "invoiced", label: "Faturado (NFS-e)" }]} />
            </Card>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card title="Receitas recebidas × despesas (competência)">
                <GroupedBars data={data.charts.revenue} x="month" series={[{ key: "received", label: "Recebido" }, { key: "expenses", label: "Despesas" }]} />
              </Card>
              <Card title="Recebimentos por forma de pagamento (mês)">
                {data.charts.payment_methods.length ? <RankBars data={data.charts.payment_methods} isMoney /> : <Empty title="Sem recebimentos no mês" />}
              </Card>
            </div>
          </div>
        )}

        {current === "fiscal" && fis && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <StatCard label="NFS-e autorizadas no mês" value={fis.authorized_month} hint={`Canceladas: ${fis.cancelled_month}`} icon={<FileCheck2 className="h-5 w-5" />}
                onClick={() => navigate("/fiscal/notas")} />
              <StatCard label="Notas pendentes" value={fis.pending} hint="rascunho, rejeitadas ou aguardando" icon={<FileClock className="h-5 w-5" />} tone="amber"
                onClick={() => navigate("/fiscal/notas")} />
              <StatCard label="Receita documentada (mês)" value={money(fis.invoiced_month)} hint={`Ainda não faturada: ${money(fis.not_invoiced_month)}`} icon={<FileText className="h-5 w-5" />}
                tone="green" onClick={() => navigate("/fiscal/emissao")} />
              <StatCard label="Tributos estimados (mês)" value={money(fis.taxes_estimated_month)} hint="estimativa — validar com o contador" icon={<Landmark className="h-5 w-5" />}
                tone="violet" onClick={() => navigate("/fiscal/tributos")} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card title="Obrigações próximas do vencimento" actions={<button className={LINK} onClick={() => navigate("/fiscal/obrigacoes")}>Ver todas</button>}>
                {fis.obligations_due.length === 0 ? <p className="text-sm text-slate-500 dark:text-slate-400">Nenhuma obrigação nos próximos 15 dias.</p> : (
                  <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                    {fis.obligations_due.map((o: any) => (
                      <li key={o.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                        <span>{o.name}</span>
                        <span className="flex shrink-0 items-center gap-2 text-xs text-slate-500 dark:text-slate-400">{date(o.due_date)} <StatusBadge status={o.status} /></span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title="Documentos para a contabilidade" actions={<button className={LINK} onClick={() => navigate("/fiscal/exportacao")}>Ir para exportação</button>}>
                <p className="text-3xl font-semibold tabular-nums">{fis.pending_accounting_docs}</p>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">pendência(s): despesas sem comprovante anexado
                  {fis.last_month_exported ? "" : " e pacote do mês anterior ainda não gerado"}.</p>
              </Card>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
