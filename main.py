#!/usr/bin/env python3
"""IT8951 e-paper display CLI — main entry point.

Usage:
  sudo python3 main.py --info                 # show device info + VCOM
  sudo python3 main.py --clear                # clear screen to white
  sudo python3 main.py --text "Hello World"   # display text
  sudo python3 main.py --text "Hello" --font-size 96
  sudo python3 main.py --image photo.png      # display image (auto-scaled)
  sudo python3 main.py --gradient             # full-screen vertical gradient
  sudo python3 main.py --checker 50           # checkerboard pattern
  sudo python3 main.py --cross 9              # gradient cross (9px lines)
  sudo python3 main.py --quarter              # top-left quarter black
  sudo python3 main.py --server               # start HTTP API server
  sudo python3 main.py --server --port 8888   # server on custom port
"""
import argparse, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from it8951_driver import IT8951, GC16_MODE, INIT_MODE


def main():
    parser = argparse.ArgumentParser(
        description="IT8951 e-paper display driver for Orange Pi Zero 2W",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--info", action="store_true", help="show device info + VCOM")
    parser.add_argument("--clear", action="store_true", help="clear screen to white")
    parser.add_argument("--text", metavar="STR", help="display text (antialiased)")
    parser.add_argument("--font-size", type=int, default=48, help="font size in pixels (default: 48)")
    parser.add_argument("--font-path", default=None, help="path to .ttf font file")
    parser.add_argument("--image", metavar="PATH", help="display image file (auto-scaled)")
    parser.add_argument("--gradient", action="store_true", help="full-screen vertical gradient")
    parser.add_argument("--checker", type=int, nargs="?", const=50, metavar="PX", help="checkerboard pattern (cell size px)")
    parser.add_argument("--checker-fast", type=int, nargs="?", const=50, metavar="PX", help="checkerboard using A2 fast refresh (~0.3s)")
    parser.add_argument("--clear-checker", type=int, nargs="?", const=50, metavar="PX", help="INIT clear then instant A2 checkerboard")
    parser.add_argument("--clear-cross", type=int, nargs="?", const=9, metavar="PX", help="clear then cross in one process (fast)")
    parser.add_argument("--cross", type=int, nargs="?", const=9, metavar="PX", help="gradient diagonal cross (line width px)")
    parser.add_argument("--quarter", action="store_true", help="top-left quarter black")
    parser.add_argument("--server", action="store_true", help="start HTTP API server")
    parser.add_argument("--host", default="0.0.0.0", help="server bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8888, help="server port (default: 8888)")
    parser.add_argument("--invert", action="store_true", help="invert cross colors (bg black, cross white)")
    parser.add_argument("--vertical", action="store_true", help="cross gradient: bottom-to-top instead of corner-to-center")
    args = parser.parse_args()

    # If --server, start the API server
    if args.server:
        from server.server import main as server_main
        sys.argv = [sys.argv[0], "--host", args.host, "--port", str(args.port)]
        server_main()
        return

    # Otherwise, run direct display commands
    epd = IT8951()
    try:
        epd.init()

        if args.info or not any([args.clear, args.text, args.image, args.gradient,
                                  args.checker is not None, args.checker_fast is not None,
                                  args.clear_checker is not None, args.clear_cross is not None,
                                  args.cross is not None, args.quarter]):
            info = epd.get_info()
            vcom = epd.get_vcom()
            print("Panel:   %d x %d" % (info["panel_w"], info["panel_h"]))
            print("Memory:  0x%08X" % info["memory_addr"])
            print("FW:      %s" % info["fw_version"])
            print("LUT:     %s" % info["lut_version"])
            print("A2 mode: %d" % info["a2_mode"])
            print("VCOM:    %d (=-%.2fV)" % (vcom, vcom / 1000.0))
            if not args.info:
                print("No action specified. Use --help for options.")

        if args.clear:
            print("Clearing...")
            epd.clear()
            print("Done.")

        if args.text:
            print("Displaying text: %s" % args.text[:60])
            epd.display_text(args.text, font_size=args.font_size, font_path=args.font_path)
            print("Done.")

        if args.image:
            from PIL import Image
            print("Loading image: %s" % args.image)
            img = Image.open(args.image)
            print("Original size: %s" % str(img.size))
            epd.display_image(img, bg_color=0, brightness=1.4)  # black bg, boosted
            print("Displayed.")

        if args.gradient:
            print("Displaying vertical gradient (dithered)...")
            w, h = epd.panel_w, epd.panel_h
            import numpy as np
            # Smooth gradient: for each pixel, compute fractional gray level
            # then use random dithering to pick integer level.
            # This gives soft transitions with no hard stripe edges.
            gray4 = np.zeros((h, w), dtype=np.uint8)  # 0=white, 15=black

            for row in range(h):
                # Continuous gray value 0→15 top to bottom
                cont = row / max(h - 1, 1) * 15.0
                base = int(cont)        # integer part
                frac = cont - base       # fractional part (0..1)
                # Random dithering: pixel gets base+1 with probability=frac
                noise = np.random.random(w)
                vals = np.where(noise < frac, base + 1, base)
                gray4[row] = np.clip(vals, 0, 15).astype(np.uint8)

            # Pack 4bpp
            if w % 2 != 0:
                gray4 = np.hstack([gray4, np.zeros((h, 1), dtype=np.uint8)])
            high = gray4[:, 0::2] << 4
            low  = gray4[:, 1::2]
            packed = (high | low).astype(np.uint8)

            epd.display_4bpp(list(packed.tobytes()), 0, 0, w, h, GC16_MODE)
            print("Done.")

        if args.checker is not None:
            cell = args.checker
            print("Displaying checkerboard (%dpx cells)..." % cell)
            w, h = epd.panel_w, epd.panel_h
            img = bytearray(w * h)
            for row in range(h):
                cy = row // cell
                off = row * w
                for col in range(w):
                    cx = col // cell
                    img[off + col] = 0 if (cx + cy) % 2 == 0 else 255
            epd.display_8bpp(list(img), 0, 0, w, h, GC16_MODE)
            print("Done.")

        if args.checker_fast is not None:
            cell = args.checker_fast
            import time
            print("Displaying checkerboard (%dpx, 4bpp GC16)..." % cell)
            w, h = epd.panel_w, epd.panel_h
            # 4bpp: 0=white, 15=black. Half the data size of 8bpp.
            bpr = (w * 4 + 7) // 8
            img = bytearray(bpr * h)
            for row in range(h):
                cy = row // cell
                off = row * bpr
                for col_pair in range(w // 2):
                    cx0 = (col_pair * 2) // cell
                    cx1 = (col_pair * 2 + 1) // cell
                    v0 = 0x0F if (cx0 + cy) % 2 == 0 else 0x00  # black or white
                    v1 = 0x0F if (cx1 + cy) % 2 == 0 else 0x00
                    img[off + col_pair] = (v0 << 4) | v1
            t0 = time.time()
            epd.display_4bpp(list(img), 0, 0, w, h, GC16_MODE)
            t1 = time.time()
            print("Done. 4bpp GC16 refresh took %.2fs" % (t1 - t0))

        if args.clear_checker is not None:
            cell = args.clear_checker
            import time
            w, h = epd.panel_w, epd.panel_h
            bpr = (w * 4 + 7) // 8
            img = bytearray(bpr * h)
            for row in range(h):
                cy = row // cell
                off = row * bpr
                for col_pair in range(w // 2):
                    cx0 = (col_pair * 2) // cell
                    cx1 = (col_pair * 2 + 1) // cell
                    v0 = 0x0F if (cx0 + cy) % 2 == 0 else 0x00
                    v1 = 0x0F if (cx1 + cy) % 2 == 0 else 0x00
                    img[off + col_pair] = (v0 << 4) | v1
            print("Single GC16 refresh (no separate clear)...")
            t0 = time.time()
            epd.display_4bpp(list(img), 0, 0, w, h, GC16_MODE)
            t1 = time.time()
            print("Done. Total: %.2fs (single GC16, no INIT clear)" % (t1 - t0))

        if args.clear_cross is not None:
            import time
            lw = args.clear_cross
            print("Clear + cross in one process (%dpx)..." % lw)
            t0 = time.time()
            # GC16 does its own full refresh — skip separate INIT clear
            # The cross has white background so GC16 refresh clears ghosting
            _draw_cross(epd, lw, args.invert, args.vertical)
            t1 = time.time()
            print("Done. Total: %.2fs (single GC16, no separate clear)" % (t1 - t0))

        if args.cross is not None:
            lw = args.cross
            print("Displaying cross (%dpx, vertical=%s, invert=%s)..." % (lw, args.vertical, args.invert))
            _draw_cross(epd, lw, args.invert, args.vertical)
            print("Done.")

        if args.quarter:
            print("Displaying quarter black...")
            w, h = epd.panel_w, epd.panel_h
            img = bytearray([255] * (w * h))  # white
            hw, hh = w // 2, h // 2
            for row in range(hh):
                off = row * w
                for col in range(hw):
                    img[off + col] = 0  # black
            epd.display_8bpp(list(img), 0, 0, w, h, GC16_MODE)
            print("Done.")

    finally:
        epd.close()


def _draw_cross(epd, line_width, invert, vertical):
    """Draw gradient diagonal cross with random dithering (4bpp, 0=white, 15=black)."""
    import numpy as np
    w, h = epd.panel_w, epd.panel_h
    # 4bpp: 0=white, 15=black. bg=15 if invert (black bg) else 0 (white bg)
    gray = np.full((h, w), 15 if invert else 0, dtype=np.float64)
    cx, cy = w // 2, h // 2

    def draw_line(x0, y0, x1, y1, width):
        dx, dy = x1 - x0, y1 - y0
        length = (dx * dx + dy * dy) ** 0.5
        if length == 0:
            return
        ux, uy = dx / length, dy / length
        px_val, py_val = -uy, ux
        steps = int(length)
        for i in range(steps + 1):
            cx_pt = x0 + ux * i
            cy_pt = y0 + uy * i
            if vertical:
                t = cy_pt / max(h - 1, 1)
            else:
                t = i / max(steps, 1)
            # Line gray: invert → black(15) to white(0), else white(0) to black(15)
            line_gray = (15 - t * 15) if invert else (t * 15)
            half_w = width / 2
            for j in range(-int(half_w), int(half_w) + 1):
                px = int(round(cx_pt + px_val * j))
                py = int(round(cy_pt + py_val * j))
                if 0 <= px < w and 0 <= py < h:
                    gray[py, px] = line_gray

    draw_line(0, 0, cx, cy, line_width)
    draw_line(w - 1, 0, cx, cy, line_width)
    draw_line(0, h - 1, cx, cy, line_width)
    draw_line(w - 1, h - 1, cx, cy, line_width)

    # Random dithering: for each pixel, pick base+1 with probability=fraction
    noise = np.random.random((h, w))
    base = np.floor(gray).astype(np.int32)
    frac = gray - base
    dithered = np.where(noise < frac, base + 1, base)
    gray4 = np.clip(dithered, 0, 15).astype(np.uint8)

    # Pack 4bpp
    if w % 2 != 0:
        gray4 = np.hstack([gray4, np.zeros((h, 1), dtype=np.uint8)])
    high = gray4[:, 0::2] << 4
    low  = gray4[:, 1::2]
    packed = (high | low).astype(np.uint8)

    epd.display_4bpp(list(packed.tobytes()), 0, 0, w, h, GC16_MODE)


if __name__ == "__main__":
    main()