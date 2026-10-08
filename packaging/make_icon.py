"""Generate packaging/alma.icns, alma.ico and alma-512.png: the Alma mark, drawn with numpy only.

The mark is a warm, slightly concave disc with one pip at two o'clock on a near-black squircle: the knob at
the centre of the app, and a small world. Geometry lives in a 1000-unit icon space (same numbers as
flow/ui/brand.html); the squircle fills 84% of the canvas like Apple's own icons, with transparent margin.
Everything is rendered 4x and box-filtered down, so edges are clean at 16 px.
"""
from __future__ import annotations
import os
import struct
import subprocess
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SS = 4           # supersampling
ICON = 0.84      # squircle span of the canvas
N = 4.6          # superellipse exponent


def png(rgba: np.ndarray) -> bytes:
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def hexc(h: str) -> np.ndarray:
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64)


def ramp(t: np.ndarray, stops: list[tuple[float, str]]) -> np.ndarray:
    """Piecewise-linear colour ramp over t in [0,1]; returns (..., 3) floats."""
    out = np.zeros(t.shape + (3,), dtype=np.float64)
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        m = (t >= p0) & (t <= p1)
        f = ((t[m] - p0) / max(p1 - p0, 1e-9))[:, None]
        out[m] = hexc(c0) * (1 - f) + hexc(c1) * f
    out[t > stops[-1][0]] = hexc(stops[-1][1])
    return out


def render(size: int) -> np.ndarray:
    S = size * SS
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float64)
    # canvas pixel -> icon space (1000 units, squircle spans ICON of the canvas)
    u = (xx + 0.5) / S * 1000
    v = (yy + 0.5) / S * 1000
    x = (u - 500) / ICON + 500
    y = (v - 500) / ICON + 500
    img = np.zeros((S, S, 4), dtype=np.float64)

    # squircle body with a faint radial lift at the top
    r = 500.0
    body = (np.abs(x - 500) / r) ** N + (np.abs(y - 500) / r) ** N <= 1.0
    d_bg = np.sqrt(((x - 500) / 800) ** 2 + ((y - 300) / 800) ** 2)
    img[..., :3] = ramp(np.clip(d_bg, 0, 1), [(0.0, "#141416"), (1.0, "#0B0B0D")])
    img[..., 3] = body

    # disc: concave warm cap
    d_disc = np.sqrt((x - 500) ** 2 + (y - 500) ** 2)
    disc = d_disc <= 300
    t = np.sqrt(((x - 500) / 600) ** 2 + ((y - 420) / 600) ** 2)
    cap = ramp(np.clip(t, 0, 1), [(0.0, "#E9E5DC"), (0.72, "#F4F1EA"), (1.0, "#FBFAF7")])
    img[disc, :3] = cap[disc]
    # hairline rim, 35% white
    rim = (d_disc >= 299) & (d_disc <= 301)
    img[rim, :3] = img[rim, :3] * 0.65 + 255 * 0.35

    # pip: a rounded line from radius 266 to 174 on the 12 o'clock axis, rotated 32° clockwise
    a = np.deg2rad(32)
    px = (x - 500) * np.cos(a) + (y - 500) * np.sin(a)
    py = -(x - 500) * np.sin(a) + (y - 500) * np.cos(a)
    seg_y0, seg_y1, half_w = -266.0, -174.0, 11.0
    cy = np.clip(py, seg_y0, seg_y1)
    d_pip = np.sqrt(px ** 2 + (py - cy) ** 2)
    pip = d_pip <= half_w
    img[pip, :3] = hexc("#0B0B0D")

    # box-filter down
    img = img.reshape(size, SS, size, SS, 4).mean(axis=(1, 3))
    out = np.zeros((size, size, 4), dtype=np.uint8)
    out[..., :3] = np.clip(img[..., :3] + 0.5, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(img[..., 3] * 255 + 0.5, 0, 255).astype(np.uint8)
    return out


def main():
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    iconset = os.path.join(HERE, "alma.iconset")
    os.makedirs(iconset, exist_ok=True)
    pngs = {s: png(render(s)) for s in sizes}
    for s in (16, 32, 128, 256, 512):
        open(os.path.join(iconset, f"icon_{s}x{s}.png"), "wb").write(pngs[s])
        open(os.path.join(iconset, f"icon_{s}x{s}@2x.png"), "wb").write(pngs[s * 2])
    if sys.platform == "darwin":
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(HERE, "alma.icns")], check=True)
    entries = [(16, pngs[16]), (32, pngs[32]), (64, pngs[64]), (256, pngs[256])]
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    dirs, data = b"", b""
    for s, p in entries:
        dirs += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(p), offset + len(data))
        data += p
    open(os.path.join(HERE, "alma.ico"), "wb").write(header + dirs + data)
    open(os.path.join(HERE, "alma-512.png"), "wb").write(pngs[512])
    open(os.path.join(HERE, "alma-1024.png"), "wb").write(pngs[1024])
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
