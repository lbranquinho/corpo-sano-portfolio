/**
 * Gráficos do Corpo Sano (Recharts).
 * Paleta categórica validada (ordem fixa, nunca reciclada):
 *   claro  #2563EB, #EC4899, #8B5CF6   |   escuro #3B82F6, #EC4899, #8B5CF6
 * Eixo único, marcas finas, grade discreta, legenda para 2+ séries e tooltip ao passar o mouse.
 */
import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { money } from "../lib/format";

const LIGHT = ["#2563EB", "#EC4899", "#8B5CF6"];
const DARK = ["#3B82F6", "#EC4899", "#8B5CF6"];

export function useChartTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const obs = new MutationObserver(() => setDark(document.documentElement.classList.contains("dark")));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  return {
    palette: dark ? DARK : LIGHT,
    grid: dark ? "#1E293B" : "#E2E8F0",
    axis: dark ? "#94A3B8" : "#64748B",
    surface: dark ? "#0F172A" : "#FFFFFF",
    tooltip: {
      contentStyle: {
        background: dark ? "#0F172A" : "#FFFFFF",
        border: `1px solid ${dark ? "#334155" : "#E2E8F0"}`,
        borderRadius: 12,
        fontSize: 12,
        color: dark ? "#E2E8F0" : "#1E293B",
      },
      labelStyle: { color: dark ? "#CBD5E1" : "#475569", fontWeight: 600 },
    },
  };
}

const compactMoney = (v: number) =>
  v >= 1000 ? `R$ ${(v / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil` : `R$ ${v.toLocaleString("pt-BR")}`;

type Series = { key: string; label: string };

export function MoneyLines({ data, x, series, height = 260 }: { data: any[]; x: string; series: Series[]; height?: number }) {
  const t = useChartTheme();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 0 }}>
        <CartesianGrid stroke={t.grid} vertical={false} />
        <XAxis dataKey={x} tick={{ fill: t.axis, fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={compactMoney} tick={{ fill: t.axis, fontSize: 11 }} axisLine={false} tickLine={false} width={74} />
        <Tooltip formatter={(v: number) => money(v)} {...t.tooltip} />
        {series.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={t.palette[i]} strokeWidth={2}
            dot={{ r: 4, strokeWidth: 2, stroke: t.surface, fill: t.palette[i] }} activeDot={{ r: 5, stroke: t.surface, strokeWidth: 2 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function GroupedBars({ data, x, series, height = 260, isMoney = true }: { data: any[]; x: string; series: Series[]; height?: number; isMoney?: boolean }) {
  const t = useChartTheme();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 0 }} barGap={2}>
        <CartesianGrid stroke={t.grid} vertical={false} />
        <XAxis dataKey={x} tick={{ fill: t.axis, fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={isMoney ? compactMoney : undefined} allowDecimals={false} tick={{ fill: t.axis, fontSize: 11 }}
          axisLine={false} tickLine={false} width={isMoney ? 74 : 32} />
        <Tooltip formatter={(v: number) => (isMoney ? money(v) : v)} cursor={{ fill: t.grid, opacity: 0.4 }} {...t.tooltip} />
        {series.length > 1 && <Legend iconType="square" wrapperStyle={{ fontSize: 12 }} />}
        {series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} fill={t.palette[i]} radius={[4, 4, 0, 0]} maxBarSize={22}
            stroke={t.surface} strokeWidth={1} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Barras horizontais de uma série (ranking). O título do cartão nomeia a série. */
export function RankBars({ data, isMoney = false, height }: { data: { name: string; value: number }[]; isMoney?: boolean; height?: number }) {
  const t = useChartTheme();
  const h = height ?? Math.max(120, data.length * 36 + 20);
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 56, left: 0, bottom: 0 }}>
        <CartesianGrid stroke={t.grid} horizontal={false} />
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="name" width={130} tick={{ fill: t.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
        <Tooltip formatter={(v: number) => (isMoney ? money(v) : v)} cursor={{ fill: t.grid, opacity: 0.4 }} {...t.tooltip} />
        <Bar dataKey="value" name={isMoney ? "Valor" : "Quantidade"} fill={t.palette[0]} radius={[0, 4, 4, 0]} maxBarSize={20}
          label={{ position: "right", fill: t.axis, fontSize: 11, formatter: (v: number) => (isMoney ? compactMoney(v) : v) }} />
      </BarChart>
    </ResponsiveContainer>
  );
}
