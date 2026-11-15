import { Navigate, Route, Routes } from "react-router-dom";
import { Empty } from "../../components/ui";
import { useAuth } from "../../lib/auth";
import { DocumentsPage, ExportPage, LedgerPage, ObligationsPage, ReceivedPage, TaxesPage } from "./Accounting";
import { CompanyPage } from "./Company";
import { InvoiceDetail, InvoicesPage, IssuePage } from "./Invoices";

/** Corpo Sano Contábil — ferramenta de gestão fiscal e apoio contábil (não substitui a escrituração oficial). */
export default function FiscalRoutes() {
  const { can } = useAuth();
  return (
    <Routes>
      <Route index element={<Navigate to={can("fiscal.issue") ? "emissao" : "notas"} replace />} />
      <Route path="emissao" element={can("fiscal.issue") ? <IssuePage /> : <Empty title="Sem permissão para emitir notas" />} />
      <Route path="notas" element={<InvoicesPage />} />
      <Route path="notas/:id" element={<InvoiceDetail />} />
      <Route path="recebidas" element={<ReceivedPage />} />
      <Route path="tributos" element={<TaxesPage />} />
      <Route path="receitas-despesas" element={<LedgerPage />} />
      <Route path="obrigacoes" element={<ObligationsPage />} />
      <Route path="documentos" element={<DocumentsPage />} />
      <Route path="exportacao" element={<ExportPage />} />
      <Route path="configuracoes" element={<CompanyPage />} />
      <Route path="*" element={<Empty title="Página não encontrada" />} />
    </Routes>
  );
}
