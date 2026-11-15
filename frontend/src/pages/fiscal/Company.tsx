import { ShieldCheck, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { CrudList } from "../../components/shared";
import { Alert, Badge, Button, Card, Checkbox, ConfirmButton, DataTable, Field, Input, Modal, PageHeader, Select, Tabs, Textarea, useToast } from "../../components/ui";
import { del, post, put, upload } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { date, dateTime } from "../../lib/format";
import { useAction, useGet } from "../../lib/hooks";
import { Readiness } from "./Invoices";

const REGIMES = [
  { value: "mei", label: "MEI (quando elegível)" }, { value: "simples_nacional", label: "Simples Nacional" },
  { value: "lucro_presumido", label: "Lucro Presumido" }, { value: "lucro_real", label: "Lucro Real" },
];

export function CompanyPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState("cadastro");
  return (
    <div>
      <PageHeader title="Cadastro fiscal" subtitle="Parâmetros configurados e validados pelo contador. O sistema não presume regime, CNAE, códigos ou alíquotas." />
      <Tabs value={tab} onChange={setTab} tabs={[{ key: "cadastro", label: "Empresa" }, { key: "certificados", label: "Certificado digital" }, { key: "codigos", label: "Códigos de serviço" }, { key: "integracao", label: "Integração NFS-e" }]} />
      {tab === "cadastro" && <CompanyForm />}
      {tab === "certificados" && <Certificates />}
      {tab === "codigos" && (
        <CrudList title="Códigos de serviço fiscal" path="/tax-service-codes" queryKey="tax-codes" canWrite={can("fiscal.settings")}
          emptyText="Cadastre os códigos conforme o enquadramento real do serviço (lista nacional de serviços / NBS), validados pelo contador."
          columns={[
            { key: "national_code", label: "cTribNac" }, { key: "municipal_code", label: "Cód. municipal", render: (r) => r.municipal_code || "—" },
            { key: "description", label: "Descrição" }, { key: "iss_rate", label: "ISS %", render: (r) => r.iss_rate ?? "—" },
            { key: "validated", label: "Validação", render: (r) => r.validated ? <Badge color="green">validado por {r.validated_by}</Badge> : <Badge color="yellow">pendente</Badge> },
          ]}
          transform={(b) => ({ ...b, iss_rate: b.iss_rate === null ? null : String(b.iss_rate) })}
          fields={[
            { key: "national_code", label: "Código de tributação nacional (cTribNac, 6 dígitos)", required: true, span: 3 },
            { key: "municipal_code", label: "Código de tributação municipal (se exigido)", span: 3 },
            { key: "lc116_item", label: "Subitem da lista de serviços (LC 116)", span: 2 },
            { key: "nbs_code", label: "Código NBS (9 dígitos)", span: 2 },
            { key: "iss_rate", label: "Alíquota ISS de referência (%)", type: "money", span: 2 },
            { key: "description", label: "Descrição", required: true, span: 6 },
            { key: "iss_withheld_default", label: "ISS normalmente retido pelo tomador", type: "checkbox", span: 3 },
            { key: "is_active", label: "Ativo", type: "checkbox", defaultValue: true, span: 3 },
            { key: "validated", label: "Validado pelo contador", type: "checkbox", span: 3 },
            { key: "validated_by", label: "Validado por", span: 3 },
            { key: "notes", label: "Observações", type: "textarea", span: 6 },
          ]} />
      )}
      {tab === "integracao" && <Integration />}
    </div>
  );
}

function CompanyForm() {
  const { can } = useAuth();
  const q = useGet<any>(["fiscal-company"], "/fiscal/company");
  const [f, setF] = useState<any>(null);
  const [validating, setValidating] = useState(false);
  const [val, setVal] = useState({ accountant_name: "", notes: "" });
  useEffect(() => {
    if (q.data) setF({ ...q.data, cnaes_secondary: (q.data.cnaes_secondary || []).join(", ") });
  }, [q.data]);
  const save = useAction(() => {
    const keys = ["legal_name", "trade_name", "cnpj", "municipal_registration", "state_registration", "zip_code", "street", "number", "complement", "district",
      "municipality_name", "uf", "ibge_code", "phone", "email", "cnae_main", "tax_regime", "regime_details", "op_simples_nacional", "reg_ap_trib_sn", "reg_esp_trib",
      "opening_date", "legal_representative", "legal_representative_cpf", "accountant_name", "accountant_crc", "accountant_email", "accountant_phone",
      "accountant_document", "has_employees", "dps_series", "next_dps_number", "layout_version"];
    const body: any = Object.fromEntries(keys.map((k) => [k, f[k] === "" ? null : f[k]]));
    body.cnaes_secondary = (f.cnaes_secondary || "").split(",").map((x: string) => x.trim()).filter(Boolean);
    ["op_simples_nacional", "reg_ap_trib_sn", "reg_esp_trib", "next_dps_number"].forEach((k) => (body[k] = body[k] === null ? (k === "reg_esp_trib" ? 0 : k === "next_dps_number" ? 1 : null) : Number(body[k])));
    body.dps_series = body.dps_series || "1";
    body.layout_version = body.layout_version || "1.01";
    return put("/fiscal/company", body);
  }, { invalidate: [["fiscal-company"], ["fiscal-readiness"]] });
  const validate = useAction(() => post("/fiscal/company/validate", { accountant_name: val.accountant_name, notes: val.notes || null }), { invalidate: [["fiscal-company"], ["fiscal-readiness"]], onDone: () => setValidating(false) });
  const production = useAction((v: boolean) => post(`/fiscal/company/production?enabled=${v}`), { invalidate: [["fiscal-company"], ["fiscal-readiness"]] });
  const env = useAction((e: string) => put("/fiscal/company/environment", { environment: e }), { invalidate: [["fiscal-company"], ["fiscal-readiness"]] });
  if (!f) return null;
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const ro = !can("fiscal.settings");
  return (
    <div className="space-y-4">
      <Readiness />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Situação" className="lg:col-span-1">
          <div className="space-y-3 text-sm">
            <p>Ambiente: <Badge color={f.nfse_environment === "producao" ? "blue" : "yellow"}>{f.nfse_environment === "producao" ? "Produção" : "Homologação"}</Badge></p>
            <p>Validação do contador: {f.validated ? <Badge color="green">validado por {f.validated_by_name} em {date(f.validated_at)}</Badge> : <Badge color="yellow">pendente</Badge>}</p>
            <p>Produção liberada: <Badge color={f.production_enabled ? "green" : "gray"}>{f.production_enabled ? "sim" : "não"}</Badge></p>
            <div className="flex flex-wrap gap-2">
              {(can("fiscal.settings") || can("fiscal.taxes")) && <Button size="sm" variant="secondary" icon={<ShieldCheck className="h-4 w-4" />} onClick={() => setValidating(true)}>Registrar validação</Button>}
              {can("fiscal.settings") && (f.production_enabled
                ? <Button size="sm" variant="secondary" onClick={() => production.mutate(false)}>Bloquear produção</Button>
                : <ConfirmButton size="sm" variant="primary" message="Liberar a emissão em produção? Exige cadastro validado e ao menos uma nota autorizada em homologação." onConfirm={() => production.mutateAsync(true)}>Liberar produção</ConfirmButton>)}
              {can("fiscal.settings") && f.production_enabled && (
                <Select className="!w-auto" value={f.nfse_environment} onChange={(e) => env.mutate(e.target.value)}><option value="homologacao">Emitir em homologação</option><option value="producao">Emitir em produção</option></Select>
              )}
            </div>
            <p className="text-xs text-slate-500">Alterar CNPJ, município, regime ou parâmetros da DPS revoga a validação e retorna à homologação.</p>
          </div>
        </Card>
        <Card title="Empresa" className="lg:col-span-2">
          <fieldset disabled={ro} className="grid gap-3 sm:grid-cols-6">
            <Field label="Razão social" className="sm:col-span-4"><Input value={f.legal_name || ""} onChange={set("legal_name")} /></Field>
            <Field label="CNPJ" className="sm:col-span-2"><Input value={f.cnpj || ""} onChange={set("cnpj")} /></Field>
            <Field label="Nome fantasia" className="sm:col-span-3"><Input value={f.trade_name || ""} onChange={set("trade_name")} /></Field>
            <Field label="Inscrição municipal" className="sm:col-span-2"><Input value={f.municipal_registration || ""} onChange={set("municipal_registration")} /></Field>
            <Field label="Inscrição estadual" className="sm:col-span-1"><Input value={f.state_registration || ""} onChange={set("state_registration")} /></Field>
            <Field label="CEP" className="sm:col-span-2"><Input value={f.zip_code || ""} onChange={set("zip_code")} /></Field>
            <Field label="Logradouro" className="sm:col-span-3"><Input value={f.street || ""} onChange={set("street")} /></Field>
            <Field label="Número" className="sm:col-span-1"><Input value={f.number || ""} onChange={set("number")} /></Field>
            <Field label="Complemento" className="sm:col-span-2"><Input value={f.complement || ""} onChange={set("complement")} /></Field>
            <Field label="Bairro" className="sm:col-span-2"><Input value={f.district || ""} onChange={set("district")} /></Field>
            <Field label="Município" className="sm:col-span-2"><Input value={f.municipality_name || ""} onChange={set("municipality_name")} /></Field>
            <Field label="UF" className="sm:col-span-1"><Input maxLength={2} value={f.uf || ""} onChange={set("uf")} /></Field>
            <Field label="Código IBGE" className="sm:col-span-2"><Input value={f.ibge_code || ""} onChange={set("ibge_code")} /></Field>
            <Field label="Telefone" className="sm:col-span-3"><Input value={f.phone || ""} onChange={set("phone")} /></Field>
            <Field label="E-mail" className="sm:col-span-3"><Input value={f.email || ""} onChange={set("email")} /></Field>
            <Field label="CNAE principal" className="sm:col-span-2"><Input value={f.cnae_main || ""} onChange={set("cnae_main")} /></Field>
            <Field label="CNAEs secundários (vírgula)" className="sm:col-span-4"><Input value={f.cnaes_secondary || ""} onChange={set("cnaes_secondary")} /></Field>
            <Field label="Data de abertura" className="sm:col-span-2"><Input type="date" value={f.opening_date || ""} onChange={set("opening_date")} /></Field>
            <Field label="Responsável legal" className="sm:col-span-2"><Input value={f.legal_representative || ""} onChange={set("legal_representative")} /></Field>
            <Field label="CPF do responsável" className="sm:col-span-2"><Input value={f.legal_representative_cpf || ""} onChange={set("legal_representative_cpf")} /></Field>
            <div className="sm:col-span-6"><Checkbox label="Possui empregados (habilita obrigações trabalhistas aplicáveis)" checked={!!f.has_employees} onChange={(v) => setF({ ...f, has_employees: v })} /></div>
          </fieldset>
        </Card>
        <Card title="Regime e enquadramento" className="lg:col-span-2">
          <fieldset disabled={ro} className="grid gap-3 sm:grid-cols-6">
            <Field label="Regime tributário" className="sm:col-span-3"><Select value={f.tax_regime || ""} onChange={set("tax_regime")}><option value="">Não definido</option>{REGIMES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}</Select></Field>
            <Field label="Situação no Simples Nacional (opSimpNac)" className="sm:col-span-3" hint="1 = não optante · 2 = MEI · 3 = ME/EPP">
              <Select value={f.op_simples_nacional ?? ""} onChange={set("op_simples_nacional")}><option value="">—</option><option value="1">1 — Não optante</option><option value="2">2 — Optante MEI</option><option value="3">3 — Optante ME/EPP</option></Select>
            </Field>
            <Field label="Regime de apuração SN (regApTribSN)" className="sm:col-span-3" hint="Somente ME/EPP — informado pelo contador"><Input type="number" min={1} max={3} value={f.reg_ap_trib_sn ?? ""} onChange={set("reg_ap_trib_sn")} /></Field>
            <Field label="Regime especial de tributação (regEspTrib)" className="sm:col-span-3" hint="0 = nenhum"><Input type="number" min={0} max={9} value={f.reg_esp_trib ?? 0} onChange={set("reg_esp_trib")} /></Field>
            <Field label="Enquadramento (anexo, fator R, observações do contador)" className="sm:col-span-6"><Textarea value={f.regime_details || ""} onChange={set("regime_details")} /></Field>
            <Field label="Série da DPS" className="sm:col-span-2"><Input value={f.dps_series || ""} onChange={set("dps_series")} disabled={f.dps_number_used} /></Field>
            <Field label="Próximo número da DPS" className="sm:col-span-2"><Input type="number" min={1} value={f.next_dps_number || 1} onChange={set("next_dps_number")} /></Field>
            <Field label="Versão do leiaute" className="sm:col-span-2" hint="Conforme documentação vigente (gov.br/nfse)"><Input value={f.layout_version || ""} onChange={set("layout_version")} /></Field>
          </fieldset>
        </Card>
        <Card title="Contador responsável">
          <fieldset disabled={ro} className="grid gap-3">
            <Field label="Nome"><Input value={f.accountant_name || ""} onChange={set("accountant_name")} /></Field>
            <Field label="CRC"><Input value={f.accountant_crc || ""} onChange={set("accountant_crc")} /></Field>
            <Field label="CPF/CNPJ"><Input value={f.accountant_document || ""} onChange={set("accountant_document")} /></Field>
            <Field label="E-mail"><Input value={f.accountant_email || ""} onChange={set("accountant_email")} /></Field>
            <Field label="Telefone"><Input value={f.accountant_phone || ""} onChange={set("accountant_phone")} /></Field>
          </fieldset>
        </Card>
      </div>
      {!ro && <div className="flex justify-end"><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>Salvar cadastro fiscal</Button></div>}
      <Modal open={validating} onClose={() => setValidating(false)} title="Registrar validação do contador" size="sm"
        footer={<Button loading={validate.isPending} disabled={val.accountant_name.length < 3} onClick={() => validate.mutate(undefined)}>Registrar</Button>}>
        <div className="space-y-3">
          <Alert kind="info">Registre somente após o contador conferir regime, enquadramento, códigos de serviço e alíquotas.</Alert>
          <Field label="Contador que validou" required><Input value={val.accountant_name} onChange={(e) => setVal({ ...val, accountant_name: e.target.value })} /></Field>
          <Field label="Observações"><Textarea value={val.notes} onChange={(e) => setVal({ ...val, notes: e.target.value })} /></Field>
        </div>
      </Modal>
    </div>
  );
}

function Certificates() {
  const { can } = useAuth();
  const toast = useToast();
  const list = useGet<any[]>(["certificates"], "/fiscal/certificates");
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [alias, setAlias] = useState("Certificado A1");
  const [busy, setBusy] = useState(false);
  const activate = useAction((id: string) => post(`/fiscal/certificates/${id}/activate`), { invalidate: [["certificates"], ["fiscal-readiness"]] });
  const remove = useAction((id: string) => del(`/fiscal/certificates/${id}`), { invalidate: [["certificates"], ["fiscal-readiness"]] });
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {can("fiscal.settings") && (
        <Card title="Enviar certificado A1 (.pfx/.p12)">
          <div className="space-y-3">
            <Field label="Arquivo"><Input type="file" accept=".pfx,.p12" onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field>
            <Field label="Senha do certificado"><Input type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
            <Field label="Identificação"><Input value={alias} onChange={(e) => setAlias(e.target.value)} /></Field>
            <Button icon={<Upload className="h-4 w-4" />} loading={busy} disabled={!file || !password} onClick={async () => {
              setBusy(true);
              try {
                const fd = new FormData();
                fd.append("file", file!); fd.append("password", password); fd.append("alias", alias); fd.append("activate", "true");
                const r = await upload("/fiscal/certificates", fd);
                toast.success(r.message);
                setFile(null); setPassword("");
                list.refetch();
              } catch (e) { toast.error(e); } finally { setBusy(false); }
            }}>Enviar e ativar</Button>
            <p className="text-xs text-slate-500">O arquivo e a senha são armazenados criptografados no servidor e nunca retornam ao navegador. Use o certificado da própria empresa (não use credenciais pessoais do contador sem autorização).</p>
          </div>
        </Card>
      )}
      <Card title="Certificados" padded={false} className="lg:col-span-2">
        <DataTable rows={list.data || []} columns={[
          { key: "alias", label: "Identificação" },
          { key: "subject", label: "Titular", render: (r) => <span className="text-xs">{r.subject}</span> },
          { key: "valid_to", label: "Validade", render: (r) => <span className={r.days_to_expire < 30 ? "font-semibold text-rose-600" : ""}>{dateTime(r.valid_to)}</span> },
          { key: "is_active", label: "", render: (r) => r.expired ? <Badge color="red">vencido</Badge> : r.is_active ? <Badge color="green">ativo</Badge> : can("fiscal.settings") && <Button size="sm" variant="secondary" onClick={() => activate.mutate(r.id)}>Ativar</Button> },
          { key: "a", label: "", render: (r) => can("fiscal.settings") && <ConfirmButton size="sm" message="Remover este certificado do sistema?" onConfirm={() => remove.mutateAsync(r.id)}>Remover</ConfirmButton> },
        ]} />
      </Card>
    </div>
  );
}

function Integration() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Sistema Nacional NFS-e (Emissor Público Nacional)">
        <div className="space-y-2 text-sm">
          <p>Comunicação oficial via API da Sefin Nacional com autenticação mútua (mTLS) pelo certificado ICP-Brasil da empresa:</p>
          <ul className="list-disc pl-5 text-slate-600 dark:text-slate-300">
            <li>Emissão síncrona: <code>POST /nfse</code> (DPS assinada, compactada e codificada)</li>
            <li>Consulta: <code>GET /nfse/{"{chave}"}</code> e <code>GET /dps/{"{id}"}</code></li>
            <li>Eventos (cancelamento): <code>POST /nfse/{"{chave}"}/eventos</code></li>
            <li>DANFSe pelo Ambiente de Dados Nacional (ADN), quando disponibilizado</li>
          </ul>
          <p>As URLs dos ambientes de produção restrita (homologação) e produção ficam nas configurações do servidor e devem ser conferidas na documentação vigente em gov.br/nfse.</p>
        </div>
      </Card>
      <Card title="Boas práticas">
        <div className="space-y-2 text-sm">
          <Alert kind="info">Teste em homologação antes de liberar produção. Uma nota só é considerada emitida após confirmação oficial.</Alert>
          <Alert kind="warning">Instale os esquemas XSD oficiais (pacote "NFSe-ESQUEMAS_XSD" em gov.br/nfse) no servidor: a validação local é obrigatória em produção.</Alert>
          <p className="text-xs text-slate-500">Municípios com sistema próprio exigem um adaptador específico do provedor; a arquitetura do Corpo Sano já é modular para isso.</p>
        </div>
      </Card>
    </div>
  );
}
