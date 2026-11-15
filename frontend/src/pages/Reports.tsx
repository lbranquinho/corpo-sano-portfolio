import clsx from "clsx";
import { useState } from "react";
import { ReportViewer } from "../components/ReportViewer";
import { PageHeader } from "../components/ui";
import { monthEnd, monthStart } from "../lib/format";
import { useGet } from "../lib/hooks";

const CATS: Record<string, string> = { operacional: "Operacionais", financeiro: "Financeiros", fiscal: "Fiscais" };

export default function Reports() {
  const catalog = useGet<any[]>(["reports-catalog"], "/reports");
  const [key, setKey] = useState<string | null>(null);
  const current = key || catalog.data?.[0]?.key;
  return (
    <div>
      <PageHeader title="Central de relatórios" subtitle="Relatórios gerenciais e contábeis com dados reais, filtráveis por período e exportáveis em PDF, Excel e CSV." />
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <nav className="card no-print h-fit p-2">
          {Object.entries(CATS).map(([cat, label]) => {
            const items = (catalog.data || []).filter((r) => r.category === cat);
            if (!items.length) return null;
            return (
              <div key={cat} className="mb-2">
                <p className="px-2 pb-1 pt-2 text-xs font-semibold uppercase text-slate-500">{label}</p>
                {items.map((r) => (
                  <button key={r.key} onClick={() => setKey(r.key)}
                    className={clsx("block w-full rounded-lg px-2.5 py-1.5 text-left text-sm", current === r.key ? "bg-brand-100 font-medium text-brand-900 dark:bg-brand-900/40 dark:text-white" : "hover:bg-slate-50 dark:hover:bg-slate-800")}>
                    {r.title}
                  </button>
                ))}
              </div>
            );
          })}
        </nav>
        <div>{current && <ReportViewer key={current} reportKey={current} initialStart={monthStart()} initialEnd={monthEnd()} />}</div>
      </div>
    </div>
  );
}
