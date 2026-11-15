import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppLayout, MENU } from "./components/Layout";
import { Empty, Loading } from "./components/ui";
import { useAuth } from "./lib/auth";
import Login from "./pages/Login";
import MyAccount from "./pages/MyAccount";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Agenda = lazy(() => import("./pages/Agenda"));
const Customers = lazy(() => import("./pages/Customers"));
const CustomerProfile = lazy(() => import("./pages/CustomerProfile"));
const Crm = lazy(() => import("./pages/Crm"));
const Treatments = lazy(() => import("./pages/Treatments"));
const Services = lazy(() => import("./pages/Services"));
const Packages = lazy(() => import("./pages/Packages"));
const Finance = lazy(() => import("./pages/Finance"));
const Fiscal = lazy(() => import("./pages/fiscal/FiscalRoutes"));
const Reports = lazy(() => import("./pages/Reports"));
const WhatsApp = lazy(() => import("./pages/WhatsApp"));
const Users = lazy(() => import("./pages/Users"));
const SettingsPage = lazy(() => import("./pages/Settings"));

function Guard({ perms, children }: { perms: string[]; children: ReactNode }) {
  const { canAny } = useAuth();
  if (!canAny(...perms)) return <Empty title="Acesso não permitido" text="Seu perfil não possui permissão para este módulo." />;
  return <>{children}</>;
}

function Home() {
  const { canAny } = useAuth();
  if (canAny("dashboard.view")) return <Dashboard />;
  const first = MENU.find((m) => m.to !== "/" && canAny(...m.perms));
  return first ? <Navigate to={first.to} replace /> : <Empty title="Sem módulos liberados" text="Solicite acesso ao administrador." />;
}

export default function App() {
  const { me, loading } = useAuth();
  if (loading) return <Loading text="Iniciando Corpo Sano..." />;
  if (!me) return <Login />;
  if (me.must_change_password) return <MyAccount forced />;
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<Home />} />
          <Route path="agenda" element={<Guard perms={["agenda.read"]}><Agenda /></Guard>} />
          <Route path="clientes" element={<Guard perms={["customers.read"]}><Customers /></Guard>} />
          <Route path="clientes/:id" element={<Guard perms={["customers.read"]}><CustomerProfile /></Guard>} />
          <Route path="crm" element={<Guard perms={["crm.read"]}><Crm /></Guard>} />
          <Route path="atendimentos" element={<Guard perms={["clinical.read"]}><Treatments /></Guard>} />
          <Route path="servicos" element={<Guard perms={["services.read"]}><Services /></Guard>} />
          <Route path="pacotes" element={<Guard perms={["packages.read"]}><Packages /></Guard>} />
          <Route path="financeiro" element={<Guard perms={["finance.read", "finance.payments"]}><Finance /></Guard>} />
          <Route path="fiscal/*" element={<Guard perms={["fiscal.read"]}><Fiscal /></Guard>} />
          <Route path="relatorios" element={<Guard perms={["reports.operational", "reports.financial", "reports.fiscal"]}><Reports /></Guard>} />
          <Route path="whatsapp" element={<Guard perms={["whatsapp.read"]}><WhatsApp /></Guard>} />
          <Route path="usuarios" element={<Guard perms={["users.manage", "audit.read"]}><Users /></Guard>} />
          <Route path="configuracoes" element={<Guard perms={["settings.manage", "agenda.settings", "finance.settings", "backups.manage"]}><SettingsPage /></Guard>} />
          <Route path="minha-conta" element={<MyAccount />} />
          <Route path="login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<Empty title="Página não encontrada" />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
