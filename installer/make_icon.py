"""Gera installer/corposano.ico (lótus em degradê azul) a partir das mesmas curvas do favicon.svg.
Requer Pillow (somente para desenvolvimento):  pip install pillow ; python installer/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
K = S / 64  # o desenho original usa viewBox 64x64


def bezier(p0, p1, p2, p3, n=60):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0]
        y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1]
        pts.append((x * K, y * K))
    return pts


PETALS = [  # (curvas, opacidade)
    ([((32, 6), (40, 16), (42, 30), (32, 46)), ((32, 46), (22, 30), (24, 16), (32, 6))], 255),
    ([((4, 26), (18, 24), (28, 32), (32, 46)), ((32, 46), (18, 46), (8, 38), (4, 26))], 235),
    ([((60, 26), (46, 24), (36, 32), (32, 46)), ((32, 46), (46, 46), (56, 38), (60, 26))], 235),
]


def gradient() -> Image.Image:
    stops = [(0.0, (0x1E, 0x3A, 0x8A)), (0.6, (0x25, 0x63, 0xEB)), (1.0, (0x38, 0xBD, 0xF8))]
    img = Image.new("RGBA", (S, S))
    px = img.load()
    for y in range(S):
        t = y / (S - 1)
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0]:
                (a, ca), (b, cb) = stops[i], stops[i + 1]
                f = (t - a) / (b - a)
                c = tuple(round(ca[j] + (cb[j] - ca[j]) * f) for j in range(3))
                break
        for x in range(S):
            px[x, y] = (*c, 255)
    return img


def main() -> None:
    mask = Image.new("L", (S, S), 0)
    draw = ImageDraw.Draw(mask)
    for curves, alpha in PETALS:
        pts = []
        for c in curves:
            pts += bezier(*c)
        draw.polygon(pts, fill=alpha)
    art = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    art.paste(gradient(), (0, 0), mask)
    dots = ImageDraw.Draw(art)
    for cx, cy, r in ((10, 14, 3), (55, 18, 2.4)):
        dots.ellipse(((cx - r) * K, (cy - r) * K, (cx + r) * K, (cy + r) * K), fill=(0x1E, 0x3A, 0x8A, 255))
    # recorte centralizado (o desenho ocupa y 6..46)
    art = art.crop((0, int(0 * K), S, int(56 * K))).resize((S, int(56 * K)))
    square = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    square.paste(art, (0, (S - art.height) // 2))
    out = Path(__file__).with_name("corposano.ico")
    square.resize((256, 256), Image.LANCZOS).save(out, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    square.resize((256, 256), Image.LANCZOS).save(Path(__file__).with_name("corposano-256.png"))
    print("Ícone gerado:", out)


if __name__ == "__main__":
    main()
