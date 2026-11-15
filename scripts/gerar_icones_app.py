"""Gera os ícones PNG do app instalável (PWA) a partir da marca lótus (frontend/public/favicon.svg).

Rasterizador próprio, sem dependências (só a biblioteca padrão), para rodar em qualquer máquina.
Uso:  python scripts/gerar_icones_app.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "icons"
SS = 4  # supersampling por eixo (antisserrilhado)

TOP, MID, BOT = (0x1E, 0x3A, 0x8A), (0x25, 0x63, 0xEB), (0x38, 0xBD, 0xF8)


def cubic(p0, p1, p2, p3, n=48):
    pts = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        pts.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return pts


def path(start, segs):
    pts = [start]
    cur = start
    for c1, c2, end in segs:
        pts += cubic(cur, c1, c2, end)
        cur = end
    return pts


# mesmas formas do favicon.svg (viewBox 0 0 64 64)
PETALA_CENTRO = path((32, 6), [((40, 16), (42, 30), (32, 46)), ((22, 30), (24, 16), (32, 6))])
PETALA_ESQ = path((4, 26), [((18, 24), (28, 32), (32, 46)), ((18, 46), (8, 38), (4, 26))])
PETALA_DIR = path((60, 26), [((46, 24), (36, 32), (32, 46)), ((46, 46), (56, 38), (60, 26))])
CIRCULOS = [((10, 14), 3.0), ((55, 18), 2.4)]


def grad(t: float):
    t = min(max(t, 0.0), 1.0)
    if t <= 0.6:
        a, b, f = TOP, MID, t / 0.6
    else:
        a, b, f = MID, BOT, (t - 0.6) / 0.4
    return tuple(a[i] + (b[i] - a[i]) * f for i in range(3))


def render(size: int, conteudo: float, fundo=(255, 255, 255)) -> bytes:
    """conteudo = fração da largura ocupada pela marca (64 unidades)."""
    n = size * SS
    escala = n * conteudo / 64
    # centraliza a área desenhada (x 4..60, y 6..46 → centro 32,26)
    offx, offy = n / 2 - 32 * escala, n / 2 - 26 * escala
    # camada base: fundo
    img = [[list(fundo) for _ in range(n)] for _ in range(n)]

    def fill_poly(poly, alpha):
        pts = [(x * escala + offx, y * escala + offy) for x, y in poly]
        ys = [p[1] for p in pts]
        y0, y1 = max(int(min(ys)), 0), min(int(max(ys)) + 1, n)
        for sy in range(y0, y1):
            yc = sy + 0.5
            xs = []
            for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
                if (ay <= yc < by) or (by <= yc < ay):
                    xs.append(ax + (yc - ay) * (bx - ax) / (by - ay))
            xs.sort()
            # gradiente em objectBoundingBox (vertical, da própria forma)
            t = (yc - min(ys)) / (max(ys) - min(ys))
            cor = grad(t)
            row = img[sy]
            for xa, xb in zip(xs[0::2], xs[1::2]):
                for sx in range(max(int(xa + 0.5), 0), min(int(xb + 0.5), n)):
                    px = row[sx]
                    for k in range(3):
                        px[k] = px[k] * (1 - alpha) + cor[k] * alpha

    def fill_circle(c, r):
        cx, cy, rr = c[0] * escala + offx, c[1] * escala + offy, r * escala
        for sy in range(max(int(cy - rr), 0), min(int(cy + rr) + 2, n)):
            for sx in range(max(int(cx - rr), 0), min(int(cx + rr) + 2, n)):
                if (sx + 0.5 - cx) ** 2 + (sy + 0.5 - cy) ** 2 <= rr * rr:
                    img[sy][sx] = list(TOP)

    fill_poly(PETALA_CENTRO, 1.0)
    fill_poly(PETALA_ESQ, 0.92)
    fill_poly(PETALA_DIR, 0.92)
    for c, r in CIRCULOS:
        fill_circle(c, r)

    # reduz o supersampling
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            s = [0.0, 0.0, 0.0]
            for dy in range(SS):
                row = img[y * SS + dy]
                for dx in range(SS):
                    p = row[x * SS + dx]
                    s[0] += p[0]; s[1] += p[1]; s[2] += p[2]
            d = SS * SS
            raw += bytes(int(round(v / d)) for v in s)
    return png(size, size, bytes(raw))


def png(w: int, h: int, raw: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    alvos = {
        "apple-touch-icon.png": (180, 0.74),  # iPhone (tela de início); o iOS arredonda os cantos
        "icon-192.png": (192, 0.74),
        "icon-512.png": (512, 0.74),
        "icon-maskable-512.png": (512, 0.56),  # Android: margem de segurança para recortes
    }
    for nome, (tam, frac) in alvos.items():
        (OUT / nome).write_bytes(render(tam, frac))
        print("gerado", nome)


if __name__ == "__main__":
    main()
