"""Generate packaging/flow.icns and flow.ico (a simple FLOW glyph) without any image library beyond the stdlib + numpy.

Draws a rounded lavender square with three white bars (the structure strip) into PNGs, then builds .icns via iconutil (mac)
and a .ico with a tiny hand-written container.
"""
from __future__ import annotations
import os
import struct
import subprocess
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def png(rgba: np.ndarray) -> bytes:
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def render(size: int) -> np.ndarray:
    """Flat, sharp mark: five black bars on a white rounded square. No gradient, no glow."""
    img = np.zeros((size, size, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    r = size * 0.225
    cx = cy = size / 2
    half = size / 2 - size * 0.05
    dx = np.maximum(np.abs(xx - cx) - (half - r), 0)
    dy = np.maximum(np.abs(yy - cy) - (half - r), 0)
    inside = (dx ** 2 + dy ** 2) <= r ** 2
    img[inside, :3] = 255
    img[inside, 3] = 255
    # five bars, bottom-aligned, heights like a structure strip
    heights = (0.20, 0.32, 0.44, 0.26, 0.52)
    w, gap = size * 0.085, size * 0.045
    total = 5 * w + 4 * gap
    x = cx - total / 2
    base = size * 0.76
    for h in heights:
        y0 = base - size * h
        m = (xx >= x) & (xx < x + w) & (yy >= y0) & (yy <= base) & inside
        img[m, :3] = 0x12
        img[m, 3] = 255
        x += w + gap
    return img


def main():
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    iconset = os.path.join(HERE, "flow.iconset")
    os.makedirs(iconset, exist_ok=True)
    pngs = {}
    for s in sizes:
        pngs[s] = png(render(s))
    for s in (16, 32, 128, 256, 512):
        open(os.path.join(iconset, f"icon_{s}x{s}.png"), "wb").write(pngs[s])
        open(os.path.join(iconset, f"icon_{s}x{s}@2x.png"), "wb").write(pngs[s * 2])
    if sys.platform == "darwin":
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(HERE, "flow.icns")], check=True)
    # .ico with 16/32/48/256 PNG entries
    entries = [(16, pngs[16]), (32, pngs[32]), (64, pngs[64]), (256, pngs[256])]
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    dirs, data = b"", b""
    for s, p in entries:
        dirs += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(p), offset + len(data))
        data += p
    open(os.path.join(HERE, "flow.ico"), "wb").write(header + dirs + data)
    open(os.path.join(HERE, "flow-512.png"), "wb").write(pngs[512])
    print("icons written to", HERE)


if __name__ == "__main__":
    main()
