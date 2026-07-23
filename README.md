# IT8951 E-Paper Display Driver — Orange Pi Zero 2W

Python driver and HTTP API for the **Waveshare 7.8" E-Ink HAT** (1872×1404, IT8951 controller)
on an **Orange Pi Zero 2W** (Allwinner H616, 1.5GB RAM).

## Features

- 📺 **Full IT8951 SPI driver** — device init, VCOM read/set, 4bpp & 8bpp display
- 📝 **Antialiased text rendering** — auto-fitting, multi-line, configurable font/size, 3× supersampling
- 🖼️ **Image display** — auto-scaled to fit screen, aspect ratio preserved, centered, brightness boost
- 🌐 **HTTP API server** — push text/images from any device on the network
- 🎨 **Built-in test patterns** — gradient, checkerboard, cross, quarter fill
- 🌫️ **Random dithering** — smooth 16-level gradients without hard banding edges
- 🔄 **Color handling** — 8bpp for text/images (smooth), 4bpp for patterns (direct control)

![SneakyJoe Avatar on E-Ink](https://media.discordapp.net/attachments/337997702170279946/1529633966275952680/PXL_20260722_233745690.MP.jpg?ex=6a62a624&is=6a6154a4&hm=1f21369a3ffde08f96da7da189940bb5c3112ee617fe67bf23216b8fe44c492a&animated=true&width=1785&height=1344)
![Cross gradient](https://media.discordapp.net/attachments/337997702170279946/1529633967135916152/PXL_20260722_233342804.MP.jpg?ex=6a62a624&is=6a6154a4&hm=afe63f23d5c7e0f8e3c7cf0a5f4369fe5ec5f6f170590d4f3f7f15d0cfa9e138&animated=true&width=1785&height=1344)
![Antialiased text](https://media.discordapp.net/attachments/337997702170279946/1529633968079634604/PXL_20260722_233256404.MP.jpg?ex=6a62a625&is=6a6154a5&hm=ed58adc604bb8715ffc913c27a1ff44491d0379b7cd2721ee919d5fd6782fc37&animated=true&width=1785&height=1344)
![Vertical gradient](https://media.discordapp.net/attachments/337997702170279946/1529633968952049815/PXL_20260722_233901518.MP.jpg?ex=6a62a625&is=6a6154a5&hm=c3f2bda95e18c8ce66db2b94f89bbb61df4e52674c5ef2ae5166f24210a4a220&animated=true&width=1785&height=1344)


## Table of Contents

- [Hardware Setup](#hardware-setup)
- [OS Configuration](#os-configuration--bring-os-to-working-state)
- [Installation](#installation)
- [Usage — CLI Tests](#usage--cli-tests)
- [Usage — HTTP API](#usage--http-api)
- [Usage — As a Library](#usage--as-a-library-in-your-projects)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)

## Hardware Setup

### What you need

| Component | Details |
|-----------|---------|
| Board | Orange Pi Zero 2W (H616, 1.5GB RAM) |
| Display | Waveshare 7.8" E-Ink HAT (1872×1404, IT8951, SPI) |
| OS | Ubuntu 24.04 LTS (aarch64) |
| Connection | HAT plugs onto GPIO header (SPI mode, not I80) |

### GPIO Pin Mapping (H616, port PH)

| Signal | GPIO | Pin Name | Notes |
|--------|------|----------|-------|
| RST | 226 | PH2 | Reset |
| CS | 229 | PH5 | SPI1 CS0 (manually driven via GPIO) |
| BUSY | 228 | PH4 | Busy/ready signal |
| SPI CLK | 231 | PH7 | SPI1 clock |
| SPI MOSI | 232 | PH8 | SPI1 data out |
| SPI MISO | 233 | PH9 | SPI1 data in |

## OS Configuration — Bring OS to Working State

This section covers everything needed to get a fresh Ubuntu 24.04 install
on the Orange Pi Zero 2W working with the IT8951 e-paper HAT.

### 1. Flash Ubuntu 24.04

Download the Orange Pi Zero 2W Ubuntu image from the official Orange Pi website
and flash it to a microSD card:

```bash
# Example using dd (replace /dev/sdX with your SD card device)
sudo dd if=ubuntu-24.04-orangepizero2w.img of=/dev/sdX bs=4M status=progress
sync
```

### 2. First boot & SSH access

Connect the Pi to your network (Ethernet or WiFi) and find its IP address.

```bash
# On the Pi (via serial console or HDMI):
sudo nmcli device wifi connect "YourWiFi" password "YourPassword"
hostname -I
sudo systemctl enable --now ssh
```

### 3. Set up SSH key (from your dev machine)

```bash
ssh-copy-id orangepi@192.168.0.199
# Or manually add your public key to ~/.ssh/authorized_keys on the Pi
```

### 4. Configure boot overlay (CRITICAL)

The Waveshare HAT's CS line is physically wired to SPI1 CS0 (GPIO 229).
We need to control CS manually (like the Waveshare C code does), so we must
prevent the kernel from claiming GPIO 229. By enabling only CS1 in the overlay,
GPIO 229 stays free for manual GPIO control.

Edit `/boot/orangepiEnv.txt`:

```ini
verbosity=1
bootlogo=false
console=both
overlay_prefix=sun50i-h616
rootdev=UUID=your-root-uuid
rootfstype=ext4
overlays=spi1-cs1-spidev    # ONLY CS1 enabled, frees GPIO 229 for manual CS
```

> **Why `spi1-cs1-spidev` and not `spi1-cs0-cs1-spidev`?**
> With both CS0+CS1 enabled, the kernel claims GPIO 229 (CS0) for the SPI driver.
> Our driver needs to manually toggle GPIO 229 as CS (matching the Waveshare C code).
> By enabling only CS1, GPIO 229 is free for manual control. We open `/dev/spidev1.1`
> (CS1) just to get an SPI file descriptor, then drive CS via GPIO 229 ourselves.

Reboot:
```bash
sudo reboot
```

Verify after reboot:
```bash
ls /dev/spidev*    # should show /dev/spidev1.1 only (NOT spidev1.0)
```

### 5. Install system packages

```bash
sudo apt update
sudo apt install -y python3-pil python3-libgpiod python3-spidev python3-numpy python3-pip
```

### 6. Verify hardware connection

```bash
sudo cat /sys/kernel/debug/gpio | grep -E "226|228|229"
# GPIO 226 (RST), 228 (BUSY) should show as GPIO (free)
# GPIO 229 (CS) should NOT appear (free for manual control)
```

## Installation

### Option A: Clone from GitHub

```bash
cd /opt
sudo git clone https://github.com/sneakyjoeru/it8951-epaper-python-orangepi-zero-2w.git it8951-epaper
sudo chown -R $USER:$USER it8951-epaper
cd it8951-epaper
```

### Option B: Copy files manually

```bash
sudo mkdir -p /opt/it8951-epaper
# Copy it8951_driver.py, main.py, server/server.py, etc. to /opt/it8951-epaper/
```

### Verify installation

```bash
cd /opt/it8951-epaper
sudo python3 main.py --info
```

Expected output:
```
Panel:   1872 x 1404
Memory:  0x00124850
FW:      v.0.1
LUT:     M814T
A2 mode: 6
VCOM:    2500 (=-2.50V)
```

### (Optional) Install as systemd service

```bash
sudo cp it8951-epaper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now it8951-epaper
```

The API server will start on port 8888 and survive reboots.

## Usage — CLI Tests

All CLI commands require `sudo` (for SPI/GPIO access):

```bash
cd /opt/it8951-epaper

# Show device info + VCOM
sudo python3 main.py --info

# Clear screen to white
sudo python3 main.py --clear

# Display text (auto-fitted, antialiased, 3× supersampled)
sudo python3 main.py --text "Hello, World!"
sudo python3 main.py --text "Large Text" --font-size 120
sudo python3 main.py --text "Multi\nLine\nText" --font-size 64

# Display image (auto-scaled, aspect preserved, centered, black bg, 1.4× brightness)
sudo python3 main.py --image photo.png
sudo python3 main.py --image test_image.jpg

# Test patterns
sudo python3 main.py --gradient              # smooth white→black gradient (random dithering)
sudo python3 main.py --checker 50            # 50px checkerboard
sudo python3 main.py --cross 9               # 9px gradient cross (corners→center)
sudo python3 main.py --cross 9 --vertical    # cross with bottom-to-top gradient
sudo python3 main.py --cross 9 --invert      # inverted: black bg, white cross
sudo python3 main.py --quarter               # top-left quarter black

# Start HTTP API server
sudo python3 main.py --server --port 8888
```

### Test patterns explained

| Pattern | Description | Dithering |
|---------|-------------|-----------|
| `--gradient` | Vertical white→black gradient | Random dithering with fractional gray levels for smooth transitions |
| `--checker 50` | 50×50px black/white checkerboard | None (pure black/white) |
| `--cross 9` | 4 diagonal lines from corners to center, 9px wide, gradient from transparent to solid | Random dithering for smooth gradient lines |
| `--cross 9 --invert` | Same but inverted: black background, white lines | Random dithering |
| `--cross 9 --vertical` | Cross with bottom-to-top gradient instead of corner-to-center | Random dithering |
| `--quarter` | Top-left quarter filled black, rest white | None |

### Combining commands

```bash
# Clear then display in one go
sudo python3 main.py --clear && sudo python3 main.py --text "Hello!"

# Clear then show image
sudo python3 main.py --clear && sudo python3 main.py --image test_image.jpg
```

## Usage — HTTP API

Start the server:
```bash
sudo python3 main.py --server --port 8888
```

Or via systemd:
```bash
sudo systemctl start it8951-epaper
```

### Endpoints

#### `GET /info`
Returns device info (panel size, firmware, VCOM).

```bash
curl http://192.168.0.199:8888/info
```

Response:
```json
{
  "ok": true,
  "device": {
    "panel_w": 1872,
    "panel_h": 1404,
    "fw_version": "v.0.1",
    "lut_version": "M814T",
    "vcom": 2500
  }
}
```

#### `POST /text`
Display antialiased text.

```bash
curl -X POST http://192.168.0.199:8888/text \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello from the network!", "font_size": 64}'
```

Parameters:
- `text` (required): string to display (use `\n` for multi-line)
- `font_size` (optional, default 48): base font size
- `font_path` (optional): path to .ttf font file
- `bg_color` (optional, default 255): background L value (255=white, 0=black)
- `fg_color` (optional, default 0): text L value (0=black, 255=white)

#### `POST /image`
Display an image (auto-scaled, aspect ratio preserved, centered).

```bash
# Multipart upload
curl -X POST http://192.168.0.199:8888/image \
  -F "file=@photo.jpg"

# Or raw image bytes
curl -X POST http://192.168.0.199:8888/image \
  --data-binary @photo.png
```

#### `POST /clear`
Clear screen to white.

```bash
curl -X POST http://192.168.0.199:8888/clear
```

#### `POST /raw`
Display raw 4bpp data (advanced).

```bash
curl -X POST http://192.168.0.199:8888/raw \
  -H "Content-Type: application/json" \
  -d '{"data": "base64-encoded-4bpp-data", "w": 1872, "h": 1404}'
```

## Usage — As a Library in Your Projects

The driver can be imported and used directly in Python scripts:

```python
from it8951_driver import IT8951, GC16_MODE, INIT_MODE

# Initialize
epd = IT8951()
epd.init()
print(f"Panel: {epd.panel_w} x {epd.panel_h}")

# Clear screen
epd.clear()

# Display text
epd.display_text("Hello, World!", font_size=96)

# Display image (auto-scaled, centered)
from PIL import Image
img = Image.open("photo.jpg")
epd.display_image(img, bg_color=0, brightness=1.4)

# Display 8bpp raw data (1 byte per pixel, 0=black, 255=white)
raw_data = bytes([128] * (1872 * 1404))  # gray fill
epd.display_8bpp(raw_data, 0, 0, 1872, 1404, GC16_MODE)

# Display 4bpp raw data (2 pixels per byte, 0=white, 15=black)
raw_4bpp = bytes([0xFF] * (936 * 1404))  # all black
epd.display_4bpp(raw_4bpp, 0, 0, 1872, 1404, GC16_MODE)

# Read/set VCOM
vcom = epd.get_vcom()
print(f"VCOM: -{vcom/1000:.2f}V")
epd.set_vcom(2510)  # -2.51V

# Clean up
epd.clear()
epd.close()
```

### Key API methods

| Method | Description |
|--------|-------------|
| `IT8951()` | Create driver instance (opens SPI, requests GPIO) |
| `.init()` | Reset, get device info (panel size, FW, LUT) |
| `.clear(mode=INIT_MODE)` | Clear screen to white |
| `.display_text(text, font_size=48)` | Display antialiased text (auto-fitting) |
| `.display_image(pil_image, bg_color=255, brightness=1.0)` | Display PIL image (auto-scaled) |
| `.display_8bpp(data, x, y, w, h, mode)` | Display raw 8bpp data (0=black, 255=white) |
| `.display_4bpp(data, x, y, w, h, mode)` | Display raw 4bpp data (0=white, 15=black) |
| `.get_vcom()` / `.set_vcom(val)` | Read/set VCOM (millivolts, e.g. 2510 = -2.51V) |
| `.get_info()` | Return dict with panel_w, panel_h, memory_addr, etc. |
| `.sleep()` | Put IT8951 to sleep |
| `.close()` | Release SPI and GPIO resources |

### Color conventions

- **8bpp** (used by text and images): PIL convention — `0=black`, `255=white`
- **4bpp** (used by patterns): `0=white`, `15=black` (inverted in `display_4bpp` for hardware)
- The display hardware inverts colors. The driver handles this automatically:
  - `display_8bpp()`: sends data directly (hardware inverts → correct display)
  - `display_4bpp()`: applies nibble inversion before sending (cancels hardware inversion)

### Refresh modes

| Mode | Value | Description | Speed |
|------|-------|-------------|-------|
| INIT | 0 | Full clear/flash | ~5s |
| GC16 | 2 | 16-level grayscale, best quality | ~3-5s |
| A2 | 6 | Fast black/white only | ~0.3s |

Use `GC16_MODE` for images and text (best quality).
Use A2 mode for fast black/white updates (requires periodic INIT clear).

## Architecture

```
it8951-epaper/
├── main.py              # CLI entry point + test patterns
├── it8951_driver.py     # Core IT8951 driver (SPI, GPIO, display, text, image)
├── server/
│   └── server.py        # HTTP API server (text, image, clear, info endpoints)
├── test_image.jpg       # Default test image
├── requirements.txt     # Python dependencies
├── it8951-epaper.service # systemd service file
├── .gitignore           # Protects against SSH key/secret leaks
└── README.md            # This file
```

### How SPI communication works

The IT8951 uses a custom SPI protocol with 16-bit commands:

| Operation | Preamble | Data |
|-----------|----------|------|
| Write command | `0x6000` | 16-bit command (big-endian) |
| Write data | `0x0000` | 16-bit data (big-endian) |
| Read data | `0x1000` | dummy `0x0000` → 16-bit data (big-endian) |

All transactions:
1. Wait for BUSY pin = HIGH (idle)
2. Pull CS (GPIO 229) LOW
3. Send preamble + data via SPI (atomic ioctl call)
4. Pull CS HIGH

The driver uses raw `SPI_IOC_MESSAGE(N)` ioctl for atomic multi-transfers.

### How dithering works

The IT8951's GC16 mode displays 16 actual gray levels, even with 8bpp input.
To prevent visible banding:

- **Gradients/patterns (4bpp)**: Random dithering — each pixel gets a fractional
  gray level (e.g. 7.3), then randomly picks level 7 or 8 with probability based
  on the fraction. This creates smooth transitions without hard edges.
- **Images (8bpp)**: Floyd-Steinberg dithering to 16 levels (multiples of 17).
  Error diffusion breaks up banding.
- **Text**: No dithering (8bpp direct) — anti-aliased edges stay clean and smooth.

## Troubleshooting

### "Device or resource busy" on GPIO

A previous process didn't release the GPIO lines. Kill it:
```bash
sudo fuser /dev/spidev1.1
sudo kill -9 <PID>
```

### "Busy never released" after reset

- Check that the HAT is properly seated on the GPIO header
- Verify the boot overlay is `spi1-cs1-spidev` (not `cs0-cs1`)
- Check `/dev/spidev1.1` exists: `ls /dev/spidev*`
- Check GPIO 229 is free: `sudo cat /sys/kernel/debug/gpio | grep 229`
  (should show nothing — GPIO 229 must NOT be kernel-claimed)

### All zeros or 0xFFFF in device info

- Wrong overlay: make sure you're using `spi1-cs1-spidev`
- GPIO conflict: check kernel hasn't claimed GPIO 229

### Colors appear inverted

The driver handles this automatically. If colors are still wrong:
- For 8bpp: data is sent directly (hardware inverts) — no action needed
- For 4bpp: `display_4bpp()` applies nibble inversion — don't double-invert

### Text appears pixelated

- Ensure you're using `display_text()` which does 3× supersampling
- Don't use dithering for text (it adds noise to smooth edges)
- Try a larger `font_size`

### Image appears too dark

- Use the `brightness` parameter: `epd.display_image(img, brightness=1.4)`
- Values > 1.0 brighten, < 1.0 darken

### `/tmp` files disappear after reboot

`/tmp` is cleared on reboot. Install to `/opt/it8951-epaper/` instead,
or use the systemd service which runs from `/opt/`.

## Credits

- Based on [Waveshare IT8951-ePaper](https://github.com/waveshare/IT8951-ePaper) C code (GPIOD mode)
- Original [waveshare/IT8951](https://github.com/waveshare/IT8951) repository (bcm2835, RPi-only)

## License

MIT
