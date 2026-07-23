#!/usr/bin/env python3
"""Speed test: try different SPI speeds and refresh strategies."""
import sys, time, os
sys.path.insert(0, "/opt/it8951-epaper")
import numpy as np

def test_speed(spi_speed, label):
    from it8951_driver import IT8951, GC16_MODE, INIT_MODE, IT8951_8BPP, IT8951_4BPP
    epd = IT8951(speed=spi_speed)
    epd.init()
    w, h = epd.panel_w, epd.panel_h

    # Build a 4bpp checkerboard
    bpr = (w * 4 + 7) // 8
    img = bytearray(bpr * h)
    cell = 50
    for row in range(h):
        cy = row // cell
        off = row * bpr
        for col_pair in range(w // 2):
            cx0 = (col_pair * 2) // cell
            cx1 = (col_pair * 2 + 1) // cell
            v0 = 0x0F if (cx0 + cy) % 2 == 0 else 0x00
            v1 = 0x0F if (cx1 + cy) % 2 == 0 else 0x00
            img[off + col_pair] = (v0 << 4) | v1

    # Test 1: A2 clear + GC16 render (current approach)
    t0 = time.time()
    epd._a2_fast_clear()
    t1 = time.time()

    # Load 4bpp data
    total = bpr * h
    inverted = bytearray(total)
    for i in range(total):
        b = img[i]
        hi = (b >> 4) & 0x0F
        lo = b & 0x0F
        inverted[i] = ((15 - hi) << 4) | (15 - lo)
    epd._set_target_mem_addr(epd.mem_addr)
    epd._load_img_area_start(IT8951_4BPP, 0, 0, w, h)
    epd._write_data_bytes(inverted)
    epd._load_img_end()
    t2 = time.time()
    epd._display_area(0, 0, w, h, GC16_MODE)
    epd._wait_display_ready()
    t3 = time.time()

    print("[%s] A2 clear: %.2fs | data load: %.2fs | GC16 refresh: %.2fs | total: %.2fs" % (
        label, t1-t0, t2-t1, t3-t2, t3-t0))

    # Test 2: Overlapped — load data during A2 clear
    # Build 1bpp clear buffers
    bpr1 = w // 8
    black = bytearray([0xFF] * (bpr1 * h))
    white = bytearray([0x00] * (bpr1 * h))
    if len(black) % 2: black.append(0)
    if len(white) % 2: white.append(0)

    val = epd.read_reg(0x1138 + 2)
    epd.write_reg(0x1138 + 2, val | (1 << 2))
    epd.write_reg(0x1250, (0x00 << 8) | 0xFF)

    epd._set_target_mem_addr(epd.mem_addr)
    # Flash black
    epd._load_img_area_start(IT8951_8BPP, 0, 0, w // 8, h)
    epd._write_data_bytes(black)
    epd._load_img_end()
    epd._display_area(0, 0, w, h, epd.a2_mode)

    # While A2 refresh runs, load the 4bpp image data
    epd._set_target_mem_addr(epd.mem_addr)
    epd._load_img_area_start(IT8951_4BPP, 0, 0, w, h)
    epd._write_data_bytes(inverted)
    epd._load_img_end()

    # Wait for A2 to finish
    epd._wait_display_ready()

    # Flash white
    epd._load_img_area_start(IT8951_8BPP, 0, 0, w // 8, h)
    epd._write_data_bytes(white)
    epd._load_img_end()
    epd._display_area(0, 0, w, h, epd.a2_mode)

    # While A2 refresh runs, reload 4bpp data (it may have been overwritten)
    epd._set_target_mem_addr(epd.mem_addr)
    epd._load_img_area_start(IT8951_4BPP, 0, 0, w, h)
    epd._write_data_bytes(inverted)
    epd._load_img_end()

    epd._wait_display_ready()

    # Disable 1bpp
    val = epd.read_reg(0x1138 + 2)
    epd.write_reg(0x1138 + 2, val & ~(1 << 2))

    # GC16 render (data already loaded)
    t4 = time.time()
    epd._display_area(0, 0, w, h, GC16_MODE)
    epd._wait_display_ready()
    t5 = time.time()

    print("[%s] overlapped: A2+load: %.2fs | A2+load: %.2fs | GC16: %.2fs | total: %.2fs" % (
        label, t5-t4, 0, t5-t4, t5-t4))

    epd.close()

# Test at different SPI speeds
for speed, label in [(12000000, "12MHz"), (24000000, "24MHz"), (48000000, "48MHz")]:
    try:
        test_speed(speed, label)
    except Exception as e:
        print("[%s] Error: %s" % (label, e))