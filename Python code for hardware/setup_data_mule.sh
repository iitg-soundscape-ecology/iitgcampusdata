#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "========================================================================="
echo "        Rainforest Data Mule System - Installer & Service Setup          "
echo "========================================================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "[ERROR] Please run this script with sudo privileges (e.g., sudo ./setup_data_mule.sh)"
  exit 1
fi

# Dynamically detect the directory where this installer script is located
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

# Safe fallback: if SCRIPT_DIR resolves to empty, dot, or root, use pwd
if [ -z "$SCRIPT_DIR" ] || [ "$SCRIPT_DIR" = "." ] || [ "$SCRIPT_DIR" = "/" ]; then
    SCRIPT_DIR="$(pwd)"
fi

# Clean up any trailing carriage returns if the variable was parsed with Windows line endings
SCRIPT_DIR=$(echo "$SCRIPT_DIR" | tr -d '\r')

echo "[INFO] Detected installation directory: $SCRIPT_DIR"

echo "[1/5] Installing system dependencies..."
apt-get update
# python3-dbus and python3-gi are installed via apt to avoid compilation issues
apt-get install -y python3-dbus python3-gi python3-serial sox libsox-fmt-all bluetooth bluez

echo "[2/5] Installing Python libraries..."
# Try system apt packages first to respect PEP 668 externally managed environment rules
if apt-get install -y python3-flask python3-serial python3-librosa python3-numpy python3-joblib; then
    echo "[OK] Python dependencies installed via apt."
else
    echo "[INFO] apt-get install failed for Python packages, trying pip with system overrides..."
    pip3 install --break-system-packages flask pyserial librosa numpy joblib
fi

echo "[3/5] Configuring BlueZ Bluetooth daemon for experimental mode..."
BLUETOOTH_SERVICE_FILE="/lib/systemd/system/bluetooth.service"

if [ -f "$BLUETOOTH_SERVICE_FILE" ]; then
    # 1. Automatic recovery: if the file has /usr/lib/bluetooth/bluetoothd but it doesn't exist
    # and /usr/libexec/bluetooth/bluetoothd does exist (standard on newer Debian/Trixie/Bookworm Pi OS),
    # repair it first.
    if grep -q "/usr/lib/bluetooth/bluetoothd" "$BLUETOOTH_SERVICE_FILE"; then
        if [ ! -f "/usr/lib/bluetooth/bluetoothd" ] && [ -f "/usr/libexec/bluetooth/bluetoothd" ]; then
            echo "[INFO] Repairing bluetoothd daemon path to /usr/libexec/bluetooth/bluetoothd..."
            sed -i 's|/usr/lib/bluetooth/bluetoothd|/usr/libexec/bluetooth/bluetoothd|g' "$BLUETOOTH_SERVICE_FILE"
        fi
    fi

    # 2. Append the --experimental flag safely to the end of the ExecStart line if not already present
    if ! grep -q -E "\--experimental|-E" "$BLUETOOTH_SERVICE_FILE"; then
        echo "[INFO] Enabling experimental mode in bluetooth.service..."
        sed -i '/^ExecStart=/ s/$/ --experimental/' "$BLUETOOTH_SERVICE_FILE"
        systemctl daemon-reload
        systemctl restart bluetooth
        echo "[OK] Bluetooth service restarted with experimental features enabled."
    else
        echo "[INFO] Experimental flag already configured in bluetooth.service."
        # Even if present, trigger a restart to ensure it's running properly after repair
        systemctl daemon-reload
        if systemctl restart bluetooth; then
            echo "[OK] Bluetooth service restarted successfully."
        else
            echo "[WARNING] Bluetooth restart failed. Checking status..."
            systemctl status bluetooth.service || true
        fi
    fi
else
    echo "[WARNING] bluetooth.service not found at $BLUETOOTH_SERVICE_FILE. Please configure your BlueZ daemon for experimental mode manually if BLE fails."
fi

echo "[4/5] Creating Systemd services for Rainforest Data Mule..."
SERVICE_FILE="/etc/systemd/system/data_mule.service"

cat <<EOT > "$SERVICE_FILE"
[Unit]
Description=Rainforest Monitor BLE & Data Mule Web Server
After=bluetooth.target network.target

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 -u "$SCRIPT_DIR/data_mule_server.py"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOT

echo "[OK] Web/BLE service file created at $SERVICE_FILE."

REC_SERVICE_FILE="/etc/systemd/system/soundscape_recorder.service"
cat <<EOT > "$REC_SERVICE_FILE"
[Unit]
Description=Continuous Soundscape Monitor and Classifier
After=local-fs.target

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 -u "$SCRIPT_DIR/soundscape_ngrok_final.py"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOT

echo "[OK] Soundscape recorder service file created at $REC_SERVICE_FILE."

echo "[5/5] Enabling and starting Systemd services..."
systemctl daemon-reload
systemctl enable data_mule.service
systemctl enable soundscape_recorder.service
systemctl restart data_mule.service
systemctl restart soundscape_recorder.service

echo "========================================================================="
echo "[SUCCESS] Rainforest Data Mule System is installed and running!"
echo "- Web/BLE status: 'sudo systemctl status data_mule.service'"
echo "- Recorder status: 'sudo systemctl status soundscape_recorder.service'"
echo "- BLE advertisement 'Forest_Ear_BLE' is active continuously."
echo "- Connect your Android Bluetooth terminal, type 'Wake' to enable Wi-Fi."
echo "========================================================================="
