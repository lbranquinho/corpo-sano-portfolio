"""Assinatura XMLDSig enveloped no padrão dos documentos fiscais eletrônicos brasileiros.

- Elemento <Signature> SEM prefixo (xmlns="http://www.w3.org/2000/09/xmldsig#"), último filho da raiz;
- Reference URI="#Id" do elemento assinado (infDPS / infPedReg);
- Transforms: enveloped-signature + C14N 1.0 inclusivo (REC-xml-c14n-20010315);
- SignatureMethod RSA-SHA256, DigestMethod SHA-256;
- KeyInfo apenas com X509Data/X509Certificate.

Implementação direta com lxml + cryptography: a canonicalização do SignedInfo é feita já dentro do
documento (contexto de namespaces correto), condição necessária para o C14N inclusivo sem prefixo.
"""
from __future__ import annotations

import base64
import copy
import hashlib

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from lxml import etree

from app.integrations.nfse.certificate import LoadedCertificate

DS = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
ALGORITHMS = {"rsa-sha256"}


def _c14n(el: etree._Element) -> bytes:
    """C14N 1.0 inclusivo do subelemento.

    O C14N do lxml aplicado diretamente a um subelemento emite ``xmlns=""`` indevido nos filhos quando o
    namespace padrão é redefinido por um ancestral (caso da <Signature> sem prefixo dentro da DPS).
    A canonicalização é feita sobre uma cópia isolada, que carrega os namespaces em escopo — resultado
    conferido contra a libxmlsec1 (implementação de referência) nos testes.
    """
    isolated = copy.deepcopy(el)
    missing = {k: v for k, v in el.nsmap.items() if isolated.nsmap.get(k) != v}
    if missing:
        raise ValueError(f"Namespaces em escopo não suportados na canonicalização: {missing}")
    return etree.tostring(isolated, method="c14n", exclusive=False, with_comments=False)


def _ds(parent: etree._Element, tag: str, text: str | None = None, **attrs: str) -> etree._Element:
    el = etree.SubElement(parent, f"{{{DS}}}{tag}", **attrs)
    if text is not None:
        el.text = text
    return el


def _find_by_id(root: etree._Element, element_id: str) -> etree._Element:
    found = root.xpath("//*[@Id=$id]", id=element_id)
    if len(found) != 1:
        raise ValueError(f"Elemento com Id '{element_id}' não encontrado (ou duplicado).")
    return found[0]


def sign_xml(xml: bytes, element_id: str, cert: LoadedCertificate, algorithm: str = "rsa-sha256") -> bytes:
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Algoritmo de assinatura não suportado: {algorithm}")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    root = etree.fromstring(xml, parser)
    target = _find_by_id(root, element_id)
    digest = base64.b64encode(hashlib.sha256(_c14n(target)).digest()).decode()

    signature = etree.SubElement(root, f"{{{DS}}}Signature", nsmap={None: DS})
    signed_info = _ds(signature, "SignedInfo")
    _ds(signed_info, "CanonicalizationMethod", Algorithm=C14N)
    _ds(signed_info, "SignatureMethod", Algorithm=RSA_SHA256)
    ref = _ds(signed_info, "Reference", URI=f"#{element_id}")
    transforms = _ds(ref, "Transforms")
    _ds(transforms, "Transform", Algorithm=ENVELOPED)
    _ds(transforms, "Transform", Algorithm=C14N)
    _ds(ref, "DigestMethod", Algorithm=SHA256)
    _ds(ref, "DigestValue", digest)

    key = serialization.load_pem_private_key(cert.key_pem, password=None)
    sig = key.sign(_c14n(signed_info), padding.PKCS1v15(), hashes.SHA256())
    _ds(signature, "SignatureValue", base64.b64encode(sig).decode())
    key_info = _ds(signature, "KeyInfo")
    x509_data = _ds(key_info, "X509Data")
    der = cert.certificate.public_bytes(serialization.Encoding.DER)
    _ds(x509_data, "X509Certificate", base64.b64encode(der).decode())
    return etree.tostring(root, xml_declaration=False, encoding="UTF-8")


def verify_xml(xml: bytes, cert_pem: bytes | None = None) -> bool:
    """Verificação independente (digest + assinatura). Usa o certificado do KeyInfo se cert_pem não for informado."""
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        root = etree.fromstring(xml, parser)
        signature = root.find(f"{{{DS}}}Signature")
        signed_info = signature.find(f"{{{DS}}}SignedInfo")
        ref = signed_info.find(f"{{{DS}}}Reference")
        target = _find_by_id(root, ref.get("URI").lstrip("#"))
        # transformação enveloped: assinatura não pode estar dentro do elemento referenciado
        if signature in target.iter():
            return False
        if base64.b64encode(hashlib.sha256(_c14n(target)).digest()).decode() != ref.findtext(f"{{{DS}}}DigestValue"):
            return False
        if cert_pem:
            certificate = x509.load_pem_x509_certificate(cert_pem)
        else:
            der = base64.b64decode(signature.findtext(f".//{{{DS}}}X509Certificate"))
            certificate = x509.load_der_x509_certificate(der)
        certificate.public_key().verify(base64.b64decode(signature.findtext(f"{{{DS}}}SignatureValue")),
                                        _c14n(signed_info), padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, AttributeError, ValueError, TypeError):
        return False
