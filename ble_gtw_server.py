#!/usr/bin/env python3
"""
BLE Gateway Server - Receives BLE device data from the Android app
"""
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import json
import sqlite3
import re
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

app = Flask(__name__)

# Database file
DB_FILE = 'ble_gateway.db'

# Store received data in memory
latest_data = {
    'devices': [],
    'timestamp': None,
    'count': 0
}

# SI Unit field mappings (field name patterns -> unit)
SENSOR_PATTERNS = {
    'temperature|temp|t(?!ime)': {'unit': '°C', 'type': 'temperature'},
    'humidity|hum|rh': {'unit': '%', 'type': 'humidity'},
    'pressure|press|p(?!m)': {'unit': 'hPa', 'type': 'pressure'},
    'battery|bat': {'unit': '%', 'type': 'battery'},
    'voltage|volt|v': {'unit': 'V', 'type': 'voltage'},
    'current|i': {'unit': 'A', 'type': 'current'},
    'light|lux|illuminance': {'unit': 'lux', 'type': 'light'},
    'co2': {'unit': 'ppm', 'type': 'co2'},
    'voc': {'unit': 'ppb', 'type': 'voc'},
    'pm2\.?5|pm25': {'unit': 'µg/m³', 'type': 'pm25'},
    'pm10': {'unit': 'µg/m³', 'type': 'pm10'},
}

# HTML template for viewing the data
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>BLE Gateway Monitor</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }
        .header {
            background-color: #007AFF;
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .stats {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }
        .stat-box {
            background: white;
            padding: 15px;
            border-radius: 8px;
            flex: 1;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            color: #007AFF;
        }
        .stat-label {
            color: #666;
            margin-top: 5px;
        }
        .device {
            background: white;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .device-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .device-name {
            font-size: 18px;
            font-weight: bold;
        }
        .rssi {
            padding: 5px 10px;
            border-radius: 4px;
            color: white;
            font-weight: bold;
        }
        .rssi-good { background-color: #34C759; }
        .rssi-medium { background-color: #FF9500; }
        .rssi-bad { background-color: #FF3B30; }
        .device-id {
            font-family: monospace;
            color: #666;
            font-size: 12px;
        }
        .advertising-data {
            margin-top: 10px;
            padding: 10px;
            background-color: #f5f5f5;
            border-radius: 4px;
            font-size: 12px;
        }
        .no-data {
            text-align: center;
            padding: 40px;
            color: #999;
        }
        pre {
            margin: 0;
            overflow-x: auto;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>BLE Gateway Monitor</h1>
        <p>Auto-refreshes every 5 seconds</p>
    </div>

    <div class="stats">
        <div class="stat-box">
            <div class="stat-value">{{ device_count }}</div>
            <div class="stat-label">Active Devices</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{{ last_update }}</div>
            <div class="stat-label">Last Update</div>
        </div>
    </div>

    {% if devices %}
        {% for device in devices %}
        <div class="device">
            <div class="device-header">
                <div>
                    <div class="device-name">{{ device.name or 'Unknown Device' }}</div>
                    <div class="device-id">{{ device.id }}</div>
                </div>
                <span class="rssi {% if device.rssi > -70 %}rssi-good{% elif device.rssi > -85 %}rssi-medium{% else %}rssi-bad{% endif %}">
                    {{ device.rssi }} dBm
                </span>
            </div>
            {% if device.advertising %}
            <div class="advertising-data">
                <strong>Advertising Data:</strong>
                <pre>{{ device.advertising | tojson(indent=2) }}</pre>
            </div>
            {% endif %}
        </div>
        {% endfor %}
    {% else %}
        <div class="no-data">
            <h2>No devices received yet</h2>
            <p>Waiting for data from BLE Gateway...</p>
            <p>Make sure Gateway Mode is enabled on the app and the endpoint URL is set to:</p>
            <code>http://YOUR_PC_IP:8080/api/ble</code>
        </div>
    {% endif %}
</body>
</html>
"""


def setup_logging():
    """Configure logging to both file and console"""
    # Create logger
    logger = logging.getLogger('ble_gateway')
    logger.setLevel(logging.DEBUG)

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_formatter = logging.Formatter(
        '%(asctime)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # File handler (rotating, max 10MB, keep 5 backups)
    file_handler = RotatingFileHandler(
        'ble_gateway.log',
        maxBytes=10*1024*1024,
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Initialize logger
logger = setup_logging()


def init_database():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Main device readings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS device_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            device_id TEXT NOT NULL,
            device_name TEXT,
            rssi INTEGER,
            raw_data TEXT
        )
    ''')

    # Sensor data table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reading_id INTEGER,
            sensor_type TEXT NOT NULL,
            sensor_value REAL NOT NULL,
            unit TEXT,
            FOREIGN KEY (reading_id) REFERENCES device_readings(id)
        )
    ''')

    # Create indices for faster queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_device_timestamp
        ON device_readings(device_id, timestamp)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_sensor_type
        ON sensor_data(sensor_type, id)
    ''')

    conn.commit()
    conn.close()


def detect_sensors(data):
    """
    Detect sensor fields in JSON data and extract values with units
    Returns: list of dict with {type, value, unit, field_name}
    """
    sensors = []

    def scan_dict(obj, prefix=''):
        """Recursively scan dictionary for sensor fields"""
        if not isinstance(obj, dict):
            return

        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key

            # Skip non-numeric values
            if not isinstance(value, (int, float)):
                if isinstance(value, dict):
                    scan_dict(value, full_key)
                continue

            # Check against sensor patterns
            key_lower = key.lower()
            for pattern, info in SENSOR_PATTERNS.items():
                if re.search(pattern, key_lower, re.IGNORECASE):
                    sensors.append({
                        'type': info['type'],
                        'value': float(value),
                        'unit': info['unit'],
                        'field_name': full_key
                    })
                    break

    scan_dict(data)
    return sensors


def save_to_database(device_id, device_name, rssi, advertising_data):
    """Save device reading and sensor data to database"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # Insert device reading
        cursor.execute('''
            INSERT INTO device_readings (device_id, device_name, rssi, raw_data)
            VALUES (?, ?, ?, ?)
        ''', (device_id, device_name, rssi, json.dumps(advertising_data)))

        reading_id = cursor.lastrowid

        # Detect and save sensor data
        sensors = detect_sensors(advertising_data)
        for sensor in sensors:
            cursor.execute('''
                INSERT INTO sensor_data (reading_id, sensor_type, sensor_value, unit)
                VALUES (?, ?, ?, ?)
            ''', (reading_id, sensor['type'], sensor['value'], sensor['unit']))

        conn.commit()

        # Log database write
        logger.debug(f"Saved to DB: {device_name} ({device_id}) - {len(sensors)} sensors")

        return sensors

    except Exception as e:
        conn.rollback()
        logger.error(f"Database error for {device_id}: {str(e)}")
        raise e
    finally:
        conn.close()


@app.route('/')
def index():
    """Display the latest BLE device data"""
    return render_template_string(
        HTML_TEMPLATE,
        devices=latest_data['devices'],
        device_count=latest_data['count'],
        last_update=latest_data['timestamp'] or 'Never'
    )


@app.route('/api/ble', methods=['POST'])
def receive_ble_data():
    """Receive BLE device data from the gateway"""
    try:
        data = request.get_json()

        if not data:
            logger.warning("Received empty request")
            return jsonify({'error': 'No data received'}), 400

        # Update stored data
        latest_data['devices'] = data
        latest_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        latest_data['count'] = len(data)

        # Log incoming data
        logger.info("=" * 60)
        logger.info(f"📡 INCOMING DATA - {len(data)} device(s)")
        logger.info("=" * 60)

        total_sensors = 0
        for idx, device in enumerate(data, 1):
            device_id = device.get('id', 'unknown')
            device_name = device.get('name', 'Unknown')
            rssi = device.get('rssi', 0)
            advertising = device.get('advertising', {})

            # Log device info
            logger.info(f"Device {idx}/{len(data)}: {device_name}")
            logger.info(f"  ID: {device_id}")
            logger.info(f"  RSSI: {rssi} dBm {'📶' if rssi > -70 else '📡' if rssi > -85 else '📉'}")

            # Log raw advertising data if present
            if advertising:
                logger.debug(f"  Raw advertising data: {json.dumps(advertising, indent=2)}")

            # Save to database and detect sensors
            sensors = save_to_database(device_id, device_name, rssi, advertising)

            # Log detected sensors
            if sensors:
                logger.info(f"  Sensors detected: {len(sensors)}")
                for sensor in sensors:
                    logger.info(f"    • {sensor['type']}: {sensor['value']} {sensor['unit']} (from field: {sensor['field_name']})")
                total_sensors += len(sensors)
            else:
                logger.info("  No sensors detected in advertising data")

            logger.info("")  # Blank line between devices

        # Summary
        logger.info(f"✓ Successfully processed {len(data)} device(s), {total_sensors} total sensor reading(s)")
        logger.info("=" * 60)

        return jsonify({
            'status': 'success',
            'received': len(data),
            'sensors_detected': total_sensors,
            'timestamp': latest_data['timestamp']
        }), 200

    except Exception as e:
        logger.error(f"❌ Error processing data: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get the latest device data as JSON"""
    return jsonify(latest_data)


if __name__ == '__main__':
    import socket

    # Initialize database
    logger.info("Initializing database...")
    init_database()
    logger.info(f"Database: {Path(DB_FILE).absolute()}")
    logger.info(f"Log file: {Path('ble_gateway.log').absolute()}")

    # Get local IP address
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    print("\n" + "=" * 60)
    print("🚀 BLE Gateway Server Starting...")
    print("=" * 60)
    print(f"\nLocal IP: {local_ip}")
    print(f"\n📊 Web Interface: http://{local_ip}:8080")
    print(f"🔌 API Endpoint:  http://{local_ip}:8080/api/ble")
    print("\nSet this URL in your Android app's Gateway Mode configuration")
    print("=" * 60)
    print(f"\n📡 Supported sensor types:")
    sensor_types = sorted(set(v['type'] for v in SENSOR_PATTERNS.values()))
    for i in range(0, len(sensor_types), 4):
        print(f"   {', '.join(sensor_types[i:i+4])}")
    print("=" * 60)
    print(f"📝 Logging to: ble_gateway.log")
    print("💾 Database:   ble_gateway.db")
    print("=" * 60)
    print("\nPress Ctrl+C to stop\n")

    logger.info("Server started successfully")

    # Disable Flask's default logging to avoid duplicates
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)

    app.run(host='0.0.0.0', port=8080, debug=False)
