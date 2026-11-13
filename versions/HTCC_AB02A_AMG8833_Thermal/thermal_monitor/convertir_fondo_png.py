# -*- coding: utf-8 -*-
"""
convertir_fondo_png.py

Convierte fondo.jpg en fondo.png dejando el fondo con canal alpha
transparente (canal alfa) conservando el objeto central (la taza).

Metodo:
  1. Desenfoque gaussiano para reducir el ruido JPEG de la cuadricula.
  2. Flood-fill (BFS) desde los bordes con diferencia INCREMENTAL entre
     vecinos; captura el fondo exterior conectado y se detiene en el
     contorno del objeto.
  3. Los pixeles de fondo quedan transparentes; el resto, opaco.

Ajuste visual rapido:
    python convertir_fondo_png.py --blur 4 --tol 7
    (sube/baja --tol para dejar mas o menos fondo; suele ir bien ~6-8)
"""

import argparse
from collections import deque

from PIL import Image, ImageFilter

SRC = r"C:\Users\Cliente Preferido\Documents\Default Project\thermal_monitor\fondo.jpg"
DST = r"C:\Users\Cliente Preferido\Documents\Default Project\thermal_monitor\fondo.png"


def png_fondo(src, dst, blur_rad=4, tol=7):
    im = Image.open(src).convert("RGB")
    W, H = im.size

    # Reduce el ruido de la cuadricula para que el fondo sea continuo
    if blur_rad > 0:
        im_sm = im.filter(ImageFilter.GaussianBlur(blur_rad))
    else:
        im_sm = im

    px = im_sm.load()
    visited = [[False] * W for _ in range(H)]
    fondo = [[False] * W for _ in range(H)]
    q = deque()

    def seed(x, y):
        if not visited[y][x]:
            visited[y][x] = True
            q.append((x, y))

    for x in range(W):
        seed(x, 0)
        seed(x, H - 1)
    for y in range(H):
        seed(0, y)
        seed(W - 1, y)

    while q:
        x, y = q.popleft()
        fondo[y][x] = True
        r0, g0, b0 = px[x, y]
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < W and 0 <= ny < H and not visited[ny][nx]:
                r1, g1, b1 = px[nx, ny]
                if abs(r1 - r0) + abs(g1 - g0) + abs(b1 - b0) <= tol:
                    visited[ny][nx] = True
                    q.append((nx, ny))

    # Pieza para bordes suaves: antialias basico (margen 1px semi) omitido por simplicidad.
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out_px = out.load()
    # usar colores del ORIGINAL (no del suavizado) para la parte opaca
    orig = im.load()
    n_fondo = 0
    for y in range(H):
        for x in range(W):
            if not fondo[y][x]:
                r, g, b = orig[x, y]
                out_px[x, y] = (r, g, b, 255)
            else:
                n_fondo += 1

    out.save(dst)
    print(f"Guardado: {dst}")
    print(f"  tamano: {W}x{H}, fondo transparente: {n_fondo / (H * W) * 100:.1f}%")
    print(f"  usa el original con los pixeles NO-fondo opacos.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--blur", type=int, default=4)
    ap.add_argument("--tol", type=int, default=7)
    args = ap.parse_args()
    png_fondo(SRC, DST, args.blur, args.tol)
