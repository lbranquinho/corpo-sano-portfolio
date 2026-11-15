"""Cliente da WhatsApp Business Cloud API (Meta Graph API) — integração oficial.

Documentação: https://developers.facebook.com/docs/whatsapp/cloud-api
- Envio:      POST https://graph.facebook.com/{versão}/{phone-number-id}/messages
- Templates:  GET  https://graph.facebook.com/{versão}/{waba-id}/message_templates
- Número:     GET  https://graph.facebook.com/{versão}/{phone-number-id}
Webhooks: verificação GET (hub.mode/hub.verify_token/hub.challenge) e eventos POST
assinados com HMAC-SHA256 do App Secret no cabeçalho X-Hub-Signature-256.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Any

import httpx

GRAPH_BASE = "https://graph.facebook.com"
# códigos da Cloud API que indicam limite/indisponibilidade temporária
RETRYABLE_CODES = {"1", "2", "4", "17", "80007", "130429", "131000", "131016", "131048", "131056", "133004"}


class WhatsAppError(Exception):
    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False, http_status: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable
        self.http_status = http_status


class WhatsAppClient:
    def __init__(self, *, access_token: str, phone_number_id: str, waba_id: str | None, api_version: str,
                 timeout: float = 20.0, transport: httpx.BaseTransport | None = None):
        if not access_token or not phone_number_id:
            raise WhatsAppError("Integração WhatsApp não configurada (token ou Phone Number ID ausentes).")
        self.phone_number_id = phone_number_id
        self.waba_id = waba_id
        self.base = f"{GRAPH_BASE}/{api_version}"
        self._client = httpx.Client(
            timeout=timeout, headers={"Authorization": f"Bearer {access_token}"}, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WhatsAppClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> dict:
        try:
            resp = self._client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise WhatsAppError("Tempo de resposta da API do WhatsApp esgotado.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise WhatsAppError(f"Falha de comunicação com a API do WhatsApp: {type(exc).__name__}", retryable=True) from exc
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            code = str(err.get("code")) if err.get("code") is not None else None
            msg = err.get("message") or f"HTTP {resp.status_code}"
            details = (err.get("error_data") or {}).get("details")
            if details:
                msg = f"{msg} — {details}"
            retryable = resp.status_code == 429 or resp.status_code >= 500 or (code in RETRYABLE_CODES)
            raise WhatsAppError(msg, code=code, retryable=retryable, http_status=resp.status_code)
        return data

    def send_template(self, to: str, name: str, language: str, body_params: list[str]) -> str:
        template: dict[str, Any] = {"name": name, "language": {"code": language}}
        if body_params:
            template["components"] = [
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in body_params]}
            ]
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "template",
                   "template": template}
        data = self._request("POST", f"{self.base}/{self.phone_number_id}/messages", json=payload)
        return self._message_id(data)

    def send_text(self, to: str, body: str) -> str:
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "text",
                   "text": {"preview_url": False, "body": body}}
        data = self._request("POST", f"{self.base}/{self.phone_number_id}/messages", json=payload)
        return self._message_id(data)

    @staticmethod
    def _message_id(data: dict) -> str:
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError, TypeError) as exc:
            raise WhatsAppError("Resposta da API sem identificador da mensagem.") from exc

    def list_templates(self) -> list[dict]:
        if not self.waba_id:
            raise WhatsAppError("Informe o WhatsApp Business Account ID para sincronizar templates.")
        url = f"{self.base}/{self.waba_id}/message_templates"
        params: dict[str, Any] | None = {"fields": "name,status,language,category,components,id", "limit": 100}
        out: list[dict] = []
        while url:
            data = self._request("GET", url, params=params)
            out.extend(data.get("data", []))
            url = (data.get("paging") or {}).get("next")
            params = None  # a URL "next" já contém os parâmetros
        return out

    def phone_info(self) -> dict:
        return self._request(
            "GET", f"{self.base}/{self.phone_number_id}",
            params={"fields": "display_phone_number,verified_name,quality_rating"},
        )


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])
