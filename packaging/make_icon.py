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
    img = np.zeros((size, size, 4), dtype=np.uint8)
    yy, xx = np.mgrid[0:size, 0:size]
    r = size * 0.22
    cx = cy = size / 2
    half = size / 2 - size * 0.04
    dx = np.maximum(np.abs(xx - cx) - (half - r), 0)
    dy = np.maximum(np.abs(yy - cy) - (half - r), 0)
    inside = (dx ** 2 + dy ** 2) <= r ** 2
    # vertical gradient lavender
    t = (yy / size)[..., None]
    top, bot = np.array([0x73, 0x72, 0xE8]), np.array([0x5C, 0x5B, 0xE0])
    col = (top * (1 - t) + bot * t).astype(np.uint8)
    img[inside, :3] = col[inside]
    img[inside, 3] = 255
    # three bars, heights like a structure strip
    bars = [(0.24, 0.36), (0.42, 0.58), (0.60, 0.80)]
    base = size * 0.78
    for (x0, x1), hgt in zip(bars, (0.28, 0.42, 0.56)):
        y0 = base - size * hgt
        m = (xx >= size * x0) & (xx <= size * x1) & (yy >= y0) & (yy <= base)
        img[m, :3] = 255
        img[m, 3] = 255
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
