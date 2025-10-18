# BLE Gateway Server

A Flask-based server for receiving and logging Bluetooth Low Energy (BLE) device data from Android apps, with automatic sensor detection and data visualization.

## Features

- **Real-time BLE Data Reception**: Receives device data from Android gateway apps via REST API
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
pip install flask matplotlib
```

Python 3.7+ required.

### Files

- `ble_gtw_server.py` - Main gateway server
- `plot_sensors.py` - Data visualization tool
- `ble_gateway.db` - SQLite database (auto-created)
- `ble_gateway.log` - Log file (auto-created)

## Usage

### Starting the Server

```bash
./ble_gtw_server.py
```

The server will:
- Initialize the SQLite database
- Start on port 8080
- Display both local and public IP addresses for Android app configuration
- Show supported sensor types

Example output:
```
============================================================
🚀 BLE Gateway Server Starting...
============================================================

🌐 Network Information:
   Local IP:  192.168.1.100
   Public IP: 203.0.113.45

📊 Web Interface:
   Local:  http://192.168.1.100:8080
   Public: http://203.0.113.45:8080

🔌 API Endpoint (for Android app):
   Local network:  http://192.168.1.100:8080/api/ble
   Internet:       http://203.0.113.45:8080/api/ble
   (Requires port forwarding if accessing from internet)
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

### Network Configuration

- **Local network**: Use the local IP address if the Android app is on the same WiFi network
- **Internet access**: Use the public IP address, but you'll need to:
  1. Configure port forwarding on your router (forward port 8080 to your local IP)
  2. Ensure your firewall allows incoming connections on port 8080

### Viewing the Dashboard

Open your browser to `http://localhost:8080` to see:
- Number of active devices
- Last update timestamp
- Device list with RSSI (signal strength)
- Advertising data from each device

The page auto-refreshes every 5 seconds.

### API Endpoints

#### POST `/api/ble`
Receive BLE device data from gateway app.

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

Set the gateway endpoint URL in your Android BLE scanning app. The server displays both local and public IP addresses on startup.

**For local network (same WiFi):**
```
http://LOCAL_IP:8080/api/ble
```

**For internet access (requires port forwarding):**
```
http://PUBLIC_IP:8080/api/ble
```

The app should POST JSON arrays of device objects to this endpoint.

## Troubleshooting

### Server won't start
- Check if port 8080 is already in use
- Verify Python 3.7+ is installed
- Ensure Flask is installed: `pip install flask`

### No data appearing
- Verify Android app is configured with correct IP address
- Check firewall allows connections on port 8080
- View logs: `tail -f ble_gateway.log`

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
