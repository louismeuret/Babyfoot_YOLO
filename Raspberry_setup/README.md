# How the raspberry pi is setup:

Adding SPI connection using the terminal interface
sudo raspi-config nonint do_spi 0

installation of the packages:
python3 -m venv ~/tft-env --system-site-packages
source ~/tft-env/bin/activate
pip install adafruit-circuitpython-rgb-display Pillow numpy

The automatic startups:
sudo nano /etc/systemd/system/mediamtx.service

[Unit]
Description=MediaMTX streaming server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/pi/mediamtx /home/pi/mediamtx.yml
Restart=on-failure
RestartSec=5
User=pi

[Install]
WantedBy=multi-user.target

and the display:
mkdir -p /home/pi/tft-display
mv /home/pi/adafruit_display.py /home/pi/tft-display/display.py

[Unit]
Description=TFT round display status
After=network-online.target mediamtx.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/pi/tft-env/bin/python /home/pi/tft-display/display.py
WorkingDirectory=/home/pi/tft-display
Restart=on-failure
RestartSec=5
User=pi
# Give the network a moment to come up so SSID/IP are ready on first frame
ExecStartPre=/bin/sleep 3

[Install]
WantedBy=multi-user.target

we restart everything:
sudo systemctl daemon-reload

sudo systemctl enable mediamtx.service
sudo systemctl start mediamtx.service

sudo systemctl enable tft-display.service
sudo systemctl start tft-display.service

For the button, we need to add a new profile:
sudo nmcli connection add type wifi ifname wlan0 con-name Hotspot autoconnect no \
    ssid "BabyfootPi" \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    ipv4.method shared \
    ipv6.method disabled \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "babyfoot1234"
    
And to switch the networks without using sudo:

sudo nano /etc/polkit-1/rules.d/50-pi-network.rules

polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0
        && subject.user === "pi") {
        return polkit.Result.YES;
    }
});

We use "display.py"

Then the pinout: 
| Component | Pin | Raspberry Pi | Physical Pin |
|-----------|-----|--------------|--------------|
| Display | VCC | 3.3V | Pin 1 |
| Display | GND | GND | Pin 6 |
| Display | SCL (SCK) | GPIO 11 (SCLK) | Pin 23 |
| Display | SDA (MOSI) | GPIO 10 (MOSI) | Pin 19 |
| Display | CS | GPIO 22 | Pin 15 |
| Display | DC | GPIO 25 | Pin 22 |
| Display | RST | GPIO 27 | Pin 13 |
| Button | - (GND) | GND | Pin 9 |
| Button | S (Signal) | GPIO 17 | Pin 11 |



