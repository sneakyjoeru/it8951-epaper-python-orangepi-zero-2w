#!/usr/bin/env python3
"""IT8951 e-paper display driver for Orange Pi Zero 2W (Python).

Based on the Waveshare IT8951-ePaper C code (GPIOD mode).
Uses raw SPI ioctl for atomic multi-transfers with manual CS control.

Hardware:
  Orange Pi Zero 2W (H616), Waveshare 7.8" E-Ink HAT (1872x1404, IT8951)
  Boot overlay: spi1-cs1-spidev (frees GPIO 229 for manual CS)
  SPI:   /dev/spidev1.1 (kernel CS1, unused — we drive CS manually)
  RST:   GPIO 226 (PH2)
  CS:    GPIO 229 (PH5, physical SPI1 CS0 — manually driven)
  BUSY:  GPIO 228 (PH4)

This driver applies a global color inversion (4bpp nibble inversion)
to compensate for the hardware displaying colors inverted.
In code: 0=white, 15=black — displays correctly on screen.
"""
import spidev, gpiod, time, ctypes, fcntl, struct

# ===========================================================================
# Constants — from IT8951.h (Waveshare)
# ===========================================================================

# GPIO pins (Orange Pi Zero 2W, H616, port PH)
RST_PIN  = 226  # PH2
CS_PIN   = 229  # PH5 (physical SPI1 CS0 — manually driven)
BUSY_PIN = 228  # PH4

# IT8951 I80 commands
IT8951_TCON_SYS_RUN      = 0x0001
IT8951_TCON_STANDBY      = 0x0002
IT8951_TCON_SLEEP        = 0x0003
IT8951_TCON_REG_RD       = 0x0010
IT8951_TCON_REG_WR       = 0x0011
IT8951_TCON_LD_IMG       = 0x0020
IT8951_TCON_LD_IMG_AREA  = 0x0021
IT8951_TCON_LD_IMG_END   = 0x0022

USDEF_I80_CMD_DPY_AREA       = 0x0034
USDEF_I80_CMD_GET_DEV_INFO   = 0x0302
USDEF_I80_CMD_DPY_BUF_AREA   = 0x0037
USDEF_I80_CMD_VCOM           = 0x0039

# Refresh modes
INIT_MODE = 0   # clear / init (full flash)
GC16_MODE = 2   # 16-level grayscale, best quality
# A2_MODE set dynamically from LUT version (6 for M841_TFA2812 = 7.8")

# Pixel formats (bits per pixel)
IT8951_2BPP = 0
IT8951_3BPP = 1
IT8951_4BPP = 2
IT8951_8BPP = 3

# Endian
IT8951_LDIMG_L_ENDIAN = 0
IT8951_LDIMG_B_ENDIAN = 1

# Rotate
IT8951_ROTATE_0 = 0

# Registers
DISPLAY_REG_BASE = 0x1000
UP1SR     = DISPLAY_REG_BASE + 0x138
LUTAFSR   = DISPLAY_REG_BASE + 0x224
BGVR      = DISPLAY_REG_BASE + 0x250
MCSR_BASE = 0x0200
LISAR     = MCSR_BASE + 0x0008

# ===========================================================================
# SPI ioctl structures
# ===========================================================================

SPI_IOC_MAGIC = ord("k")

class SpiIocTransfer(ctypes.Structure):
    _fields_ = [
        ("tx_buf",        ctypes.c_uint64),
        ("rx_buf",        ctypes.c_uint64),
        ("len",           ctypes.c_uint32),
        ("speed_hz",      ctypes.c_uint32),
        ("delay_usecs",   ctypes.c_uint16),
        ("bits_per_word", ctypes.c_uint8),
        ("cs_change",     ctypes.c_uint8),
        ("tx_nbits",      ctypes.c_uint8),
        ("rx_nbits",      ctypes.c_uint8),
        ("pad",           ctypes.c_uint16),
    ]

def _spi_ioc_msg(n):
    return (1 << 30) | (SPI_IOC_MAGIC << 8) | (ctypes.sizeof(SpiIocTransfer) * n << 16)


class IT8951:
    """IT8951 e-paper display driver.

    All public display methods use the convention 0=white, 15=black.
    A global color inversion is applied in display_4bpp() to compensate
    for the hardware displaying colors inverted.
    """

    def __init__(self, spi_bus=1, spi_cs=1, speed=12000000):
        self.speed = speed
        self.panel_w = 0
        self.panel_h = 0
        self.mem_addr = 0
        self.lut_version = ""
        self.fw_version = ""
        self.a2_mode = 6

        # GPIO setup
        self.chip = gpiod.Chip("/dev/gpiochip0")
        self.rst  = self.chip.get_line(RST_PIN)
        self.cs   = self.chip.get_line(CS_PIN)
        self.busy = self.chip.get_line(BUSY_PIN)
        self.rst.request(consumer="epd", type=gpiod.LINE_REQ_DIR_OUT)
        self.cs.request(consumer="epd", type=gpiod.LINE_REQ_DIR_OUT)
        self.busy.request(consumer="epd", type=gpiod.LINE_REQ_DIR_IN)
        self.cs.set_value(1)  # CS idle = HIGH

        # SPI setup
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_cs)
        self.spi.max_speed_hz = speed
        self.spi.mode = 0
        self.spi.lsbfirst = False
        self.spi_fd = self.spi.fileno()

    # ---- Low-level SPI ----

    def _multi_xfer(self, transfers):
        """Send multiple SPI transfers in one ioctl call (CS held low manually)."""
        n = len(transfers)
        xfers = (SpiIocTransfer * n)()
        tx_bufs = []
        rx_bufs = []
        for i, (tx, _) in enumerate(transfers):
            tx_a = (ctypes.c_uint8 * len(tx))(*tx)
            rx_a = (ctypes.c_uint8 * len(tx))()
            tx_bufs.append(tx_a)
            rx_bufs.append(rx_a)
            xfers[i].tx_buf = ctypes.cast(tx_a, ctypes.c_void_p).value
            xfers[i].rx_buf = ctypes.cast(rx_a, ctypes.c_void_p).value
            xfers[i].len = len(tx)
            xfers[i].speed_hz = self.speed
            xfers[i].bits_per_word = 8
            xfers[i].cs_change = 0
        fcntl.ioctl(self.spi_fd, _spi_ioc_msg(n), xfers, True)
        return [list(rx) for rx in rx_bufs]

    def _wait_busy(self, timeout_ms=5000):
        for _ in range(timeout_ms):
            if self.busy.get_value() == 1:
                return True
            time.sleep(0.001)
        return False

    def _cs_low(self):
        self.cs.set_value(0)

    def _cs_high(self):
        self.cs.set_value(1)

    # ---- IT8951 protocol ----

    def _write_cmd(self, cmd):
        self._wait_busy()
        self._cs_low()
        self._multi_xfer([
            ([0x60, 0x00], True),
            ([(cmd >> 8) & 0xFF, cmd & 0xFF], False),
        ])
        self._cs_high()

    def _write_data(self, data):
        self._wait_busy()
        self._cs_low()
        self._multi_xfer([
            ([0x00, 0x00], True),
            ([(data >> 8) & 0xFF, data & 0xFF], False),
        ])
        self._cs_high()

    def _write_data_bytes(self, data_bytes):
        """Write raw data bytes after preamble 0x0000, CS held low."""
        self._wait_busy()
        self._cs_low()
        self._multi_xfer([([0x00, 0x00], True)])
        chunk_size = 4096
        for i in range(0, len(data_bytes), chunk_size):
            chunk = data_bytes[i:i + chunk_size]
            self._multi_xfer([(chunk, False)])
        self._cs_high()

    def _read_data(self):
        self._wait_busy()
        self._cs_low()
        result = self._multi_xfer([
            ([0x10, 0x00], True),
            ([0x00, 0x00], True),
            ([0x00, 0x00], False),
        ])
        self._cs_high()
        rx = result[2]
        return (rx[0] << 8) | rx[1]

    def _read_multi(self, count):
        self._wait_busy()
        self._cs_low()
        xfers = [([0x10, 0x00], True), ([0x00, 0x00], True)]
        for i in range(count):
            xfers.append(([0x00, 0x00], i < count - 1))
        result = self._multi_xfer(xfers)
        self._cs_high()
        words = []
        for i in range(count):
            rx = result[2 + i]
            words.append((rx[0] << 8) | rx[1])
        return words

    # ---- Register access ----

    def write_reg(self, addr, val):
        self._write_cmd(IT8951_TCON_REG_WR)
        self._write_data(addr)
        self._write_data(val)

    def read_reg(self, addr):
        self._write_cmd(IT8951_TCON_REG_RD)
        self._write_data(addr)
        return self._read_data()

    # ---- Init ----

    def init(self):
        """Reset, get device info."""
        self.rst.set_value(1); time.sleep(0.2)
        self.rst.set_value(0); time.sleep(0.01)
        self.rst.set_value(1); time.sleep(0.2)

        if not self._wait_busy():
            raise RuntimeError("IT8951 busy not released after reset")

        self._write_cmd(IT8951_TCON_SYS_RUN)
        time.sleep(0.1)

        self._write_cmd(USDEF_I80_CMD_GET_DEV_INFO)
        time.sleep(0.05)
        self._wait_busy()
        words = self._read_multi(20)

        self.panel_w = words[0]
        self.panel_h = words[1]
        self.mem_addr = words[2] | (words[3] << 16)

        fw_bytes = []
        for j in range(8):
            fw_bytes.append((words[4 + j] >> 8) & 0xFF)
            fw_bytes.append(words[4 + j] & 0xFF)
        lut_bytes = []
        for j in range(8):
            lut_bytes.append((words[12 + j] >> 8) & 0xFF)
            lut_bytes.append(words[12 + j] & 0xFF)
        self.fw_version  = "".join(chr(b) if 0x20 <= b < 127 else "" for b in fw_bytes).strip()
        self.lut_version = "".join(chr(b) if 0x20 <= b < 127 else "" for b in lut_bytes).strip()

        if "M641" in self.lut_version:
            self.a2_mode = 4
        else:
            self.a2_mode = 6

    def get_info(self):
        """Return dict with device info."""
        return {
            "panel_w": self.panel_w,
            "panel_h": self.panel_h,
            "memory_addr": self.mem_addr,
            "fw_version": self.fw_version,
            "lut_version": self.lut_version,
            "a2_mode": self.a2_mode,
        }

    # ---- VCOM ----

    def get_vcom(self):
        self._write_cmd(USDEF_I80_CMD_VCOM)
        self._write_data(0x0000)
        return self._read_data()

    def set_vcom(self, vcom):
        self._write_cmd(USDEF_I80_CMD_VCOM)
        self._write_data(0x0001)
        self._write_data(vcom)

    # ---- Display operations ----

    def _set_target_mem_addr(self, addr):
        self.write_reg(LISAR + 2, (addr >> 16) & 0xFFFF)
        self.write_reg(LISAR, addr & 0xFFFF)

    def _wait_display_ready(self):
        for _ in range(30000):
            if self.read_reg(LUTAFSR) == 0:
                return True
            time.sleep(0.001)
        return False

    def _load_img_area_start(self, pixel_format, x, y, w, h):
        args = (IT8951_LDIMG_L_ENDIAN << 8) | (pixel_format << 4) | IT8951_ROTATE_0
        self._write_cmd(IT8951_TCON_LD_IMG_AREA)
        self._write_data(args)
        self._write_data(x)
        self._write_data(y)
        self._write_data(w)
        self._write_data(h)

    def _load_img_end(self):
        self._write_cmd(IT8951_TCON_LD_IMG_END)

    def _display_area(self, x, y, w, h, mode):
        self._write_cmd(USDEF_I80_CMD_DPY_AREA)
        self._write_data(x)
        self._write_data(y)
        self._write_data(w)
        self._write_data(h)
        self._write_data(mode)

    def clear(self, mode=INIT_MODE):
        """Clear the entire screen to white.
        Hardware inverts: send 0 (PIL black) → shows white on screen.
        """
        w, h = self.panel_w, self.panel_h
        self._set_target_mem_addr(self.mem_addr)
        self._load_img_area_start(IT8951_8BPP, 0, 0, w, h)
        data = bytearray([0] * (w * h))
        if w * h % 2 != 0:
            data.append(0)
        self._write_data_bytes(data)
        self._load_img_end()
        self._display_area(0, 0, w, h, mode)
        self._wait_display_ready()

    def display_4bpp(self, img_bytes, x=0, y=0, w=None, h=None, mode=GC16_MODE):
        """Display a 4bpp grayscale image.
        img_bytes: raw 4bpp data, 2 pixels per byte (high nibble = first pixel).
        Convention: 0=white, 15=black. Global inversion applied before sending.
        """
        if w is None: w = self.panel_w
        if h is None: h = self.panel_h

        # Global color inversion: gray → 15-gray (compensates hardware inversion)
        inverted = bytearray(len(img_bytes))
        for i, b in enumerate(img_bytes):
            hi = (b >> 4) & 0x0F
            lo = b & 0x0F
            inverted[i] = ((15 - hi) << 4) | (15 - lo)

        self._set_target_mem_addr(self.mem_addr)
        self._load_img_area_start(IT8951_4BPP, x, y, w, h)
        self._write_data_bytes(inverted)
        self._load_img_end()
        self._display_area(x, y, w, h, mode)
        self._wait_display_ready()

    def display_8bpp(self, img_bytes, x=0, y=0, w=None, h=None, mode=GC16_MODE):
        """Display an 8bpp grayscale image.
        img_bytes: raw 8bpp data, 1 byte per pixel (0=black, 255=white in PIL convention).
        Size must be w * h bytes.
        NO inversion needed — hardware already inverts (255=white in PIL → shows white).
        """
        if w is None: w = self.panel_w
        if h is None: h = self.panel_h

        # Pad to even length (2 pixels per 16-bit word)
        data = bytearray(img_bytes)
        if len(data) % 2 != 0:
            data.append(0)

        self._set_target_mem_addr(self.mem_addr)
        self._load_img_area_start(IT8951_8BPP, x, y, w, h)
        self._write_data_bytes(data)
        self._load_img_end()
        self._display_area(x, y, w, h, mode)
        self._wait_display_ready()

    def display_1bpp_a2(self, img_bytes, x=0, y=0, w=None, h=None):
        """Display a 1bpp black/white image using A2 fast refresh mode.
        img_bytes: raw 1bpp data, 8 pixels per byte (MSB=first pixel).
        0 bit = white, 1 bit = black. w must be multiple of 8.
        Size must be (w // 8) * h bytes.
        A2 mode refreshes in ~0.3s (vs ~5s for GC16).
        Requires periodic INIT clear to remove ghosting.
        """
        if w is None: w = self.panel_w
        if h is None: h = self.panel_h

        self._set_target_mem_addr(self.mem_addr)

        # Enable 1bpp mode: set UP1SR+2 bit[2]
        val = self.read_reg(UP1SR + 2)
        self.write_reg(UP1SR + 2, val | (1 << 2))
        # Set background=white(0xF0), foreground=black(0x00) — matches Waveshare C code
        self.write_reg(BGVR, (0x00 << 8) | 0xF0)

        # Load image: use 8BPP format, coordinates in BYTES (not pixels)
        # Area_W = w/8 (byte width), Area_X = x/8
        self._load_img_area_start(IT8951_8BPP, x // 8, y, w // 8, h)
        # Data: each byte = 8 pixels, sent as 16-bit words
        data = bytearray(img_bytes)
        if len(data) % 2 != 0:
            data.append(0)
        self._write_data_bytes(data)
        self._load_img_end()

        # Display with A2 mode — PIXEL coordinates (not bytes!)
        # 1bpp mode is enabled via UP1SR bit, display_area still uses pixels
        self._display_area(x, y, w, h, self.a2_mode)
        self._wait_display_ready()

        # Disable 1bpp mode
        val = self.read_reg(UP1SR + 2)
        self.write_reg(UP1SR + 2, val & ~(1 << 2))

    def display_image(self, pil_image, mode=GC16_MODE, dither=True, bg_color=255, brightness=1.0):
        """Display a PIL Image on the screen, auto-scaling to fit while
        preserving aspect ratio. Image is centered on a background.
        Uses 8bpp with Floyd-Steinberg dithering to prevent banding.

        pil_image: PIL.Image (any mode, any size).
        dither: if True (default), Floyd-Steinberg dithering to 16 levels.
                if False, send raw 8bpp (smooth but may band on gradients).
        bg_color: background L value (255=white, 0=black). Default white.
        brightness: multiplier for non-background pixels (1.0=normal, 1.3=brighter).
        """
        from PIL import Image
        import numpy as np

        # Convert to grayscale ('L' mode: 0=black, 255=white)
        if pil_image.mode != "L":
            pil_image = pil_image.convert("L")

        # Auto-scale to fit screen, preserving aspect ratio
        screen_w, screen_h = self.panel_w, self.panel_h
        img_w, img_h = pil_image.size
        scale = min(screen_w / img_w, screen_h / img_h)
        if scale < 1.0:
            new_w = int(img_w * scale)
            new_h = int(img_h * scale)
            pil_image = pil_image.resize((new_w, new_h), Image.LANCZOS)
        else:
            new_w, new_h = img_w, img_h

        # Center on background
        canvas = Image.new("L", (screen_w, screen_h), bg_color)
        offset_x = (screen_w - new_w) // 2
        offset_y = (screen_h - new_h) // 2
        canvas.paste(pil_image, (offset_x, offset_y))

        # Brightness adjustment: boost non-background pixels
        if brightness != 1.0:
            import numpy as np
            arr = np.array(canvas, dtype=np.float64)
            # Only boost pixels that differ from bg_color
            mask = np.abs(arr - bg_color) > 2  # non-background pixels
            arr[mask] = np.clip(arr[mask] * brightness, 0, 255)
            canvas = Image.fromarray(arr.astype(np.uint8), "L")

        if dither:
            # Floyd-Steinberg dithering to 16 levels (IT8951's actual gray depth).
            # Quantize to multiples of 17 (0,17,34,...,255) so the IT8951's
            # internal 256→16 mapping is exact — no extra banding.
            arr = np.array(canvas, dtype=np.float64)
            out = np.zeros_like(arr, dtype=np.uint8)
            h, w = arr.shape
            for row in range(h):
                cur = arr[row]
                q = np.round(cur / 17) * 17
                q = np.clip(q, 0, 255).astype(np.uint8)
                out[row] = q
                err = cur - q.astype(np.float64)
                if w > 1:
                    arr[row, 1:] += err[:-1] * 7 / 16
                if row + 1 < h:
                    arr[row + 1, :-1] += err[1:] * 3 / 16
                    arr[row + 1, :]   += err * 5 / 16
                    arr[row + 1, 1:]  += err[:-1] * 1 / 16
            self.display_8bpp(list(out.tobytes()), 0, 0, screen_w, screen_h, mode)
        else:
            # Raw 8bpp, no dithering
            self.display_8bpp(list(canvas.tobytes()), 0, 0, screen_w, screen_h, mode)

    def display_text(self, text, font_size=48, font_path=None,
                     bg_color=255, fg_color=0, mode=GC16_MODE):
        """Display antialiased text on the screen, auto-fitting.

        text: string to display (can be multi-line with \\n).
        font_size: base font size in pixels.
        font_path: path to .ttf font file (default: DejaVuSans).
        bg_color: background L value (255=white, 0=black).
        fg_color: text L value (0=black, 255=white).
        mode: refresh mode (GC16_MODE for quality, A2 for speed).
        """
        from PIL import Image, ImageDraw, ImageFont

        if font_path is None:
            # Try common font paths
            for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                       "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
                try:
                    ImageFont.truetype(fp, font_size)
                    font_path = fp
                    break
                except Exception:
                    continue
            if font_path is None:
                font_path = ""  # fall back to default bitmap font

        # Auto-fit: reduce font size if text doesn't fit
        # Render at 3× resolution for better anti-aliasing, then downscale.
        scale_factor = 3
        screen_w, screen_h = self.panel_w, self.panel_h
        render_w, render_h = screen_w * scale_factor, screen_h * scale_factor
        lines = text.split("\n")

        # Try decreasing font sizes until it fits at render resolution
        for try_size in range(font_size * scale_factor, 8, -2):
            if font_path:
                font = ImageFont.truetype(font_path, try_size)
            else:
                font = ImageFont.load_default()

            # Measure text
            max_w = 0
            total_h = 0
            line_heights = []
            for line in lines:
                bbox = font.getbbox(line) if hasattr(font, "getbbox") else (0, 0, 0, 0)
                lw = bbox[2] - bbox[0] if bbox[2] > bbox[0] else try_size * len(line) * 0.6
                lh = bbox[3] - bbox[1] if bbox[3] > bbox[1] else try_size
                line_heights.append(int(lh * 1.4))
                max_w = max(max_w, int(lw))
                total_h += int(lh * 1.4)

            if max_w <= render_w - 60 and total_h <= render_h - 60:
                break

        # Render at high resolution
        canvas = Image.new("L", (render_w, render_h), bg_color)
        draw = ImageDraw.Draw(canvas)
        y = (render_h - total_h) // 2
        for line in lines:
            bbox = font.getbbox(line) if hasattr(font, "getbbox") else (0, 0, 0, 0)
            lw = bbox[2] - bbox[0] if bbox[2] > bbox[0] else try_size * len(line) * 0.6
            x = (render_w - int(lw)) // 2
            draw.text((x, y), line, fill=fg_color, font=font)
            y += int(line_heights[0] * 1.0) if line_heights else try_size

        # Downscale to screen resolution with LANCZOS for smooth anti-aliasing
        canvas = canvas.resize((screen_w, screen_h), Image.LANCZOS)

        # Text: no dithering — keep smooth anti-aliased edges clean
        self.display_image(canvas, mode, dither=False)

    def sleep(self):
        self._write_cmd(IT8951_TCON_SLEEP)
        time.sleep(0.1)

    def close(self):
        try:
            self.spi.close()
        except Exception:
            pass
        self.rst.set_value(0)
        self.rst.release()
        self.cs.release()
        self.busy.release()