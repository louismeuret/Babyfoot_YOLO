import time
import socket
import subprocess
import threading
import digitalio
import board
from PIL import Image, ImageDraw, ImageFont
from adafruit_rgb_display import gc9a01a
from gpiozero import Button

# ---------- Display setup ----------
cs_pin = digitalio.DigitalInOut(board.D22)
dc_pin = digitalio.DigitalInOut(board.D25)
reset_pin = digitalio.DigitalInOut(board.D27)

BAUDRATE = 24000000
spi = board.SPI()
disp = gc9a01a.GC9A01A(
    spi, rotation=0, width=240, height=240,
    x_offset=0, y_offset=0,
    cs=cs_pin, dc=dc_pin, rst=reset_pin, baudrate=BAUDRATE,
)
WIDTH, HEIGHT = disp.width, disp.height

# ---------- Button setup ----------
HOTSPOT_NAME = "Hotspot"
button = Button(17, pull_up=True, bounce_time=0.05, hold_time=2)

# Shared state — UI thread reads these, button thread writes them
state = {
    "hotspot_active": False,
    "busy": False,           # True while we're switching modes
    "message": None,         # Transient message to flash on screen
    "message_until": 0,
}
state_lock = threading.Lock()


# ---------- Fonts ----------
try:
    font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
except OSError:
    font_big = ImageFont.load_default()
    font_small = ImageFont.load_default()


# ---------- Network helpers ----------
def is_hotspot_active():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
            capture_output=True, text=True, timeout=2,
        )
        return HOTSPOT_NAME in result.stdout.split()
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def get_wifi_status():
    """Returns (connected, ssid, ip)."""
    ssid = None
    try:
        result = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=2)
        ssid = result.stdout.strip() or None
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    ip = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        pass

    # In hotspot mode, find our AP IP from wlan0
    if ip is None:
        try:
            result = subprocess.run(
                ["ip", "-4", "-o", "addr", "show", "wlan0"],
                capture_output=True, text=True, timeout=2,
            )
            for token in result.stdout.split():
                if "/" in token and token.count(".") == 3:
                    ip = token.split("/")[0]
                    break
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    return (ssid is not None or ip is not None), ssid, ip


def is_mediamtx_running():
    try:
        result = subprocess.run(["pgrep", "-x", "mediamtx"], capture_output=True, timeout=2)
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def flash_message(text, duration=3):
    with state_lock:
        state["message"] = text
        state["message_until"] = time.time() + duration


# ---------- Hotspot toggle ----------
def toggle_hotspot():
    with state_lock:
        if state["busy"]:
            return
        state["busy"] = True

    try:
        if is_hotspot_active():
            flash_message("Stopping hotspot...")
            subprocess.run(["nmcli", "connection", "down", HOTSPOT_NAME], timeout=15)
            flash_message("Hotspot OFF", 2)
        else:
            flash_message("Starting hotspot...")
            subprocess.run(["nmcli", "connection", "up", HOTSPOT_NAME], timeout=15)
            flash_message("Hotspot ON", 2)
    except subprocess.SubprocessError as e:
        flash_message(f"Error: {e}", 3)
    finally:
        with state_lock:
            state["busy"] = False


def on_button_pressed():
    # Run in a thread so we don't block button events
    threading.Thread(target=toggle_hotspot, daemon=True).start()


button.when_pressed = on_button_pressed


# ---------- Drawing ----------
def draw_centered_text(draw, text, y, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((WIDTH - w) // 2, y), text, font=font, fill=fill)


def render_frame(wifi_connected, ssid, ip, mediamtx_ok, hotspot, busy, message):
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Outer ring: green if mediamtx running, red if not
    ring_color = (0, 200, 0) if mediamtx_ok else (220, 0, 0)
    draw.ellipse((0, 0, WIDTH - 1, HEIGHT - 1), outline=ring_color, width=8)

    # If a transient message is active, show it big in the middle
    if message:
        draw_centered_text(draw, "⚙ Working" if busy else "Status", 70, font_small, (200, 200, 200))
        draw_centered_text(draw, message, 110, font_big, (255, 255, 255))
        draw_centered_text(draw, time.strftime("%H:%M:%S"), 195, font_small, (140, 140, 140))
        return image

    # Mode label at top
    mode_label = "HOTSPOT" if hotspot else "Wi-Fi"
    mode_color = (255, 180, 0) if hotspot else (255, 255, 255)
    draw_centered_text(draw, mode_label, 40, font_small, mode_color)

    # Network name
    if hotspot:
        draw_centered_text(draw, "BabyfootPi", 70, font_big, (255, 220, 100))
    elif ssid:
        draw_centered_text(draw, ssid, 70, font_big, (255, 255, 255))
    else:
        draw_centered_text(draw, "disconnected", 70, font_big, (255, 150, 150))

    # IP
    if ip:
        draw_centered_text(draw, ip, 105, font_small, (180, 220, 255))

    # MediaMTX status
    mtx_text = "MediaMTX: running" if mediamtx_ok else "MediaMTX: stopped"
    mtx_color = (180, 255, 180) if mediamtx_ok else (255, 180, 180)
    draw_centered_text(draw, mtx_text, 145, font_small, mtx_color)

    # Hint at the bottom
    draw_centered_text(draw, "Press btn: toggle AP", 175, font_small, (120, 120, 120))
    draw_centered_text(draw, time.strftime("%H:%M:%S"), 200, font_small, (140, 140, 140))

    return image


# ---------- Main loop ----------
def main():
    try:
        while True:
            hotspot = is_hotspot_active()
            wifi_connected, ssid, ip = get_wifi_status()
            mtx = is_mediamtx_running()

            with state_lock:
                state["hotspot_active"] = hotspot
                msg = state["message"] if time.time() < state["message_until"] else None
                busy = state["busy"]

            disp.image(render_frame(wifi_connected, ssid, ip, mtx, hotspot, busy, msg))
            time.sleep(1)
    except KeyboardInterrupt:
        disp.image(Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)))


if __name__ == "__main__":
    main()
