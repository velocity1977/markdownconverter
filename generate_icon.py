"""
One-time icon generator for ConvertDown.

Run this once from your venv:  python generate_icon.py
It writes icon.ico to this folder (multi-size: 16/32/48/256px).

Uses only the Python standard library (struct + zlib) -- no PIL/Pillow
dependency added just for a one-off asset. Safe to delete this file after
running it; icon.ico is the only thing that matters afterward.

Design: a rounded blue square (matching the app's existing #0E639C button
color), a white document with a folded top-right corner, and a small blue
downward chevron suggesting "converting down to markdown". Feel free to
replace icon.ico with your own artwork later -- this is just a clean
placeholder so the app isn't shipping a blank taskbar icon.
"""
import struct
import zlib

BLUE = (14, 99, 156)
WHITE = (255, 255, 255)
LIGHT = (230, 236, 241)


def rounded_rect_mask(x, y, w, h, radius, px, py):
    if px < x or px >= x + w or py < y or py >= y + h:
        return False
    cx = min(max(px, x + radius), x + w - radius)
    cy = min(max(py, y + radius), y + h - radius)
    if (px < x + radius or px >= x + w - radius) and (py < y + radius or py >= y + h - radius):
        return (px - cx) ** 2 + (py - cy) ** 2 <= radius ** 2
    return True


def draw_canvas(size):
    canvas = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]
    pad = max(1, size // 16)
    radius = max(2, size // 5)

    for y in range(size):
        for x in range(size):
            if rounded_rect_mask(pad, pad, size - 2 * pad, size - 2 * pad, radius, x, y):
                canvas[y][x] = (*BLUE, 255)

    doc_pad_x = size * 0.28
    doc_pad_top = size * 0.18
    doc_pad_bottom = size * 0.22
    doc_x0, doc_x1 = doc_pad_x, size - doc_pad_x * 0.62
    doc_y0, doc_y1 = doc_pad_top, size - doc_pad_bottom
    fold = (doc_x1 - doc_x0) * 0.32

    for y in range(size):
        for x in range(size):
            if doc_x0 <= x < doc_x1 and doc_y0 <= y < doc_y1:
                if (x - (doc_x1 - fold)) > 0 and (y - doc_y0) < fold and \
                   (x - (doc_x1 - fold)) > (fold - (y - doc_y0)):
                    continue
                canvas[y][x] = (*WHITE, 255)

    for y in range(size):
        for x in range(size):
            if (doc_x1 - fold) <= x < doc_x1 and doc_y0 <= y < doc_y0 + fold:
                if (x - (doc_x1 - fold)) <= (fold - (y - doc_y0)):
                    canvas[y][x] = (*LIGHT, 255)

    chevron_cx = (doc_x0 + doc_x1) / 2
    chevron_top = doc_y0 + (doc_y1 - doc_y0) * 0.45
    chevron_h = (doc_y1 - doc_y0) * 0.30
    chevron_w = (doc_x1 - doc_x0) * 0.34
    thickness = max(1.2, size * 0.045)
    for y in range(size):
        for x in range(size):
            t = (y - chevron_top) / chevron_h if chevron_h else 0
            if 0 <= t <= 1:
                half_w = chevron_w / 2
                left_line_x = chevron_cx - half_w + half_w * t
                right_line_x = chevron_cx + half_w - half_w * t
                if abs(x - left_line_x) <= thickness or abs(x - right_line_x) <= thickness:
                    if doc_x0 < x < doc_x1 and doc_y0 < y < doc_y1:
                        canvas[y][x] = (*BLUE, 255)
    return canvas


def png_bytes(canvas, size):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    raw = bytearray()
    for row in canvas:
        raw.append(0)
        for (r, g, b, a) in row:
            raw += bytes((r, g, b, a))

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    return sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')


def build_ico(sizes, out_path):
    images = [(s, png_bytes(draw_canvas(s), s)) for s in sizes]
    num = len(images)
    header = struct.pack("<HHH", 0, 1, num)
    entries = b""
    data_blob = b""
    offset = 6 + 16 * num
    for s, png in images:
        w = s if s < 256 else 0
        h = s if s < 256 else 0
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset)
        data_blob += png
        offset += len(png)

    with open(out_path, "wb") as f:
        f.write(header + entries + data_blob)


if __name__ == "__main__":
    build_ico([16, 32, 48, 256], "icon.ico")
    print("Wrote icon.ico")
