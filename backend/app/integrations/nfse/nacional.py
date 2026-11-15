"""Adaptador do Sistema Nacional NFS-e — API do Emissor Público Nacional (Sefin Nacional) e ADN.

Referência: "Manual dos Contribuintes — Guia para utilização das APIs do Emissor Público Nacional"
(gov.br/nfse, documentação técnica atual) e especificação Swagger da Sefin Nacional:
  POST /nfse                                   { "dpsXmlGZipB64": ... }  -> 201 NFSePostResponseSucesso
  GET  /nfse/{chaveAcesso}                                                -> nfseXmlGZipB64
  GET  /dps/{id}                                                          -> chaveAcesso
  POST /nfse/{chaveAcesso}/eventos             { "pedidoRegistroEventoXmlGZipB64": ... }
  GET  /nfse/{chaveAcesso}/eventos
Autenticação: TLS mútuo com certificado ICP-Brasil do contribuinte. URLs-base configuráveis.
"""
from __future__ import annotations

import base64
import gzip
from typing import Any

import httpx

from app.integrations.nfse.base import FiscalProvider, ProviderMessage, ProviderResult
from app.integrations.nfse.certificate import LoadedCertificate, mtls_files


def gzip_b64(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data)).decode("ascii")


def ungzip_b64(value: str) -> bytes:
    return gzip.decompress(base64.b64decode(value))


def _messages(items: Any) -> list[ProviderMessage]:
    out = []
    if isinstance(items, dict):
        items = [items]
    for it in items or []:
        if isinstance(it, dict):
            out.append(ProviderMessage(code=it.get("codigo") or it.get("Codigo"),
                                       message=it.get("descricao") or it.get("mensagem") or it.get("Descricao") or "Erro",
                                       detail=it.get("complemento") or it.get("Complemento")))
    return out


class NationalProvider(FiscalProvider):
    name = "nacional"

    def __init__(self, *, sefin_url: str, adn_url: str, certificate: LoadedCertificate, timeout: float = 60.0,
                 danfse_path: str = "/danfse/{chave}", transport: httpx.BaseTransport | None = None):
        self.sefin_url = sefin_url.rstrip("/")
        self.adn_url = adn_url.rstrip("/")
        self.certificate = certificate
        self.timeout = timeout
        self.danfse_path = danfse_path
        self.transport = transport

    def _call(self, method: str, url: str, json_body: dict | None = None, accept: str = "application/json") -> tuple[int | None, Any, bytes | None, str | None]:
        """Retorna (status, json, bytes, erro_de_comunicação)."""
        with mtls_files(self.certificate) as (cert_path, key_path):
            try:
                kwargs: dict[str, Any] = {"timeout": self.timeout, "headers": {"Accept": accept}}
                if self.transport is not None:
                    kwargs["transport"] = self.transport
                else:
                    kwargs["cert"] = (cert_path, key_path)
                with httpx.Client(**kwargs) as client:
                    resp = client.request(method, url, json=json_body)
            except httpx.TimeoutException:
                return None, None, None, "Tempo de resposta esgotado na comunicação com o serviço fiscal."
            except httpx.HTTPError as exc:
                return None, None, None, f"Falha de comunicação com o serviço fiscal ({type(exc).__name__})."
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            try:
                return resp.status_code, resp.json(), resp.content, None
            except ValueError:
                return resp.status_code, None, resp.content, None
        return resp.status_code, None, resp.content, None

    def emit(self, signed_dps: bytes) -> ProviderResult:
        status, data, _, comm = self._call("POST", f"{self.sefin_url}/nfse", {"dpsXmlGZipB64": gzip_b64(signed_dps)})
        if comm:
            return ProviderResult(ok=False, communication_failure=True,
                                  errors=[ProviderMessage(code="COMUNICACAO", message=comm)])
        data = data or {}
        summary = {k: data.get(k) for k in ("tipoAmbiente", "versaoAplicativo", "dataHoraProcessamento", "idDps", "idDPS", "chaveAcesso")}
        if status == 201 and data.get("chaveAcesso") and data.get("nfseXmlGZipB64"):
            return ProviderResult(ok=True, http_status=status, access_key=data["chaveAcesso"], dps_id=data.get("idDps"),
                                  nfse_xml=ungzip_b64(data["nfseXmlGZipB64"]), alerts=_messages(data.get("alertas")),
                                  raw_summary=summary)
        if status in (400, 401, 403, 404, 409, 422):
            errors = _messages(data.get("erros") or data.get("erro")) or [ProviderMessage(code=str(status), message="Rejeitado pelo serviço fiscal")]
            return ProviderResult(ok=False, http_status=status, errors=errors, raw_summary=summary)
        # 5xx ou resposta inesperada: situação desconhecida -> consultar antes de qualquer conclusão
        return ProviderResult(ok=False, http_status=status, communication_failure=True,
                              errors=_messages(data.get("erros") or data.get("erro")) or
                              [ProviderMessage(code=str(status), message="Resposta inesperada do serviço fiscal")],
                              raw_summary=summary)

    def get_nfse(self, access_key: str) -> ProviderResult:
        status, data, _, comm = self._call("GET", f"{self.sefin_url}/nfse/{access_key}")
        if comm:
            return ProviderResult(ok=False, communication_failure=True, errors=[ProviderMessage("COMUNICACAO", comm)])
        data = data or {}
        if status == 200 and data.get("nfseXmlGZipB64"):
            return ProviderResult(ok=True, http_status=status, access_key=data.get("chaveAcesso", access_key),
                                  nfse_xml=ungzip_b64(data["nfseXmlGZipB64"]))
        return ProviderResult(ok=False, http_status=status, errors=_messages(data.get("erro") or data.get("erros"))
                              or [ProviderMessage(str(status), "NFS-e não localizada")])

    def get_by_dps(self, dps_id: str) -> ProviderResult:
        status, data, _, comm = self._call("GET", f"{self.sefin_url}/dps/{dps_id}")
        if comm:
            return ProviderResult(ok=False, communication_failure=True, errors=[ProviderMessage("COMUNICACAO", comm)])
        data = data or {}
        if status == 200 and data.get("chaveAcesso"):
            return ProviderResult(ok=True, http_status=status, access_key=data["chaveAcesso"], dps_id=dps_id)
        return ProviderResult(ok=False, http_status=status, errors=_messages(data.get("erro") or data.get("erros"))
                              or [ProviderMessage(str(status), "Nenhuma NFS-e gerada para esta DPS")])

    def register_event(self, access_key: str, signed_event: bytes) -> ProviderResult:
        status, data, _, comm = self._call("POST", f"{self.sefin_url}/nfse/{access_key}/eventos",
                                           {"pedidoRegistroEventoXmlGZipB64": gzip_b64(signed_event)})
        if comm:
            return ProviderResult(ok=False, communication_failure=True, errors=[ProviderMessage("COMUNICACAO", comm)])
        data = data or {}
        if status == 201 and data.get("eventoXmlGZipB64"):
            return ProviderResult(ok=True, http_status=status, access_key=access_key,
                                  event_xml=ungzip_b64(data["eventoXmlGZipB64"]))
        return ProviderResult(ok=False, http_status=status, communication_failure=status is None or status >= 500,
                              errors=_messages(data.get("erro") or data.get("erros"))
                              or [ProviderMessage(str(status), "Evento rejeitado")])

    def list_events(self, access_key: str) -> ProviderResult:
        status, data, _, comm = self._call("GET", f"{self.sefin_url}/nfse/{access_key}/eventos")
        if comm:
            return ProviderResult(ok=False, communication_failure=True, errors=[ProviderMessage("COMUNICACAO", comm)])
        return ProviderResult(ok=status == 200, http_status=status, raw_summary={"eventos": data})

    def download_danfse(self, access_key: str) -> ProviderResult:
        url = self.adn_url + self.danfse_path.format(chave=access_key)
        status, _, content, comm = self._call("GET", url, accept="application/pdf")
        if comm:
            return ProviderResult(ok=False, communication_failure=True, errors=[ProviderMessage("COMUNICACAO", comm)])
        if status == 200 and content and content.startswith(b"%PDF"):
            return ProviderResult(ok=True, http_status=status, pdf=content)
        return ProviderResult(ok=False, http_status=status, errors=[ProviderMessage(str(status), "DANFSe indisponível")])
