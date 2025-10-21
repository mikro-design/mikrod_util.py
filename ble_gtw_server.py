#!/usr/bin/env python3
"""
BLE Gateway Server - Receives BLE device data from the Android app via MQTT or HTTP
"""
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import json
import sqlite3
import re
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading

app = Flask(__name__)

# Database file
DB_FILE = 'ble_gateway.db'
CONNECTION_ID_FILE = 'connection_id.txt'  # Stores the unique connection ID

# MQTT Configuration (HiveMQ Cloud or any MQTT broker)
MQTT_BROKER = "broker.hivemq.com"  # Free HiveMQ public broker
MQTT_PORT = 1883  # TCP port for Python client
MQTT_WEBSOCKET_PORT = 8000  # WebSocket port for React Native app
# For HiveMQ Cloud with authentication, set these:
MQTT_USERNAME = None  # Set to your username if using HiveMQ Cloud
MQTT_PASSWORD = None  # Set to your password if using HiveMQ Cloud
MQTT_USE_TLS = False  # Set to True if using HiveMQ Cloud

# Connection ID will be loaded/generated at startup
MQTT_CONNECTION_ID = None
MQTT_TOPIC = None
MQTT_CLIENT_ID = None

mqtt_client = None

# Store received data in memory
latest_data = {
    'devices': [],
    'timestamp': None,
    'count': 0
}

# Server just stores raw data - plotting tool handles sensor detection

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
            <code>https://YOUR_PC_IP:8443/api/ble</code>
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


# Sensor detection removed - plotting tool handles this
# Server just stores raw data


def save_to_database(device_id, device_name, rssi, advertising_data):
    """Save device reading to database (raw data only)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # Insert device reading
        cursor.execute('''
            INSERT INTO device_readings (device_id, device_name, rssi, raw_data)
            VALUES (?, ?, ?, ?)
        ''', (device_id, device_name, rssi, json.dumps(advertising_data)))

        conn.commit()

        # Log database write
        logger.debug(f"Saved to DB: {device_name} ({device_id})")

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


def process_ble_data(data, source="HTTP"):
    """Process BLE device data from any source (HTTP or MQTT)"""
    try:
        if not data:
            logger.warning(f"Received empty data from {source}")
            return {'error': 'No data received'}, 400

        # Update stored data
        latest_data['devices'] = data
        latest_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        latest_data['count'] = len(data)

        # Log incoming data
        logger.info("=" * 60)
        logger.info(f"📡 INCOMING DATA ({source}) - {len(data)} device(s)")
        logger.info("=" * 60)

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

            # Save to database (raw data only)
            save_to_database(device_id, device_name, rssi, advertising)

            logger.info("")  # Blank line between devices

        # Summary
        logger.info(f"✓ Successfully processed {len(data)} device(s)")
        logger.info("=" * 60)

        return {
            'status': 'success',
            'received': len(data),
            'timestamp': latest_data['timestamp']
        }, 200

    except Exception as e:
        logger.error(f"❌ Error processing data from {source}: {str(e)}", exc_info=True)
        return {'error': str(e)}, 500


def on_mqtt_connect(client, userdata, flags, rc):
    """Callback when MQTT client connects to broker"""
    if rc == 0:
        logger.info(f"✓ Connected to MQTT broker: {MQTT_BROKER}")
        client.subscribe(MQTT_TOPIC)
        logger.info(f"✓ Subscribed to topic: {MQTT_TOPIC}")
        logger.info(f"  (1:1 private connection)")
    else:
        logger.error(f"❌ Failed to connect to MQTT broker, return code: {rc}")


def on_mqtt_message(client, userdata, msg):
    """Callback when MQTT message is received"""
    try:
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)

        # Process the data (same as HTTP endpoint)
        if isinstance(data, list):
            process_ble_data(data, source="MQTT")
        else:
            logger.warning(f"MQTT message is not a list: {type(data)}")
    except json.JSONDecodeError as e:
        logger.error(f"❌ Invalid JSON in MQTT message: {e}")
    except Exception as e:
        logger.error(f"❌ Error processing MQTT message: {e}", exc_info=True)


def on_mqtt_disconnect(client, userdata, rc):
    """Callback when MQTT client disconnects"""
    if rc != 0:
        logger.warning(f"⚠️  Unexpected MQTT disconnection. Attempting to reconnect...")


def setup_mqtt():
    """Setup and start MQTT client"""
    global mqtt_client

    try:
        import paho.mqtt.client as mqtt

        # Support both paho-mqtt v1.x and v2.0
        try:
            # Try v2.0 style (with callback_api_version)
            mqtt_client = mqtt.Client(
                client_id=MQTT_CLIENT_ID,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1
            )
        except (AttributeError, TypeError):
            # Fallback to v1.x style
            mqtt_client = mqtt.Client(MQTT_CLIENT_ID)

        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.on_disconnect = on_mqtt_disconnect

        # Set username and password if provided
        if MQTT_USERNAME and MQTT_PASSWORD:
            mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        # Enable TLS if required
        if MQTT_USE_TLS:
            mqtt_client.tls_set()

        logger.info(f"Connecting to MQTT broker: {MQTT_BROKER}:{MQTT_PORT}")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)

        # Start the MQTT loop in a separate thread
        mqtt_thread = threading.Thread(target=mqtt_client.loop_forever, daemon=True)
        mqtt_thread.start()

        return True

    except ImportError:
        logger.warning("⚠️  paho-mqtt not installed. MQTT support disabled.")
        logger.warning("   Install with: pip install paho-mqtt")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to setup MQTT: {e}")
        return False


@app.route('/api/ble', methods=['POST'])
def receive_ble_data():
    """Receive BLE device data from the gateway via HTTP"""
    try:
        data = request.get_json()
        result, status_code = process_ble_data(data, source="HTTP")
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"❌ Error in HTTP endpoint: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get the latest device data as JSON"""
    return jsonify(latest_data)


def generate_ssl_certificate():
    """Generate self-signed SSL certificate if it doesn't exist"""
    cert_file = Path('cert.pem')
    key_file = Path('key.pem')

    if cert_file.exists() and key_file.exists():
        logger.info("SSL certificates found")
        return str(cert_file), str(key_file)

    logger.info("Generating self-signed SSL certificate...")

    try:
        # Try using cryptography library (more portable)
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        import datetime

        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )

        # Create certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"BLE Gateway Server"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"BLE-Gateway"),
        ])

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=365)
        ).sign(private_key, hashes.SHA256())

        # Write private key
        with open(key_file, 'wb') as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        # Write certificate
        with open(cert_file, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        logger.info(f"✓ SSL certificate generated: {cert_file.absolute()}")
        logger.info(f"✓ SSL key generated: {key_file.absolute()}")

    except ImportError:
        # Fallback to openssl command
        logger.info("cryptography library not found, using openssl command...")
        import subprocess

        result = subprocess.run([
            'openssl', 'req', '-x509', '-newkey', 'rsa:4096',
            '-nodes', '-out', str(cert_file), '-keyout', str(key_file),
            '-days', '365',
            '-subj', '/CN=BLE-Gateway/O=BLE Gateway Server/C=US'
        ], capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"Failed to generate certificate: {result.stderr}")

        logger.info(f"✓ SSL certificate generated: {cert_file.absolute()}")
        logger.info(f"✓ SSL key generated: {key_file.absolute()}")

    return str(cert_file), str(key_file)


def generate_new_connection_id():
    """Generate a fresh connection ID on every server start"""
    global MQTT_CONNECTION_ID, MQTT_TOPIC, MQTT_CLIENT_ID

    import secrets
    import time

    # Generate new connection ID with timestamp for uniqueness (8 chars + timestamp hash)
    random_part = secrets.token_urlsafe(6)  # ~8 chars
    timestamp_part = hex(int(time.time()))[2:6]  # 4 hex chars from timestamp
    MQTT_CONNECTION_ID = f"{random_part}{timestamp_part}"

    logger.info(f"🔄 Generated NEW connection ID: {MQTT_CONNECTION_ID}")
    logger.info(f"   Fresh MQTT topic created - old connections are now invalid")

    # Set topic and client ID
    MQTT_TOPIC = f"mikrodesign/ble_scan/{MQTT_CONNECTION_ID}"
    MQTT_CLIENT_ID = f"ble_gtw_{MQTT_CONNECTION_ID}"

    # Save to file for reference only (not used for loading)
    conn_id_path = Path(CONNECTION_ID_FILE)
    with open(conn_id_path, 'w') as f:
        f.write(f"{MQTT_CONNECTION_ID}\n")
        f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Topic: {MQTT_TOPIC}\n")

    return MQTT_CONNECTION_ID


if __name__ == '__main__':
    import socket
    import urllib.request

    # Initialize database
    logger.info("Initializing database...")
    init_database()
    logger.info(f"Database: {Path(DB_FILE).absolute()}")
    logger.info(f"Log file: {Path('ble_gateway.log').absolute()}")

    # Generate fresh connection ID for this session
    connection_id = generate_new_connection_id()

    # Generate or check SSL certificates
    cert_file, key_file = generate_ssl_certificate()

    # Get local IP address (actual network IP, not loopback)
    try:
        # Create a socket to determine which interface would be used to reach the internet
        # This doesn't actually send any data
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        # Fallback to hostname method
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)

    # Get public IP address
    public_ip = None
    try:
        logger.info("Fetching public IP address...")
        with urllib.request.urlopen('https://api.ipify.org', timeout=5) as response:
            public_ip = response.read().decode('utf-8')
        logger.info(f"Public IP: {public_ip}")
    except Exception as e:
        logger.warning(f"Could not fetch public IP: {e}")
        public_ip = "Unable to fetch"

    # Setup MQTT
    mqtt_enabled = setup_mqtt()

    print("\n" + "=" * 60)
    print("🚀 BLE Gateway Server Starting...")
    print("=" * 60)

    # MQTT Configuration
    print(f"\n📬 MQTT Configuration:")
    if mqtt_enabled:
        print(f"   ✓ MQTT Enabled")
        print(f"   Broker: {MQTT_BROKER}:{MQTT_PORT} (Server)")
        print(f"   App Port: {MQTT_WEBSOCKET_PORT} (WebSocket)")
        print(f"   Connection ID: {connection_id}")
        print(f"   Topic: {MQTT_TOPIC}")
        if MQTT_USE_TLS:
            print(f"   TLS: Enabled")
        print(f"\n   🔒 This is a 1:1 private connection")
        print(f"   🔄 Fresh connection ID generated on each restart")
        print(f"   💡 Scan the NEW QR code to reconnect your phone")

        # Generate QR code with MQTT configuration
        import qrcode

        # Create configuration JSON for Android app
        mqtt_config = {
            "broker": MQTT_BROKER,
            "port": MQTT_WEBSOCKET_PORT,  # Use WebSocket port for React Native app
            "topic": MQTT_TOPIC,
            "connection_id": connection_id,
            "tls": MQTT_USE_TLS
        }
        if MQTT_USERNAME:
            mqtt_config["username"] = MQTT_USERNAME
        if MQTT_PASSWORD:
            mqtt_config["password"] = MQTT_PASSWORD

        config_json = json.dumps(mqtt_config)

        # Generate QR code
        qr = qrcode.QRCode(border=1)
        qr.add_data(config_json)
        qr.make()

        print(f"\n   📱 Scan this QR code with your Android app:")
        print()
        qr.print_ascii(invert=True)
        print()
        print(f"   ✓ Instant 1:1 connection setup!")

        print(f"\n   📱 Or configure manually:")
        print(f"      Broker: {MQTT_BROKER}")
        print(f"      Port: {MQTT_WEBSOCKET_PORT} (WebSocket)")
        print(f"      Topic: {MQTT_TOPIC}")
    else:
        print(f"   ✗ MQTT Disabled (paho-mqtt not installed)")
        print(f"   Install with: pip install paho-mqtt")

    print(f"\n🌐 Network Information:")
    print(f"   Local IP:  {local_ip}")
    print(f"   Public IP: {public_ip}")
    print("\n📊 Web Interface:")
    print(f"   Local:  https://{local_ip}:8443")
    if public_ip and public_ip != "Unable to fetch":
        print(f"   Public: https://{public_ip}:8443")
    print("\n🔌 HTTP API Endpoint (optional fallback):")
    print(f"   Local network:  https://{local_ip}:8443/api/ble")
    if public_ip and public_ip != "Unable to fetch":
        print(f"   Internet:       https://{public_ip}:8443/api/ble")
        print("   (Requires port forwarding if accessing from internet)")
    print("\n🔒 Security:")
    print(f"   Using self-signed certificate for HTTPS")
    print(f"   ⚠️  You'll need to accept security warnings or install cert on Android")
    print("=" * 60)
    print(f"📝 Logging to: ble_gateway.log")
    print("💾 Database:   ble_gateway.db")
    print("=" * 60)
    print("\nPress Ctrl+C to stop\n")

    logger.info("Server started successfully")

    # Disable Flask's default logging to avoid duplicates
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)

    # Run with HTTPS using SSL context
    import ssl
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert_file, key_file)

    app.run(host='0.0.0.0', port=8443, ssl_context=ssl_context, debug=False)
