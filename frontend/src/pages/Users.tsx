import { useState } from "react";
import { Alert, Badge, Button, Card, Checkbox, ConfirmButton, DataTable, Empty, Field, Input, Modal, PageHeader, Pagination, Select, Tabs } from "../components/ui";
import { del, post, put } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime } from "../lib/format";
import { useAction, useGet } from "../lib/hooks";

export default function Users() {
  const { can } = useAuth();
  const tabs = [...(can("users.manage") ? [{ key: "usuarios", label: "Usuários" }, { key: "perfis", label: "Perfis e permissões" }] : []), ...(can("audit.read") ? [{ key: "auditoria", label: "Auditoria" }] : [])];
  const [tab, setTab] = useState(tabs[0]?.key);
  return (
    <div>
      <PageHeader title="Usuários e permissões" subtitle="Acesso individual, perfis separados por área (administrativa, clínica, financeira e fiscal) e trilha de auditoria." />
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      {tab === "usuarios" && <UserList />}
      {tab === "perfis" && <Roles />}
      {tab === "auditoria" && <Audit />}
    </div>
  );
}

function UserList() {
  const users = useGet<any[]>(["users"], "/users");
  const roles = useGet<any[]>(["roles"], "/roles");
  const profs = useGet<any[]>(["professionals"], "/settings/professionals", { active: true });
  const [editing, setEditing] = useState<any>(null);
  const [perm, setPerm] = useState<any>(null);
  const [reset, setReset] = useState<any>(null);
  const unlock = useAction((id: string) => post(`/users/${id}/unlock`), { invalidate: [["users"]] });
  const revoke = useAction((id: string) => post(`/users/${id}/revoke-sessions`));
  return (
    <Card padded={false} title="Usuários" actions={<Button size="sm" onClick={() => setEditing({})}>Novo usuário</Button>}>
      <DataTable rows={users.data || []} columns={[
        { key: "name", label: "Nome", render: (r) => <span className="font-medium">{r.name}</span> },
        { key: "email", label: "E-mail" },
        { key: "role_name", label: "Perfil", render: (r) => <Badge color="violet">{r.role_name}</Badge> },
        { key: "last_login_at", label: "Último acesso", render: (r) => dateTime(r.last_login_at) },
        { key: "is_active", label: "Situação", render: (r) => <span className="flex gap-1">{r.is_active ? <Badge color="green">ativo</Badge> : <Badge color="gray">inativo</Badge>}
          {r.locked_until && new Date(r.locked_until) > new Date() && <Badge color="red">bloqueado</Badge>}{r.must_change_password && <Badge color="yellow">senha provisória</Badge>}</span> },
        { key: "a", label: "", render: (r) => (
          <div className="flex flex-wrap justify-end gap-1">
            <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Editar</Button>
            <Button size="sm" variant="ghost" onClick={() => setPerm(r)}>Permissões</Button>
            <Button size="sm" variant="ghost" onClick={() => setReset(r)}>Senha</Button>
            {r.locked_until && <Button size="sm" variant="ghost" onClick={() => unlock.mutate(r.id)}>Desbloquear</Button>}
            <ConfirmButton size="sm" variant="primary" message={`Encerrar todas as sessões de ${r.name}?`} onConfirm={() => revoke.mutateAsync(r.id)}>Encerrar sessões</ConfirmButton>
          </div>) },
      ]} />
      {editing && <UserForm user={editing} roles={roles.data || []} profs={profs.data || []} onClose={() => setEditing(null)} />}
      {perm && <UserPermissions user={perm} onClose={() => setPerm(null)} />}
      {reset && <ResetPassword user={reset} onClose={() => setReset(null)} />}
    </Card>
  );
}

function UserForm({ user, roles, profs, onClose }: { user: any; roles: any[]; profs: any[]; onClose: () => void }) {
  const [f, setF] = useState({ name: user.name || "", email: user.email || "", role_id: user.role_id || "", professional_id: user.professional_id || "", is_active: user.is_active ?? true, password: "" });
  const save = useAction(() => user.id
    ? put(`/users/${user.id}`, { name: f.name, email: f.email, role_id: f.role_id, professional_id: f.professional_id || null, is_active: f.is_active })
    : post("/users", { name: f.name, email: f.email, role_id: f.role_id, professional_id: f.professional_id || null, password: f.password }),
  { success: "Usuário salvo.", invalidate: [["users"]], onDone: onClose });
  const role = roles.find((r) => r.id === f.role_id);
  return (
    <Modal open onClose={onClose} title={user.id ? "Editar usuário" : "Novo usuário"} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>Cancelar</Button><Button loading={save.isPending} disabled={!f.name || !f.email || !f.role_id || (!user.id && f.password.length < 10)} onClick={() => save.mutate(undefined)}>Salvar</Button></>}>
      <div className="grid gap-3">
        <Field label="Nome" required><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="E-mail (login)" required><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Perfil" required><Select value={f.role_id} onChange={(e) => setF({ ...f, role_id: e.target.value })}><option value="">Selecione</option>{roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select></Field>
        {role && <p className="text-xs text-slate-500">{role.description}</p>}
        <Field label="Profissional vinculado" hint="Massoterapeutas veem apenas a própria agenda e os próprios clientes."><Select value={f.professional_id} onChange={(e) => setF({ ...f, professional_id: e.target.value })}><option value="">Nenhum</option>{profs.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
        {!user.id && <Field label="Senha provisória" hint="Mínimo 10 caracteres com letras e números. A troca será exigida no 1º acesso." required><Input type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>}
        {user.id && <Checkbox label="Usuário ativo" checked={f.is_active} onChange={(v) => setF({ ...f, is_active: v })} />}
      </div>
    </Modal>
  );
}

function ResetPassword({ user, onClose }: { user: any; onClose: () => void }) {
  const [pw, setPw] = useState("");
  const save = useAction(() => post(`/users/${user.id}/reset-password`, { password: pw }), { invalidate: [["users"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title={`Senha provisória — ${user.name}`} size="sm" footer={<Button loading={save.isPending} disabled={pw.length < 10} onClick={() => save.mutate(undefined)}>Definir</Button>}>
      <Field label="Nova senha provisória" hint="Informe-a pessoalmente ao usuário; ela deverá ser trocada no próximo acesso."><Input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
    </Modal>
  );
}

function PermissionGrid({ selected, onToggle, roleSet }: { selected: (code: string) => boolean | null; onToggle: (code: string) => void; roleSet?: Set<string> }) {
  const perms = useGet<any[]>(["permissions"], "/permissions");
  const groups: Record<string, any[]> = {};
  (perms.data || []).forEach((p) => (groups[p.module] = [...(groups[p.module] || []), p]));
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {Object.entries(groups).map(([mod, items]) => (
        <div key={mod} className="rounded-xl border border-slate-100 p-3 dark:border-slate-800">
          <p className="mb-2 text-xs font-semibold uppercase text-slate-500">{mod}</p>
          <div className="space-y-1.5">
            {items.map((p) => {
              const v = selected(p.code);
              return (
                <label key={p.code} className="flex items-start gap-2 text-sm">
                  <input type="checkbox" className="mt-0.5" checked={!!v} onChange={() => onToggle(p.code)} />
                  <span>{p.description} {roleSet && (roleSet.has(p.code) ? <Badge color="gray">do perfil</Badge> : null)}</span>
                </label>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function UserPermissions({ user, onClose }: { user: any; onClose: () => void }) {
  const q = useGet<any>(["user-perms", user.id], `/users/${user.id}/permissions`);
  const [overrides, setOverrides] = useState<Record<string, boolean> | null>(null);
  const roleSet = new Set<string>(q.data?.role_permissions || []);
  const ov = overrides ?? Object.fromEntries((q.data?.overrides || []).map((o: any) => [o.code, o.allow]));
  const effective = (code: string) => (code in ov ? ov[code] : roleSet.has(code));
  const toggle = (code: string) => {
    const next = { ...ov };
    const target = !effective(code);
    if (target === roleSet.has(code)) delete next[code];
    else next[code] = target;
    setOverrides(next);
  };
  const save = useAction(() => put(`/users/${user.id}/permissions`, Object.entries(ov).map(([code, allow]) => ({ code, allow }))), { onDone: onClose });
  return (
    <Modal open onClose={onClose} title={`Permissões personalizadas — ${user.name}`} size="lg" footer={<Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar</Button>}>
      <Alert kind="info">Marque/desmarque para conceder ou revogar além do perfil "{user.role_name}". Itens alterados em relação ao perfil são personalizações individuais.</Alert>
      <div className="mt-3"><PermissionGrid selected={effective} onToggle={toggle} roleSet={roleSet} /></div>
    </Modal>
  );
}

function Roles() {
  const roles = useGet<any[]>(["roles"], "/roles");
  const [editing, setEditing] = useState<any>(null);
  const remove = useAction((id: string) => del(`/roles/${id}`), { invalidate: [["roles"]] });
  return (
    <Card padded={false} title="Perfis" actions={<Button size="sm" onClick={() => setEditing({ permissions: [] })}>Novo perfil</Button>}>
      <DataTable rows={roles.data || []} columns={[
        { key: "name", label: "Perfil", render: (r) => <span className="font-medium">{r.name} {r.is_system && <Badge color="gray">padrão</Badge>}</span> },
        { key: "description", label: "Descrição", render: (r) => r.description || "—" },
        { key: "permissions", label: "Permissões", render: (r) => r.permissions.length },
        { key: "a", label: "", render: (r) => (
          <div className="flex justify-end gap-1">
            {r.code !== "admin" && <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Editar</Button>}
            {!r.is_system && <ConfirmButton size="sm" message="Excluir este perfil?" onConfirm={() => remove.mutateAsync(r.id)}>Excluir</ConfirmButton>}
          </div>) },
      ]} />
      {editing && <RoleForm role={editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function RoleForm({ role, onClose }: { role: any; onClose: () => void }) {
  const [f, setF] = useState({ name: role.name || "", description: role.description || "", permissions: new Set<string>(role.permissions || []) });
  const save = useAction(() => {
    const body = { name: f.name, description: f.description || null, permissions: [...f.permissions] };
    return role.id ? put(`/roles/${role.id}`, body) : post("/roles", body);
  }, { success: "Perfil salvo.", invalidate: [["roles"]], onDone: onClose });
  return (
    <Modal open onClose={onClose} title={role.id ? `Perfil: ${role.name}` : "Novo perfil"} size="lg" footer={<Button loading={save.isPending} disabled={f.name.length < 2} onClick={() => save.mutate(undefined)}>Salvar</Button>}>
      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <Field label="Nome"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Descrição"><Input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      </div>
      <PermissionGrid selected={(c) => f.permissions.has(c)} onToggle={(c) => { const s = new Set(f.permissions); s.has(c) ? s.delete(c) : s.add(c); setF({ ...f, permissions: s }); }} />
    </Modal>
  );
}

function Audit() {
  const [f, setF] = useState({ action: "", user_name: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const q = useGet<any>(["audit"], "/audit-logs", { ...f, page });
  return (
    <Card padded={false} title="Trilha de auditoria" actions={<>
      <Input className="!w-40" placeholder="Ação" value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })} />
      <Input className="!w-40" placeholder="Usuário" value={f.user_name} onChange={(e) => setF({ ...f, user_name: e.target.value })} />
      <Input type="date" className="!w-auto" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} />
      <Input type="date" className="!w-auto" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} />
    </>}>
      <DataTable rows={q.data?.items || []} empty={<Empty title="Nenhum registro" />} columns={[
        { key: "created_at", label: "Data", render: (r) => dateTime(r.created_at) },
        { key: "user_name", label: "Usuário", render: (r) => r.user_name || "—" },
        { key: "action", label: "Ação", render: (r) => <span>{r.action} {r.sensitive && <Badge color="pink">sensível</Badge>}</span> },
        { key: "entity", label: "Entidade", render: (r) => r.entity || "—" },
        { key: "ip", label: "IP" },
        { key: "details", label: "Detalhes", render: (r) => <span className="line-clamp-2 max-w-sm text-xs text-slate-500">{r.details ? JSON.stringify(r.details) : ""}</span> },
      ]} />
      <Pagination page={page} pageSize={50} total={q.data?.total || 0} onPage={setPage} />
    </Card>
  );
}
