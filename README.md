# BLE Gateway Server

A Flask-based server for receiving and logging Bluetooth Low Energy (BLE) device data from Android apps via MQTT or HTTPS, with automatic sensor detection and data visualization.

## Features

- **MQTT Support**: Receive data via MQTT (HiveMQ) - works anywhere without port forwarding!
- **HTTPS Encrypted Communication**: Automatic SSL certificate generation and HTTPS support
- **Android 9+ Compatible**: Works with modern Android security requirements
- **Dual Communication Methods**: MQTT (recommended) or direct HTTP REST API
- **Automatic Sensor Detection**: Automatically detects and parses common SI unit sensors:
  - Temperature (°C)
  - Humidity (%)
  - Pressure (hPa)
  - Battery (%)
  - Voltage (V)
  - Current (A)
  - Light/Lux (lux)
  - CO2 (ppm)
  - VOC (ppb)
  - PM2.5/PM10 (µg/m³)
- **SQLite Database**: Persistent storage of all device readings and sensor data
- **Web Dashboard**: Real-time web interface with auto-refresh
- **Comprehensive Logging**: Detailed logs to both console and rotating log files
- **Data Visualization**: Plotting tool for time-series analysis of sensor data

## Installation

### Requirements

```bash
pip install flask matplotlib cryptography paho-mqtt 'qrcode[pil]'
```

Python 3.7+ required.

**Notes**:
- The `cryptography` library is recommended for automatic SSL certificate generation. If not available, the server will fall back to using the `openssl` command-line tool.
- `paho-mqtt` is required for MQTT support (recommended). The server will work without it but only via HTTP.
- `qrcode[pil]` enables QR code generation for instant Android app setup (required for MQTT).

### Files

- `ble_gtw_server.py` - Main gateway server
- `plot_sensors.py` - Data visualization tool
- `ble_gateway.db` - SQLite database (auto-created)
- `ble_gateway.log` - Log file (auto-created)
- `connection_id.txt` - Current connection ID (auto-generated each restart, for reference only)
- `cert.pem` - SSL certificate (auto-generated)
- `key.pem` - SSL private key (auto-generated)

## Usage

### Starting the Server

```bash
./ble_gtw_server.py
```

The server will:
- Initialize the SQLite database
- Connect to MQTT broker (if paho-mqtt is installed)
- Generate SSL certificates automatically (if not present)
- Start on port 8443 with HTTPS
- Display both MQTT and HTTP endpoints for Android app configuration
- Show supported sensor types

Example output:
```
============================================================
🚀 BLE Gateway Server Starting...
============================================================

📬 MQTT Configuration:
   ✓ MQTT Enabled
   Broker: broker.hivemq.com:1883
   Server subscribed to: mikrodesign/ble_scan/+

   📱 Configure your Android app to publish to:
      Topic: mikrodesign/ble_scan/<gateway_id>
      Examples:
        - mikrodesign/ble_scan/phone1
        - mikrodesign/ble_scan/home
        - mikrodesign/ble_scan/office

   💡 Use a simple, unique gateway_id for each device

🌐 Network Information:
   Local IP:  192.168.1.100
   Public IP: 203.0.113.45

📊 Web Interface:
   Local:  https://192.168.1.100:8443
   Public: https://203.0.113.45:8443

🔌 HTTP API Endpoint (optional fallback):
   Local network:  https://192.168.1.100:8443/api/ble
   Internet:       https://203.0.113.45:8443/api/ble
   (Requires port forwarding if accessing from internet)

🔒 Security:
   Using self-signed certificate for HTTPS
   ⚠️  You'll need to accept security warnings or install cert on Android
============================================================

📡 Supported sensor types:
   battery, co2, current, humidity
   light, pm10, pm25, pressure
   temperature, voc, voltage
============================================================
📝 Logging to: ble_gateway.log
💾 Database:   ble_gateway.db
============================================================
```

### HTTPS and SSL Certificates

The server automatically generates a self-signed SSL certificate on first run. This provides:
- ✅ Encrypted communication
- ✅ Compatibility with Android 9+ (which blocks cleartext HTTP)
- ✅ Automatic certificate management

**Certificate files** (auto-generated):
- `cert.pem` - SSL certificate
- `key.pem` - Private key

**For Android apps**, you have two options:

#### Option 1: Accept Security Warning (Quick Testing)
Your Android app will show a security warning about the untrusted certificate. You can bypass this in your app's development settings.

#### Option 2: Install Certificate on Android Device (Recommended)
1. Copy `cert.pem` from the server to your Android device
2. Go to **Settings → Security → Install certificates from storage**
3. Select `cert.pem` and install it
4. The app will now trust the connection without warnings

**Note**: Certificates are valid for 365 days. Delete both `.pem` files to regenerate new certificates.

### MQTT Configuration (Recommended)

MQTT is the recommended way to connect your Android app to the server. It works anywhere with internet access, requires no port forwarding, and is more reliable than direct HTTP connections.

**Automatic 1:1 Connection with Fresh Keys:**

The server automatically generates a **NEW** unique connection ID on **every restart**. This ensures maximum security - old connections become invalid and you get a fresh, private MQTT topic each time.

- Broker: `broker.hivemq.com` (free public broker)
- Port: `1883` (server), `8000` (WebSocket for mobile)
- Connection ID: Auto-generated on each restart (e.g., `xK3pQz8A7f2e`)
- Topic: `mikrodesign/ble_scan/{connection_id}`
- Previous connections: Automatically invalidated on restart

**No configuration needed!** Just run the server and scan the NEW QR code each time.

**For Production (HiveMQ Cloud):**

If you want private, authenticated MQTT, sign up for a free HiveMQ Cloud account at https://www.hivemq.com/mqtt-cloud-broker/

Then edit the MQTT configuration at the top of `ble_gtw_server.py`:

```python
MQTT_BROKER = "your-instance.hivemq.cloud"  # Your HiveMQ Cloud URL
MQTT_PORT = 8883
MQTT_TOPIC_BASE = "mikrodesign/ble_scan"  # Keep the same or change if needed
MQTT_USERNAME = "your_username"
MQTT_PASSWORD = "your_password"
MQTT_USE_TLS = True
```

**Android App Configuration:**

Configure your Android app to publish BLE data to the same MQTT broker and topic. The message format should be a JSON array:

```json
[
  {
    "id": "AA:BB:CC:DD:EE:FF",
    "name": "TempSensor",
    "rssi": -65,
    "advertising": {
      "temp": 23.5,
      "humidity": 45.2
    }
  }
]
```

### Network Configuration

- **Local network**: Use the local IP address if the Android app is on the same WiFi network
- **Internet access**: Use the public IP address, but you'll need to:
  1. Configure port forwarding on your router (forward port 8443 to your local IP)
  2. Ensure your firewall allows incoming connections on port 8443

### Viewing the Dashboard

Open your browser to `https://localhost:8443` to see:
- Number of active devices
- Last update timestamp
- Device list with RSSI (signal strength)
- Advertising data from each device

The page auto-refreshes every 5 seconds.

### Communication Methods

The server supports two methods for receiving BLE data:

#### 1. MQTT (Recommended)

The server subscribes to MQTT topics to receive data:
- **Broker:** Configurable (default: `broker.hivemq.com`)
- **Topic Pattern:** `mikrodesign/ble_scan/{gateway_id}`
- **Server subscribes to:** `mikrodesign/ble_scan/+` (wildcard for all gateways)
- **Message Format:** JSON array (same as HTTP POST body)

Each Android device publishes to its own unique topic (e.g., `mikrodesign/ble_scan/phone1`)

#### 2. HTTP REST API

#### POST `/api/ble`
Receive BLE device data from gateway app via HTTP.

**Request body:**
```json
[
  {
    "id": "AA:BB:CC:DD:EE:FF",
    "name": "TempSensor",
    "rssi": -65,
    "advertising": {
      "temp": 23.5,
      "humidity": 45.2
    }
  }
]
```

**Response:**
```json
{
  "status": "success",
  "received": 1,
  "sensors_detected": 2,
  "timestamp": "2025-10-18 12:00:00"
}
```

#### GET `/api/devices`
Get latest device data as JSON.

### Plotting Sensor Data

The `plot_sensors.py` tool visualizes historical sensor data from the database.

#### List Available Data

```bash
./plot_sensors.py --list
```

Shows all devices and sensor types in the database.

#### Plot Temperature

```bash
# All devices
./plot_sensors.py --sensor temperature

# Specific device, last 12 hours
./plot_sensors.py --sensor temperature --device AA:BB:CC:DD:EE:FF --hours 12

# Save to file
./plot_sensors.py --sensor temperature --save temp_plot.png
```

#### Plot Signal Strength (RSSI)

```bash
# All devices
./plot_sensors.py --rssi

# Specific device
./plot_sensors.py --rssi --device AA:BB:CC:DD:EE:FF --hours 24
```

#### Available Options

```
--list              List available devices and sensors
--sensor TYPE       Plot specific sensor type
--rssi              Plot signal strength
--device ID         Filter by device ID
--hours N           Hours of data to plot (default: 24)
--save FILE         Save plot to file instead of displaying
--db FILE           Database file (default: ble_gateway.db)
```

## Logging

Logs are written to both console (INFO level) and file (DEBUG level).

### Console Output

When data arrives:
```
============================================================
📡 INCOMING DATA - 2 device(s)
============================================================
Device 1/2: TempSensor
  ID: AA:BB:CC:DD:EE:FF
  RSSI: -65 dBm 📶
  Sensors detected: 2
    • temperature: 23.5 °C (from field: temp)
    • humidity: 45.2 % (from field: hum)

✓ Successfully processed 2 device(s), 2 total sensor reading(s)
============================================================
```

### Log File

View live logs:
```bash
tail -f ble_gateway.log
```

The log file includes:
- All console output
- Raw advertising JSON data (DEBUG level)
- Database write confirmations
- Full error stack traces

Logs automatically rotate at 10MB, keeping 5 backup files.

## Database Schema

### `device_readings` Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| timestamp | DATETIME | Reading timestamp |
| device_id | TEXT | BLE device MAC address |
| device_name | TEXT | Device name |
| rssi | INTEGER | Signal strength (dBm) |
| raw_data | TEXT | JSON advertising data |

### `sensor_data` Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| reading_id | INTEGER | Foreign key to device_readings |
| sensor_type | TEXT | Sensor type (temperature, humidity, etc.) |
| sensor_value | REAL | Numeric value |
| unit | TEXT | Unit of measurement |

## Sensor Detection

The server automatically detects sensor values in the advertising JSON using pattern matching:

```python
{
  "temp": 23.5,           # Detected as temperature (°C)
  "humidity": 45.2,       # Detected as humidity (%)
  "bat": 87,              # Detected as battery (%)
  "pressure": 1013.25,    # Detected as pressure (hPa)
  "lux": 450              # Detected as light (lux)
}
```

Nested fields are also supported:
```python
{
  "sensors": {
    "environmental": {
      "temperature": 23.5  # Detected as temperature
    }
  }
}
```

## Android App Configuration

### Option 1: MQTT (Recommended)

#### Quick Setup with QR Code (Easiest!)

1. Run the server: `python3 ble_gtw_server.py`
2. A NEW QR code appears in the terminal
3. Open your Android BLE scanner app
4. Scan the QR code
5. Done! The app is now connected

**Important:** Each server restart generates a NEW connection ID for security. You'll need to scan the new QR code each time.

The QR code contains everything:
- Broker: `broker.hivemq.com`
- Port: `8000` (WebSocket for mobile apps)
- Topic: `mikrodesign/ble_scan/{unique_connection_id}`
- Connection ID (freshly generated each restart)

#### Manual Configuration

If you can't scan the QR code, the server also displays manual configuration:

**Broker:** `broker.hivemq.com`
**Port:** `1883`
**Topic:** (shown in server output, e.g., `mikrodesign/ble_scan/xK3pQz8A`)
**QoS:** `1` (at least once)

Benefits:
- ✅ **Zero configuration** - auto-generated connection ID
- ✅ **Maximum security** - fresh connection ID on every restart
- ✅ **Auto-flush** - old connections become invalid automatically
- ✅ **True 1:1 private** - unique random ID with timestamp
- ✅ Works anywhere with internet (no port forwarding needed)
- ✅ No SSL certificate issues
- ✅ More reliable for mobile connections
- ✅ Lower latency
- ✅ QR code instant setup

### Option 2: Direct HTTP (Fallback)

Set the gateway endpoint URL in your Android BLE scanning app. The server displays both local and public IP addresses on startup.

**For local network (same WiFi):**
```
https://LOCAL_IP:8443/api/ble
```

**For internet access (requires port forwarding):**
```
https://PUBLIC_IP:8443/api/ble
```

The app should POST JSON arrays of device objects to this endpoint.

**Note:** HTTP requires dealing with self-signed certificates (see below).

### Handling Self-Signed Certificates in Android

If your Android app doesn't trust the self-signed certificate, you have several options:

**Option 1: Install certificate on device** (Recommended for testing)
- Transfer `cert.pem` to your Android device
- Install via Settings → Security → Install certificates

**Option 2: Configure Network Security Config** (For development)
Add to your Android app's `res/xml/network_security_config.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="false">
        <trust-anchors>
            <certificates src="system" />
            <certificates src="user" />
        </trust-anchors>
    </base-config>
    <!-- For testing only - replace with your server IP -->
    <domain-config cleartextTrafficPermitted="false">
        <domain includeSubdomains="true">YOUR_SERVER_IP</domain>
        <trust-anchors>
            <certificates src="user" />
        </trust-anchors>
    </domain-config>
</network-security-config>
```

And reference it in your `AndroidManifest.xml`:
```xml
<application
    android:networkSecurityConfig="@xml/network_security_config"
    ...>
```

## Troubleshooting

### Server won't start
- Check if port 8443 is already in use: `lsof -i :8443`
- Verify Python 3.7+ is installed
- Ensure required packages are installed: `pip install flask cryptography paho-mqtt`
- If certificate generation fails, ensure `openssl` is installed

### MQTT connection issues
- **"paho-mqtt not installed"**: Install with `pip install paho-mqtt`
- **"Failed to connect to MQTT broker"**: Check internet connection and broker address
- **No data appearing**: Verify Android app is publishing to the correct topic pattern (`mikrodesign/ble_scan/{gateway_id}`)
- **Multiple devices**: Each device should use a unique gateway_id (e.g., phone1, phone2, home, office)
- **Using HiveMQ Cloud**: Ensure TLS is enabled and credentials are correct

### Certificate errors
- Delete `cert.pem` and `key.pem` to regenerate certificates
- Ensure `cryptography` library is installed: `pip install cryptography`
- If using openssl fallback, verify it's installed: `openssl version`

### Android app can't connect (SSL errors)
- **"Certificate not trusted"**: Install `cert.pem` on Android device or configure Network Security Config
- **"Unable to resolve host"**: Check IP address is correct
- **"Connection refused"**: Verify server is running and firewall allows port 8443
- **Android 9+ cleartext traffic**: The server now uses HTTPS, no cleartext config needed

### No data appearing
- Verify Android app is configured with correct IP address and HTTPS
- Check firewall allows connections on port 8443
- View logs: `tail -f ble_gateway.log`
- Test connection: `curl -k https://localhost:8443/` (the `-k` flag bypasses certificate verification)

### Database errors
- Delete `ble_gateway.db` to recreate fresh database
- Check file permissions

### Plotting errors
- Install matplotlib: `pip install matplotlib`
- Ensure database has data: `./plot_sensors.py --list`

## License

MIT License

## Contributing

Contributions welcome! Please submit issues and pull requests on GitHub.
