"""Gera o pacote ZIP com todo o código-fonte do Corpo Sano, SEM segredos, dependências instaladas ou dados.

Uso:  python scripts/empacotar_codigo.py [arquivo_saida.zip]
"""
from __future__ import annotations

import fnmatch
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"

EXCLUDE_DIRS = {
    ".git", ".claude", ".venv", "node_modules", "dist", "data", "__pycache__", ".pytest_cache",
    "certbot", "entrega", ".vite", "build-installer", "implantacao-privada",
}
EXCLUDE_FILES = [
    ".env", "*.pyc", "*.dump", "*.dump.enc", "*.pfx", "*.p12", "*.log", ".coverage", "Thumbs.db", ".DS_Store",
]
# .env.example, .env.homologacao.example e .env.producao.example SÃO incluídos (modelos sem segredos)
ALLOW_FILES = {".env.example", ".env.homologacao.example", ".env.producao.example"}


def excluded(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
        return True
    if path.name in ALLOW_FILES:
        return False
    if path.name.startswith(".env"):
        return True
    if rel.as_posix().startswith("backend/app/integrations/nfse/xsd/") and path.suffix == ".xsd":
        return True
    return any(fnmatch.fnmatch(path.name, pat) for pat in EXCLUDE_FILES)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "entrega" / f"CorpoSano-codigo-fonte-{VERSION}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(ROOT.rglob("*")):
            if path.is_dir() or excluded(path) or path.resolve() == out.resolve():
                continue
            z.write(path, Path("CorpoSano") / path.relative_to(ROOT))
            count += 1
    print(f"{count} arquivos -> {out} ({out.stat().st_size / 1024 / 1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
