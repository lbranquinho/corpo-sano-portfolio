import { useState } from "react";
import { del, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime } from "../lib/format";
import { useAction, useGet } from "../lib/hooks";
import { Logo } from "../components/Logo";
import { Alert, Button, Card, DataTable, Field, Input, PageHeader, useToast } from "../components/ui";

function PasswordForm({ onDone }: { onDone: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  return (
    <form className="space-y-3" onSubmit={async (e) => {
      e.preventDefault();
      if (next !== confirm) return toast.error("A confirmação não confere com a nova senha.");
      setBusy(true);
      try {
        const r = await post("/auth/change-password", { current_password: current, new_password: next });
        toast.success(r.message);
        setCurrent(""); setNext(""); setConfirm("");
        onDone();
      } catch (err) {
        toast.error(err);
      } finally {
        setBusy(false);
      }
    }}>
      <Field label="Senha atual" required><Input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required /></Field>
      <Field label="Nova senha" hint="Mínimo de 10 caracteres, com letras e números." required>
        <Input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
      </Field>
      <Field label="Confirme a nova senha" required><Input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required /></Field>
      <Button type="submit" loading={busy}>Alterar senha</Button>
    </form>
  );
}

export default function MyAccount({ forced = false }: { forced?: boolean }) {
  const { me, reload, logout } = useAuth();
  const sessions = useGet<any[]>(["my-sessions"], forced ? null : "/auth/sessions");
  const revoke = useAction((id: string) => del(`/auth/sessions/${id}`), { invalidate: [["my-sessions"]] });

  if (forced) {
    return (
      <div className="flex min-h-full items-center justify-center p-6">
        <div className="card w-full max-w-md space-y-4 p-6">
          <Logo />
          <h1 className="text-lg font-semibold">Defina sua senha pessoal</h1>
          <Alert kind="info">Por segurança, troque a senha provisória antes de acessar o sistema.</Alert>
          <PasswordForm onDone={() => reload()} />
          <Button variant="ghost" onClick={() => logout()}>Sair</Button>
        </div>
      </div>
    );
  }
  return (
    <div>
      <PageHeader title="Minha conta" subtitle={`${me?.name} · ${me?.email} · ${me?.role_name}`} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Alterar senha"><PasswordForm onDone={() => sessions.refetch()} /></Card>
        <Card title="Sessões ativas" padded={false}>
          <DataTable rows={sessions.data || []} columns={[
            { key: "created_at", label: "Início", render: (r) => dateTime(r.created_at) },
            { key: "last_used_at", label: "Última atividade", render: (r) => dateTime(r.last_used_at) },
            { key: "ip", label: "IP" },
            { key: "act", label: "", render: (r) => r.current ? <span className="text-xs text-emerald-700 dark:text-emerald-400">Esta sessão</span> :
              <Button size="sm" variant="secondary" onClick={() => revoke.mutate(r.id)}>Encerrar</Button> },
          ]} />
        </Card>
      </div>
      <p className="mt-4 text-xs text-slate-500">Dica: a sessão é encerrada automaticamente após {me?.session_idle_minutes} minutos sem atividade.</p>
    </div>
  );
}
