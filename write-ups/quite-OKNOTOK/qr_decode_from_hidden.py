#!/usr/bin/env python3
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

def _luminance(rgb: np.ndarray) -> np.ndarray:
    rgb = rgb.astype(np.float32)
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]

def binarize_qr(rgb_crop: np.ndarray) -> np.ndarray:
    lum = _luminance(rgb_crop)
    uniq = np.unique(np.round(lum, 3))
    if len(uniq) <= 32 and float(uniq[-1]) > 150.0:
        thr = float(uniq[-2])
        dark = lum < thr
        return dark
    vals = np.clip(lum.astype(np.int32), 0, 255)
    hist = np.bincount(vals.ravel(), minlength=256).astype(np.float64)
    total = vals.size
    sum_total = np.dot(np.arange(256), hist)
    sum_b = 0.0
    w_b = 0.0
    max_var = -1.0
    thr = 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > max_var:
            max_var = var_between
            thr = t
    return lum <= thr

ECL_MAP = {
    0b00: "M",
    0b01: "L",
    0b10: "H",
    0b11: "Q",
}

def _format_codeword(ecl_bits: int, mask: int) -> int:
    data = ((ecl_bits & 0x3) << 3) | (mask & 0x7) 
    g = 0x537
    v = data << 10
    for i in range(14, 9, -1):
        if (v >> i) & 1:
            v ^= g << (i - 10)
    remainder = v & 0x3FF
    code = (data << 10) | remainder
    code ^= 0x5412
    return code

FORMAT_TABLE = [(_format_codeword(ecl, m), ecl, m) for ecl in range(4) for m in range(8)]

def read_format_bits_top_left(mod: np.ndarray) -> int:
    bits = []
    for c in range(0, 6):
        bits.append(int(mod[8, c]))
    bits.append(int(mod[8, 7]))
    bits.append(int(mod[8, 8]))
    bits.append(int(mod[7, 8]))
    for r in range(5, -1, -1):
        bits.append(int(mod[r, 8]))
    v = 0
    for b in bits:
        v = (v << 1) | b
    return v

def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()

@dataclass
class QRFormat:
    ecl_bits: int
    mask: int

def decode_format(mod: np.ndarray) -> QRFormat:
    v = read_format_bits_top_left(mod)
    best = None
    for code, ecl, mask in FORMAT_TABLE:
        d = hamming(v, code)
        if best is None or d < best[0]:
            best = (d, ecl, mask)
    assert best is not None
    dist, ecl_bits, mask = best
    return QRFormat(ecl_bits=ecl_bits, mask=mask)

def build_function_mask(version: int, N: int) -> np.ndarray:
    func = np.zeros((N, N), dtype=bool)
    finders = [(0, 0), (0, N - 7), (N - 7, 0)]
    for r0, c0 in finders:
        for r in range(r0 - 1, r0 + 8):
            for c in range(c0 - 1, c0 + 8):
                if 0 <= r < N and 0 <= c < N:
                    func[r, c] = True
    func[6, :] = True
    func[:, 6] = True
    if version == 2:
        cy = cx = 18
        for r in range(cy - 2, cy + 3):
            for c in range(cx - 2, cx + 3):
                func[r, c] = True
    func[8, 0:9] = True
    func[0:9, 8] = True
    func[8, N - 8 : N] = True
    func[N - 8 : N, 8] = True
    func[4 * version + 9, 8] = True
    return func

def mask_condition(mask: int, r: int, c: int) -> bool:
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return ((r // 2) + (c // 3)) % 2 == 0
    if mask == 5:
        return ((r * c) % 2 + (r * c) % 3) == 0
    if mask == 6:
        return (((r * c) % 2 + (r * c) % 3) % 2) == 0
    if mask == 7:
        return (((r + c) % 2 + (r * c) % 3) % 2) == 0
    raise ValueError("invalid mask")

def extract_codewords(mod_dark: np.ndarray, fmt: QRFormat) -> list[int]:
    N = mod_dark.shape[0]
    version = (N - 17) // 4
    func = build_function_mask(version, N)
    m = mod_dark.copy().astype(np.uint8)
    for r in range(N):
        for c in range(N):
            if func[r, c]:
                continue
            if mask_condition(fmt.mask, r, c):
                m[r, c] ^= 1
    bits: list[int] = []
    col = N - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(N - 1, -1, -1) if upward else range(N)
        for r in rows:
            for c in (col, col - 1):
                if func[r, c]:
                    continue
                bits.append(int(m[r, c]))
        upward = not upward
        col -= 2
    codewords: list[int] = []
    for i in range(0, len(bits) // 8 * 8, 8):
        b = 0
        for j in range(8):
            b = (b << 1) | bits[i + j]
        codewords.append(b)
    return codewords

def decode_qr_payload(mod_dark: np.ndarray) -> str:
    fmt = decode_format(mod_dark)
    codewords = extract_codewords(mod_dark, fmt)
    data_cw = codewords[:28]  
    bits = []
    for b in data_cw:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    def read(n: int) -> int:
        nonlocal bits
        v = 0
        for _ in range(n):
            v = (v << 1) | bits.pop(0)
        return v
    length = read(8)  
    out = bytearray()
    for _ in range(length):
        out.append(read(8))
    return out.decode("utf-8", errors="replace")

def main() -> int:
    img_path = Path(sys.argv[1])
    rgb = np.array(Image.open(img_path).convert("RGB"))
    h, w, _ = rgb.shape
    crop = rgb[:, w - h : w, :]
    mod_dark = binarize_qr(crop)
    payload = decode_qr_payload(mod_dark)
    print(payload)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
