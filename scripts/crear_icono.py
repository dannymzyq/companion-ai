"""Dibuja el icono de la app (21 nov 2026): la esfera con ojos (el personaje avatar3) sobre un cuadrado redondeado
oscuro, para que se vea en barras claras y oscuras. Crea:
  desktop/icono.ico  (16-256, cada tamaño dibujado aparte: en 16-24 px sin brillo ni estrella, ojos más grandes)
  desktop/icono.png  (1024 px: Electron en el Mac y el .icns de crear_app_mac.sh)
  web/icono.png y docs/icono.png (192 px: icono de la pestaña y de la web)
Uso: .venv\\Scripts\\python.exe scripts\\crear_icono.py
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SS = 4  # sobremuestreo
# Estilo elegido (21 nov 2026: el actual sin estrella, esfera y ojos algo más grandes). Las otras claves sirven para probar variantes.
STYLE = {"star": False, "orb": 1.14, "eyes": 1.12, "rim": False, "blush": False, "smile": False, "bg": "dark"}
BGS = {"dark": ((44, 30, 82, 255), (14, 12, 26, 255)), "violet": ((96, 62, 190, 255), (30, 18, 70, 255)),
       "night": ((24, 26, 60, 255), (8, 8, 20, 255))}


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def gradient(size, c1, c2, angle_xy=(1, 1)):
    """Degradado lineal de c1 (arriba-izquierda) a c2 (abajo-derecha)."""
    g = Image.new("RGBA", (size, size))
    px = g.load()
    dx, dy = angle_xy
    n = (dx + dy) * (size - 1)
    for y in range(size):
        for x in range(size):
            px[x, y] = lerp(c1, c2, (x * dx + y * dy) / n)
    return g


def draw(size: int) -> Image.Image:
    S = size * SS
    small = size <= 24
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Fondo: cuadrado redondeado oscuro con un leve degradado violeta
    pad = round(S * (0.02 if small else 0.04))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, S - pad, S - pad), radius=round(S * 0.23), fill=255)
    bg = gradient(S // 8 or 1, *BGS[STYLE['bg']]).resize((S, S), Image.BILINEAR)
    img.paste(bg, (0, 0), mask)

    # Halo detrás de la esfera
    if not small:
        halo = Image.new("L", (S, S), 0)
        r = S * 0.36
        c = S * 0.5
        ImageDraw.Draw(halo).ellipse((c - r, c - r + S * 0.02, c + r, c + r + S * 0.02), fill=150)
        halo = halo.filter(ImageFilter.GaussianBlur(S * 0.07))
        halo = ImageChops.multiply(halo, mask)
        glow = Image.new("RGBA", (S, S), (167, 139, 250, 255))
        img.paste(glow, (0, 0), halo)

    # Esfera
    r = S * (0.37 if small else 0.32 * STYLE['orb'])
    cx, cy = S * 0.5, S * (0.5 if small or not STYLE['star'] else 0.53)
    orb_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(orb_mask).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    orb = gradient(S // 8 or 1, (205, 186, 255, 255), (98, 48, 196, 255)).resize((S, S), Image.BILINEAR)
    if not small:  # brillo arriba a la izquierda
        hl = Image.new("L", (S, S), 0)
        hr = r * 0.42
        hx, hy = cx - r * 0.38, cy - r * 0.42
        ImageDraw.Draw(hl).ellipse((hx - hr, hy - hr * 0.8, hx + hr, hy + hr * 0.8), fill=200)
        hl = hl.filter(ImageFilter.GaussianBlur(r * 0.2))
        orb.paste(Image.new("RGBA", (S, S), (255, 255, 255, 255)), (0, 0), hl)
    img.paste(orb, (0, 0), orb_mask)
    if STYLE["rim"] and not small:  # luz rebotada en el borde de abajo: más volumen
        inner = Image.new("L", (S, S), 0)
        ImageDraw.Draw(inner).ellipse((cx - r * 1.02, cy - r * 1.12, cx + r * 0.94, cy + r * 0.86), fill=255)
        band = ImageChops.subtract(orb_mask, inner).filter(ImageFilter.GaussianBlur(r * 0.05))
        img.paste(Image.new("RGBA", (S, S), (240, 170, 255, 255)), (0, 0),
                  ImageChops.multiply(band, orb_mask).point(lambda v: v * 3 // 4))

    # Ojos
    d = ImageDraw.Draw(img)
    k = 1 if small else STYLE['eyes']
    ew, eh = r * (0.2 if small else 0.17) * k, r * (0.34 if small else 0.31) * k
    gap = r * (0.36 if small else 0.33)
    ey = cy + r * 0.04
    for sx in (-1, 1):
        ex = cx + sx * gap
        d.ellipse((ex - ew / 2, ey - eh / 2, ex + ew / 2, ey + eh / 2), fill=(26, 16, 58, 255))
        if size >= 48:  # chispa en el ojo
            gr = ew * 0.22
            d.ellipse((ex - ew * 0.12 - gr, ey - eh * 0.2 - gr, ex - ew * 0.12 + gr, ey - eh * 0.2 + gr),
                      fill=(255, 255, 255, 230))

    if STYLE["blush"] and size >= 32:
        for sx in (-1, 1):
            bl = Image.new("L", (S, S), 0)
            bx, by = cx + sx * r * 0.56, cy + r * 0.3
            ImageDraw.Draw(bl).ellipse((bx - r * 0.14, by - r * 0.08, bx + r * 0.14, by + r * 0.08), fill=150)
            img.paste(Image.new("RGBA", (S, S), (255, 120, 180, 255)), (0, 0), bl.filter(ImageFilter.GaussianBlur(r * 0.05)))
    if STYLE["smile"] and size >= 32:
        d.arc((cx - r * 0.1, cy + r * 0.17, cx + r * 0.1, cy + r * 0.31), 20, 160, fill=(26, 16, 58, 255),
              width=max(2, round(r * 0.04)))

    # Estrella (la del pelo del personaje) arriba a la derecha
    if STYLE["star"] and size >= 32:
        sx, sy, R = S * 0.77, S * 0.24, S * 0.095
        pts = []
        for i in range(8):
            ang = i * 3.14159265 / 4 - 3.14159265 / 2
            rr = R if i % 2 == 0 else R * 0.3
            import math
            pts.append((sx + rr * math.cos(ang), sy + rr * math.sin(ang)))
        d.polygon(pts, fill=(255, 232, 140, 255))

    return img.resize((size, size), Image.LANCZOS)


def main():
    sizes = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    frames = {s: draw(s) for s in sizes}
    big = frames[256]
    big.save(ROOT / "desktop" / "icono.ico", sizes=[(s, s) for s in sizes],
             append_images=[frames[s] for s in sizes if s != 256])
    draw(1024).save(ROOT / "desktop" / "icono.png")
    for d in ("web", "docs"):
        draw(192).save(ROOT / d / "icono.png")
    print("Iconos creados:", ", ".join(str(s) for s in sizes), "+ 1024 + 192")


if __name__ == "__main__":
    main()
