"""Geração do XML da DPS e do Pedido de Registro de Evento (NFS-e Nacional).

Leiaute de referência: Anexo I (DPS/NFS-e) e Anexo II (eventos) do Sistema Nacional NFS-e,
disponíveis em https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica.
Os esquemas XSD oficiais devem ser colocados em app/integrations/nfse/xsd/ (ver docs/CONFIGURACAO_FISCAL.md);
quando presentes, o XML é validado antes do envio (obrigatório em produção).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from lxml import etree

NS = "http://www.sped.fazenda.gov.br/nfse"
XSD_DIR = Path(__file__).parent / "xsd"
APP_VERSION = "CorpoSano-1.0"


class DpsError(Exception):
    pass


@dataclass
class Party:
    document: str  # CPF (11) ou CNPJ (14)
    name: str | None = None
    municipal_registration: str | None = None
    phone: str | None = None
    email: str | None = None
    ibge_code: str | None = None
    zip_code: str | None = None
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    district: str | None = None


@dataclass
class DpsData:
    environment: int  # 1 = produção, 2 = homologação (produção restrita)
    issued_at: datetime
    series: str
    number: int
    competence: date
    emitter_ibge: str
    provider: Party
    op_simples_nacional: int
    reg_ap_trib_sn: int | None
    reg_esp_trib: int
    taker: Party | None
    service_location_ibge: str
    national_code: str
    municipal_code: str | None
    description: str
    nbs_code: str | None
    service_amount: Decimal
    unconditional_discount: Decimal = Decimal("0")
    conditional_discount: Decimal = Decimal("0")
    deductions: Decimal = Decimal("0")
    iss_withheld: bool = False
    iss_rate: Decimal | None = None
    include_iss_rate: bool = False
    federal_retentions: dict = field(default_factory=dict)  # irrf, csll, cp
    total_tax_sn_percent: Decimal | None = None
    substitution_key: str | None = None
    substitution_code: str | None = None
    substitution_reason: str | None = None
    layout_version: str = "1.01"


def _money(v: Decimal) -> str:
    return str(Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _pct(v: Decimal) -> str:
    return str(Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _sub(parent: etree._Element, tag: str, text: str | None = None) -> etree._Element:
    el = etree.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        el.text = str(text)
    return el


def dps_id(emitter_ibge: str, document: str, series: str, number: int) -> str:
    """Id da DPS: 'DPS' + cMun(7) + tipo inscrição(1) + inscrição federal(14) + série(5) + número(15)."""
    tp = "2" if len(document) == 14 else "1"
    ident = "DPS" + emitter_ibge + tp + document.zfill(14) + str(series).zfill(5) + str(number).zfill(15)
    if len(ident) != 45:
        raise DpsError("Identificador da DPS com tamanho inválido; confira IBGE, CNPJ e série.")
    return ident


def _doc(parent: etree._Element, document: str) -> None:
    _sub(parent, "CNPJ" if len(document) == 14 else "CPF", document)


def build_dps(d: DpsData) -> tuple[str, bytes]:
    if not d.description or len(d.description) > 2000:
        raise DpsError("Descrição do serviço obrigatória (até 2000 caracteres).")
    if len(d.national_code) != 6 or not d.national_code.isdigit():
        raise DpsError("Código de tributação nacional deve ter 6 dígitos.")
    ident = dps_id(d.emitter_ibge, d.provider.document, d.series, d.number)
    root = etree.Element(f"{{{NS}}}DPS", nsmap={None: NS}, versao=d.layout_version)
    inf = _sub(root, "infDPS")
    inf.set("Id", ident)
    _sub(inf, "tpAmb", str(d.environment))
    _sub(inf, "dhEmi", d.issued_at.replace(microsecond=0).isoformat())
    _sub(inf, "verAplic", APP_VERSION)
    _sub(inf, "serie", str(int(d.series)))
    _sub(inf, "nDPS", str(d.number))
    _sub(inf, "dCompet", d.competence.isoformat())
    _sub(inf, "tpEmit", "1")  # emitente = prestador
    _sub(inf, "cLocEmi", d.emitter_ibge)
    if d.substitution_key:
        subst = _sub(inf, "subst")
        _sub(subst, "chSubstda", d.substitution_key)
        _sub(subst, "cMotivo", d.substitution_code or "99")
        if d.substitution_reason:
            _sub(subst, "xMotivo", d.substitution_reason[:255])
    prest = _sub(inf, "prest")
    _doc(prest, d.provider.document)
    if d.provider.municipal_registration:
        _sub(prest, "IM", d.provider.municipal_registration)
    if d.provider.phone:
        _sub(prest, "fone", d.provider.phone[-11:])
    if d.provider.email:
        _sub(prest, "email", d.provider.email)
    reg = _sub(prest, "regTrib")
    _sub(reg, "opSimpNac", str(d.op_simples_nacional))
    if d.op_simples_nacional == 3 and d.reg_ap_trib_sn:
        _sub(reg, "regApTribSN", str(d.reg_ap_trib_sn))
    _sub(reg, "regEspTrib", str(d.reg_esp_trib))
    if d.taker and d.taker.document:
        toma = _sub(inf, "toma")
        _doc(toma, d.taker.document)
        if d.taker.municipal_registration:
            _sub(toma, "IM", d.taker.municipal_registration)
        _sub(toma, "xNome", (d.taker.name or "")[:300])
        if d.taker.ibge_code and d.taker.zip_code and d.taker.street and d.taker.district:
            end = _sub(toma, "end")
            nac = _sub(end, "endNac")
            _sub(nac, "cMun", d.taker.ibge_code)
            _sub(nac, "CEP", d.taker.zip_code)
            _sub(end, "xLgr", d.taker.street[:255])
            _sub(end, "nro", (d.taker.number or "S/N")[:60])
            if d.taker.complement:
                _sub(end, "xCpl", d.taker.complement[:156])
            _sub(end, "xBairro", d.taker.district[:60])
        if d.taker.phone:
            _sub(toma, "fone", d.taker.phone[-11:])
        if d.taker.email:
            _sub(toma, "email", d.taker.email)
    serv = _sub(inf, "serv")
    loc = _sub(serv, "locPrest")
    _sub(loc, "cLocPrestacao", d.service_location_ibge)
    cserv = _sub(serv, "cServ")
    _sub(cserv, "cTribNac", d.national_code)
    if d.municipal_code:
        _sub(cserv, "cTribMun", d.municipal_code)
    _sub(cserv, "xDescServ", d.description)
    if d.nbs_code:
        _sub(cserv, "cNBS", d.nbs_code)
    val = _sub(inf, "valores")
    vsp = _sub(val, "vServPrest")
    _sub(vsp, "vServ", _money(d.service_amount))
    if d.unconditional_discount > 0 or d.conditional_discount > 0:
        desc = _sub(val, "vDescCondIncond")
        if d.unconditional_discount > 0:
            _sub(desc, "vDescIncond", _money(d.unconditional_discount))
        if d.conditional_discount > 0:
            _sub(desc, "vDescCond", _money(d.conditional_discount))
    if d.deductions > 0:
        ded = _sub(val, "vDedRed")
        _sub(ded, "vDR", _money(d.deductions))
    trib = _sub(val, "trib")
    tmun = _sub(trib, "tribMun")
    _sub(tmun, "tribISSQN", "1")  # operação tributável
    _sub(tmun, "tpRetISSQN", "2" if d.iss_withheld else "1")
    if d.include_iss_rate and d.iss_rate is not None:
        _sub(tmun, "pAliq", _pct(d.iss_rate))
    fed = {k: v for k, v in (d.federal_retentions or {}).items() if v and Decimal(str(v)) > 0}
    if fed:
        tfed = _sub(trib, "tribFed")
        if fed.get("cp"):
            _sub(tfed, "vRetCP", _money(Decimal(str(fed["cp"]))))
        if fed.get("irrf"):
            _sub(tfed, "vRetIRRF", _money(Decimal(str(fed["irrf"]))))
        if fed.get("csll"):
            _sub(tfed, "vRetCSLL", _money(Decimal(str(fed["csll"]))))
    tot = _sub(trib, "totTrib")
    if d.total_tax_sn_percent is not None and d.op_simples_nacional == 3:
        _sub(tot, "pTotTribSN", _pct(d.total_tax_sn_percent))
    else:
        _sub(tot, "indTotTrib", "0")  # não informar valor estimado dos tributos (Decreto 8.264/2014)
    xml = etree.tostring(root, xml_declaration=False, encoding="UTF-8")
    return ident, xml


def build_cancel_event(*, environment: int, author_document: str, access_key: str, reason_code: str,
                       reason: str, issued_at: datetime, sequence: int = 1, layout_version: str = "1.00") -> tuple[str, bytes]:
    """Pedido de Registro de Evento e101101 — Cancelamento de NFS-e."""
    if len(access_key) != 50:
        raise DpsError("Chave de acesso deve ter 50 dígitos.")
    if not 15 <= len(reason) <= 255:
        raise DpsError("A justificativa deve ter entre 15 e 255 caracteres.")
    ident = "PRE" + access_key + "101101" + str(sequence).zfill(3)
    root = etree.Element(f"{{{NS}}}pedRegEvento", nsmap={None: NS}, versao=layout_version)
    inf = _sub(root, "infPedReg")
    inf.set("Id", ident)
    _sub(inf, "tpAmb", str(environment))
    _sub(inf, "verAplic", APP_VERSION)
    _sub(inf, "dhEvento", issued_at.replace(microsecond=0).isoformat())
    _sub(inf, "CNPJAutor" if len(author_document) == 14 else "CPFAutor", author_document)
    _sub(inf, "chNFSe", access_key)
    _sub(inf, "nPedRegEvento", str(sequence))
    ev = _sub(inf, "e101101")
    _sub(ev, "xDesc", "Cancelamento de NFS-e")
    _sub(ev, "cMotivo", reason_code)
    _sub(ev, "xMotivo", reason)
    return ident, etree.tostring(root, xml_declaration=False, encoding="UTF-8")


def schema_path(kind: str, version: str) -> Path | None:
    """Procura o XSD oficial (ex.: DPS_v1.01.xsd, pedRegEvento_v1.00.xsd)."""
    for candidate in (XSD_DIR / f"{kind}_v{version}.xsd", XSD_DIR / f"{kind}_v{version.replace('.', '_')}.xsd"):
        if candidate.exists():
            return candidate
    return None


def validate_xsd(xml: bytes, kind: str, version: str) -> list[str] | None:
    """Retorna lista de erros; None se o esquema oficial não estiver instalado."""
    path = schema_path(kind, version)
    if path is None:
        return None
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    schema = etree.XMLSchema(etree.parse(str(path), parser))
    doc = etree.fromstring(xml, parser)
    if schema.validate(doc):
        return []
    return [f"linha {e.line}: {e.message}" for e in schema.error_log][:20]


def parse_nfse(xml: bytes) -> dict:
    """Extrai dados da NFS-e autorizada (namespace-agnóstico)."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(xml, parser)

    def first(name: str) -> str | None:
        found = root.xpath(f"//*[local-name()='{name}']")
        return found[0].text if found else None

    inf = root.xpath("//*[local-name()='infNFSe']")
    ident = inf[0].get("Id") if inf else None
    return {
        "number": first("nNFSe"),
        "access_key": ident[3:] if ident and ident.startswith("NFS") else None,
        "processed_at": first("dhProc"),
        "status_code": first("cStat"),
        "dfe_number": first("nDFSe"),
    }
