import clsx from "clsx";
import { useId, useState } from "react";

/** Marca Corpo Sano: lótus em degradê azul (inspirado no logotipo da clínica). */
export function LotusMark({ className }: { className?: string }) {
  // id único por instância: com id repetido, o navegador usa o degradê de uma cópia oculta
  // (ex.: painel do computador escondido no celular) e as pétalas ficam invisíveis
  const gid = `cs-lotus-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#1E3A8A" />
          <stop offset="0.6" stopColor="#2563EB" />
          <stop offset="1" stopColor="#38BDF8" />
        </linearGradient>
      </defs>
      <path d="M32 6 C40 16 42 30 32 46 C22 30 24 16 32 6 Z" fill={`url(#${gid})`} />
      <path d="M4 26 C18 24 28 32 32 46 C18 46 8 38 4 26 Z" fill={`url(#${gid})`} opacity="0.92" />
      <path d="M60 26 C46 24 36 32 32 46 C46 46 56 38 60 26 Z" fill={`url(#${gid})`} opacity="0.92" />
      <circle cx="10" cy="14" r="3" fill="#1E3A8A" />
      <circle cx="55" cy="18" r="2.4" fill="#1E3A8A" />
      <circle cx="58" cy="34" r="1.6" fill="#1E3A8A" />
    </svg>
  );
}

/** Usa o logotipo enviado em Configurações; se não houver, exibe a marca padrão. */
export function Logo({ hasLogo, compact = false, light = false, large = false, className }: {
  hasLogo?: boolean; compact?: boolean; light?: boolean; large?: boolean; className?: string;
}) {
  const [failed, setFailed] = useState(false);
  if (hasLogo && !failed) {
    return (
      <img src="/api/v1/settings/clinic/logo" alt="Corpo Sano" onError={() => setFailed(true)}
        className={clsx("object-contain", compact ? "h-9 w-9" : large ? "h-[10.5rem] w-auto" : "h-14 w-auto", className)} />
    );
  }
  // large = 3x o tamanho padrão (painel da tela de login no computador)
  return (
    <div className={clsx("flex", large ? "flex-col items-start gap-4" : "items-center gap-2", className)}>
      <LotusMark className={compact ? "h-8 w-8" : large ? "h-[7.5rem] w-[7.5rem] shrink-0" : "h-10 w-10"} />
      {!compact && (
        <div className="leading-none">
          <p className={clsx("font-script font-bold", large ? "text-7xl" : "text-2xl", light ? "text-white" : "text-brand-900 dark:text-white")}>Corpo Sano</p>
          <p className={clsx("uppercase", large ? "mt-5 text-lg tracking-[0.35em]" : "mt-0.5 text-[10px] tracking-[0.25em]", light ? "text-brand-100" : "text-brand-600 dark:text-brand-100")}>
            saúde e bem-estar
          </p>
        </div>
      )}
    </div>
  );
}
