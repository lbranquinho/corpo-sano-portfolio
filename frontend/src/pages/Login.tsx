import { Eye, EyeOff, Lock, Mail } from "lucide-react";
import { useEffect, useState } from "react";
import { Logo } from "../components/Logo";
import { Alert, Button, Field, Input } from "../components/ui";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { login, notice } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hasLogo, setHasLogo] = useState(false);

  useEffect(() => {
    fetch("/api/v1/settings/clinic/logo/status")
      .then((r) => (r.ok ? r.json() : { has_logo: false }))
      .then((d: { has_logo?: boolean }) => setHasLogo(!!d.has_logo))
      .catch(() => setHasLogo(false));
  }, []);

  return (
    <div className="flex min-h-full">
      <div className="brand-gradient relative hidden flex-1 items-center justify-center overflow-hidden lg:flex">
        <div className="absolute -left-24 -top-24 h-96 w-96 rounded-full bg-white/10 blur-2xl" />
        <div className="absolute -bottom-32 right-0 h-[28rem] w-[28rem] rounded-full bg-aqua/20 blur-3xl" />
        <div className="relative max-w-2xl px-10 text-white">
          <Logo light large />
          <p className="mt-10 text-brand-100">Agenda, clientes, atendimentos, financeiro e fiscal integrados em um só lugar — com segurança e privacidade.</p>
        </div>
      </div>
      <div className="flex flex-1 flex-col bg-white px-6 dark:bg-slate-900">
        <div className="flex flex-1 items-center justify-center py-10">
        <form className="w-full max-w-sm space-y-5" onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await login(email.trim(), password);
          } catch (err) {
            setError(err instanceof Error ? err.message : "Não foi possível entrar.");
          } finally {
            setBusy(false);
          }
        }}>
          <div className="flex justify-center lg:hidden">
            <Logo hasLogo={hasLogo} />
          </div>
          {hasLogo && (
            <div className="hidden justify-center lg:flex">
              <Logo hasLogo className="!h-28" />
            </div>
          )}
          <div>
            <h1 className="text-2xl font-semibold">Entrar</h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Acesse com seu e-mail e senha individuais.</p>
          </div>
          {notice && <Alert kind="warning">{notice}</Alert>}
          {error && <Alert kind="danger">{error}</Alert>}
          <Field label="E-mail">
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" aria-hidden />
              <Input type="email" autoComplete="username" required className="pl-9" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
          </Field>
          <Field label="Senha">
            <div className="relative">
              <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500 dark:text-slate-400" aria-hidden />
              <Input type={showPw ? "text" : "password"} autoComplete="current-password" required className="pl-9 pr-12" value={password} onChange={(e) => setPassword(e.target.value)} />
              <button type="button" className="absolute right-0.5 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
                onClick={() => setShowPw((v) => !v)} aria-label={showPw ? "Ocultar senha" : "Mostrar senha"} aria-pressed={showPw}>
                {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </Field>
          <Button type="submit" className="w-full" loading={busy}>Entrar</Button>
          <p className="text-center text-xs text-slate-500 dark:text-slate-400">
            Esqueceu a senha? Solicite ao administrador uma senha provisória.
            <br />Conexão protegida. Seus acessos são registrados para auditoria.
          </p>
        </form>
        </div>
        <footer className="pb-4 pt-2 text-center text-xs leading-snug text-slate-500 dark:text-slate-400">
          Sistema integrado Corpo Sano © Copyright 2026 - Cuidado, organização e tranquilidade para a sua clínica.
        </footer>
      </div>
    </div>
  );
}
