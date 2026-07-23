#!/usr/bin/env python3
"""Simple timing test: measure each phase of clear+render."""
import sys, time
sys.path.insert(0, "/opt/it8951-epaper")
from it8951_driver import IT8951, GC16_MODE, INIT_MODE, IT8951_8BPP, IT8951_4BPP

epd = IT8951()
epd.init()
w, h = epd.panel_w, epd.panel_h

# Build 4bpp checkerboard
import numpy as np
bpr = (w * 4 + 7) // 8
cell = 50
gray4 = np.zeros((h, w), dtype=np.uint8)
for row in range(h):
    cy = row // cell
    for col in range(w):
        cx = col // cell
        gray4[row, col] = 0x0F if (cx + cy) % 2 == 0 else 0x00
if w % 2 != 0:
    gray4 = np.hstack([gray4, np.zeros((h, 1), dtype=np.uint8)])
packed = ((gray4[:, 0::2] << 4) | gray4[:, 1::2]).astype(np.uint8)
img_4bpp = list(packed.tobytes())

# Invert for hardware
total = len(img_4bpp)
inverted = bytearray(total)
for i in range(total):
    b = img_4bpp[i]
    hi = (b >> 4) & 0x0F
    lo = b & 0x0F
    inverted[i] = ((15 - hi) << 4) | (15 - lo)

# Build 1bpp clear buffers
bpr1 = w // 8
black = bytearray([0xFF] * (bpr1 * h))
white = bytearray([0x00] * (bpr1 * h))
if len(black) % 2: black.append(0)
if len(white) % 2: white.append(0)

print("=== Test 1: A2 clear (2 frames) + 4bpp load + GC16 (sequential) ===")
t0 = time.time()

# A2 clear
val = epd.read_reg(0x1138 + 2)
epd.write_reg(0x1138 + 2, val | (1 << 2))
epd.write_reg(0x1250, (0x00 << 8) | 0xFF)
epd._set_target_mem_addr(epd.mem_addr)
for frame in [black, white]:
    epd._load_img_area_start(IT8951_8BPP, 0, 0, w // 8, h)
    epd._write_data_bytes(frame)
    epd._load_img_end()
    epd._display_area(0, 0, w, h, epd.a2_mode)
    epd._wait_display_ready()
val = epd.read_reg(0x1138 + 2)
epd.write_reg(0x1138 + 2, val & ~(1 << 2))
t1 = time.time()

# Load 4bpp
epd._set_target_mem_addr(epd.mem_addr)
epd._load_img_area_start(IT8951_4BPP, 0, 0, w, h)
epd._write_data_bytes(inverted)
epd._load_img_end()
t2 = time.time()

# GC16 render
epd._display_area(0, 0, w, h, GC16_MODE)
epd._wait_display_ready()
t3 = time.time()

print("  A2 clear: %.2fs | 4bpp load: %.2fs | GC16: %.2fs | total: %.2fs" % (t1-t0, t2-t1, t3-t2, t3-t0))

print()
print("=== Test 2: Overlapped — load 4bpp during A2 white frame ===")
t0 = time.time()

# Enable 1bpp
val = epd.read_reg(0x1138 + 2)
epd.write_reg(0x1138 + 2, val | (1 << 2))
epd.write_reg(0x1250, (0x00 << 8) | 0xFF)

# A2 black frame (no wait after — load data while it refreshes)
epd._set_target_mem_addr(epd.mem_addr)
epd._load_img_area_start(IT8951_8BPP, 0, 0, w // 8, h)
epd._write_data_bytes(black)
epd._load_img_end()
epd._display_area(0, 0, w, h, epd.a2_mode)

# Load 4bpp data WHILE A2 black refreshes (SPI is free during LUT refresh)
epd._set_target_mem_addr(epd.mem_addr)
epd._load_img_area_start(IT8951_4BPP, 0, 0, w, h)
epd._write_data_bytes(inverted)
epd._load_img_end()
t1 = time.time()

# Now wait for A2 black to finish
epd._wait_display_ready()
t2 = time.time()

# A2 white frame (clear the black)
epd._load_img_area_start(IT8951_8BPP, 0, 0, w // 8, h)
epd._write_data_bytes(white)
epd._load_img_end()
epd._display_area(0, 0, w, h, epd.a2_mode)
epd._wait_display_ready()
t3 = time.time()

# Disable 1bpp
val = epd.read_reg(0x1138 + 2)
epd.write_reg(0x1138 + 2, val & ~(1 << 2))

# Reload 4bpp (was overwritten by A2 white frame)
epd._set_target_mem_addr(epd.mem_addr)
epd._load_img_area_start(IT8951_4BPP, 0, 0, w, h)
epd._write_data_bytes(inverted)
epd._load_img_end()
t4 = time.time()

# GC16 render
epd._display_area(0, 0, w, h, GC16_MODE)
epd._wait_display_ready()
t5 = time.time()

print("  A2 black+4bpp load: %.2fs | A2 black wait: %.2fs | A2 white: %.2fs | 4bpp reload: %.2fs | GC16: %.2fs | total: %.2fs" % (
    t1-t0, t2-t1, t3-t2, t4-t3, t5-t4, t5-t0))

print()
print("=== Test 3: Single A2 black + 4bpp load during + GC16 (no white frame) ===")
t0 = time.time()

val = epd.read_reg(0x1138 + 2)
epd.write_reg(0x1138 + 2, val | (1 << 2))
epd.write_reg(0x1250, (0x00 << 8) | 0xFF)

# A2 black — clear ghosting
epd._set_target_mem_addr(epd.mem_addr)
epd._load_img_area_start(IT8951_8BPP, 0, 0, w // 8, h)
epd._write_data_bytes(black)
epd._load_img_end()
epd._display_area(0, 0, w, h, epd.a2_mode)

# Load 4bpp during A2 refresh
epd._set_target_mem_addr(epd.mem_addr)
epd._load_img_area_start(IT8951_4BPP, 0, 0, w, h)
epd._write_data_bytes(inverted)
epd._load_img_end()
t1 = time.time()

epd._wait_display_ready()
t2 = time.time()

# Disable 1bpp
val = epd.read_reg(0x1138 + 2)
epd.write_reg(0x1138 + 2, val & ~(1 << 2))

# GC16 render
epd._display_area(0, 0, w, h, GC16_MODE)
epd._wait_display_ready()
t3 = time.time()

print("  A2 black+4bpp load: %.2fs | A2 wait: %.2fs | GC16: %.2fs | total: %.2fs" % (
    t1-t0, t2-t1, t3-t2, t3-t0))

epd.close()
print("\nDone.")