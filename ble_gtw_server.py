#!/usr/bin/env python3
"""
BLE Gateway Server - Receives BLE device data from the Android app via MQTT or HTTP
"""
from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import base64
import binascii
import struct
import copy
import json
import sqlite3
import re
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading
import os
import time
import queue
import secrets
from functools import wraps

app = Flask(__name__)

# Configure rate limiting if flask-limiter is available
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    # Initialize rate limiter
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per hour"],  # Global default
        storage_uri="memory://",  # Use in-memory storage (for SQLite use: "sqlite:///rate_limit.db")
        strategy="fixed-window"
    )
    logger_early = logging.getLogger('ble_gateway')
    if logger_early.hasHandlers():
        logger_early.info("✓ Rate limiting enabled")
except ImportError:
    limiter = None  # Rate limiting not available

# Configure CORS if flask-cors is available
try:
    from flask_cors import CORS
    # Allow CORS for API endpoints only
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",  # In production, specify allowed origins
            "methods": ["GET", "POST"],
            "allow_headers": ["Content-Type", "Authorization", "X-API-Key"]
        },
        r"/health": {
            "origins": "*",
            "methods": ["GET"]
        }
    })
    logger_early = logging.getLogger('ble_gateway')
    if logger_early.hasHandlers():
        logger_early.info("✓ CORS enabled for API endpoints")
except ImportError:
    pass  # CORS not available, will work without it

# ============================================================================
# AUTHENTICATION CONFIGURATION
# ============================================================================

# Load API key from environment or generate one
API_KEY = os.environ.get('BLE_GATEWAY_API_KEY')

if not API_KEY:
    # Generate a secure random API key on first run
    API_KEY = secrets.token_urlsafe(32)

# Optional: Allow disabling auth for local testing
AUTH_ENABLED = os.environ.get('BLE_GATEWAY_AUTH_ENABLED', 'true').lower() == 'true'

def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in ('1', 'true', 'yes', 'y')

# Require API key in MQTT payloads when auth is enabled (can be overridden)
MQTT_REQUIRE_API_KEY = _env_flag('BLE_GATEWAY_MQTT_REQUIRE_API_KEY', default=AUTH_ENABLED)
LOG_COMPACT = _env_flag('BLE_GATEWAY_LOG_COMPACT', default=False)


def require_api_key(f):
    """
    Decorator to require API key authentication.
    Checks for key in:
    1. Authorization header: 'Bearer <api_key>'
    2. X-API-Key header: '<api_key>'
    3. Query parameter: ?api_key=<api_key>
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AUTH_ENABLED:
            return f(*args, **kwargs)

        # Check Authorization header (Bearer token)
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header[7:]  # Remove 'Bearer ' prefix
            if token == API_KEY:
                return f(*args, **kwargs)

        # Check X-API-Key header
        api_key_header = request.headers.get('X-API-Key')
        if api_key_header == API_KEY:
            return f(*args, **kwargs)

        # Check query parameter (less secure, but convenient for testing)
        query_key = request.args.get('api_key')
        if query_key == API_KEY:
            return f(*args, **kwargs)

        # No valid key found
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        # Use logger after it's initialized (will be set up later)
        try:
            logger.warning(f"Unauthorized access attempt from {client_ip}")
        except NameError:
            pass  # Logger not yet initialized

        return jsonify({
            'error': 'Unauthorized',
            'message': 'Valid API key required. Use Authorization: Bearer <key> or X-API-Key: <key> header.'
        }), 401

    return decorated_function

# ============================================================================

# Database file
DB_FILE = 'ble_gateway.db'
CONNECTION_ID_FILE = 'connection_id.txt'  # Stores the unique connection ID

# JSON Schema for input validation
BLE_DEVICE_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "maxItems": 100,  # Prevent large payloads
    "items": {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {
                "type": "string",
                "pattern": "^[A-Fa-f0-9:]{17}$|^[A-Fa-f0-9]{12}$",  # MAC address format
                "maxLength": 50
            },
            "name": {
                "type": ["string", "null"],
                "maxLength": 100
            },
            "rssi": {
                "type": "integer",
                "minimum": -120,
                "maximum": 0
            },
            "advertising": {
                "type": ["object", "null"]
            }
        }
    }
}


def validate_ble_data(data):
    """
    Validate BLE device data against schema.
    Returns (is_valid, error_message)
    """
    try:
        import jsonschema
        jsonschema.validate(instance=data, schema=BLE_DEVICE_SCHEMA)
        return True, None
    except jsonschema.exceptions.ValidationError as e:
        return False, f"Validation error: {e.message}"
    except jsonschema.exceptions.SchemaError as e:
        logger.error(f"Schema error: {e}")
        return False, "Internal validation error"
    except ImportError:
        # jsonschema not installed, do basic validation
        if not isinstance(data, list):
            return False, "Data must be an array"
        if len(data) == 0:
            return False, "Data array cannot be empty"
        if len(data) > 100:
            return False, "Too many devices (max 100)"
        for device in data:
            if not isinstance(device, dict):
                return False, "Each device must be an object"
            if 'id' not in device:
                return False, "Each device must have an 'id' field"
            if not isinstance(device.get('id'), str):
                return False, "Device 'id' must be a string"
            if len(device.get('id', '')) > 50:
                return False, "Device 'id' too long"
        return True, None

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
MQTT_QUEUE_MAXSIZE = 1000
MQTT_WORKER_LOG_INTERVAL = 10  # seconds
MQTT_WORKER_ENABLED = True
mqtt_queue = queue.Queue(maxsize=MQTT_QUEUE_MAXSIZE)
mqtt_worker_thread = None
MQTT_STATS = {
    'messages': 0,
    'devices': 0,
    'last_log': time.time(),
}

# Thread coordination
DB_WRITE_LOCK = threading.Lock()
LATEST_DATA_LOCK = threading.Lock()

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
    logger.propagate = False

    # Avoid adding duplicate handlers on reload/import
    if logger.handlers:
        return logger

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


def get_db_connection():
    """Create a configured SQLite connection"""
    conn = sqlite3.connect(DB_FILE, timeout=5)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except sqlite3.OperationalError:
        pass
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA busy_timeout=5000')
    return conn


def _json_default(value):
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def normalize_advertising_data(advertising_data):
    """Return (safe_obj, json_string) for advertising payloads"""
    if not advertising_data:
        return {}, "{}"
    try:
        advertising_json = json.dumps(advertising_data, default=_json_default)
        return json.loads(advertising_json), advertising_json
    except (TypeError, ValueError) as e:
        logger.warning(f"Failed to serialize advertising data: {e}")
        return {}, "{}"


def _coerce_advertising_json(advertising_data):
    if advertising_data is None:
        return "{}"
    if isinstance(advertising_data, str):
        return advertising_data
    return json.dumps(advertising_data, default=_json_default)


def _extract_path_value(data, field_path):
    """Extract a nested value using dot notation (e.g., 'manufacturerData.bytes.0')"""
    if not field_path:
        return None

    parts = field_path.split('.')
    current = data

    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return None
            if index < 0 or index >= len(current):
                return None
            current = current[index]
        else:
            return None

        if current is None:
            return None

    return current


def _coerce_bytes(value):
    """Normalize common BLE payload encodings into bytes."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, list):
        if all(isinstance(item, int) for item in value):
            return bytes(item & 0xFF for item in value)
        return None
    if isinstance(value, dict):
        for key in ('bytes', 'data', 'raw', 'value'):
            if key in value:
                return _coerce_bytes(value[key])
        return None
    if isinstance(value, str):
        text = value.strip()
        hex_text = text[2:] if text.lower().startswith('0x') else text
        if re.fullmatch(r'[0-9a-fA-F]+', hex_text) and len(hex_text) % 2 == 0:
            try:
                return bytes.fromhex(hex_text)
            except ValueError:
                pass
        try:
            return base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            try:
                return base64.b64decode(text)
            except (binascii.Error, ValueError):
                return None
    return None


def _decode_with_format(data_bytes, fmt, byte_offset=0):
    fmt_map = {
        'u8': ('B', 1),
        'i8': ('b', 1),
        'u16le': ('<H', 2),
        'u16be': ('>H', 2),
        'i16le': ('<h', 2),
        'i16be': ('>h', 2),
        'u32le': ('<I', 4),
        'u32be': ('>I', 4),
        'i32le': ('<i', 4),
        'i32be': ('>i', 4),
        'f32le': ('<f', 4),
        'f32be': ('>f', 4),
    }
    fmt_key = fmt.lower()
    if fmt_key not in fmt_map:
        logger.warning(f"Unknown selector format '{fmt}'")
        return None

    struct_fmt, size = fmt_map[fmt_key]
    if byte_offset < 0 or byte_offset + size > len(data_bytes):
        return None
    segment = data_bytes[byte_offset:byte_offset + size]
    return struct.unpack(struct_fmt, segment)[0]


def _decode_bytes(data_bytes, byte_offset=0, byte_length=None, endian='little', signed=False):
    if byte_length is None:
        return None
    if byte_offset < 0 or byte_length <= 0:
        return None
    end = byte_offset + byte_length
    if end > len(data_bytes):
        return None
    segment = data_bytes[byte_offset:end]
    byteorder = 'little' if str(endian).lower() != 'big' else 'big'
    return int.from_bytes(segment, byteorder=byteorder, signed=bool(signed))


def _coerce_number(value, default=None):
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_selector_value(advertising_data, selector):
    raw_value = _extract_path_value(advertising_data, selector.get('path'))
    if raw_value is None:
        return None

    value = None
    if isinstance(raw_value, (int, float)):
        value = raw_value
    else:
        raw_bytes = _coerce_bytes(raw_value)
        if raw_bytes is None:
            return None
        byte_offset = selector.get('byte_offset', selector.get('offset', 0))
        fmt = selector.get('format')
        if fmt:
            value = _decode_with_format(raw_bytes, fmt, byte_offset=byte_offset)
        else:
            byte_length = selector.get('byte_length', selector.get('length'))
            endian = selector.get('endian', 'little')
            signed = selector.get('signed', False)
            value = _decode_bytes(
                raw_bytes,
                byte_offset=byte_offset,
                byte_length=byte_length,
                endian=endian,
                signed=signed
            )

    if value is None:
        return None

    scale = _coerce_number(selector.get('scale', 1), default=1)
    value_offset = _coerce_number(selector.get('value_offset', selector.get('add', 0)), default=0)
    try:
        return (value * scale) + value_offset
    except TypeError:
        return None


def _normalize_selectors(selectors):
    normalized = []
    for idx, selector in enumerate(selectors):
        if not isinstance(selector, dict):
            logger.warning(f"Ignoring selector {idx}: not an object")
            continue
        sensor_type = selector.get('sensor_type') or selector.get('sensor')
        unit = selector.get('unit')
        path = selector.get('path') or selector.get('field')
        if not sensor_type or not unit or not path:
            logger.warning(f"Ignoring selector {idx}: missing sensor_type, unit, or path")
            continue
        normalized.append({
            'sensor_type': sensor_type,
            'unit': unit,
            'path': path,
            'format': selector.get('format'),
            'byte_offset': selector.get('byte_offset', selector.get('offset', 0)),
            'byte_length': selector.get('byte_length', selector.get('length')),
            'endian': selector.get('endian', 'little'),
            'signed': selector.get('signed', False),
            'scale': selector.get('scale', 1),
            'value_offset': selector.get('value_offset', selector.get('add', 0))
        })
    return normalized


def load_sensor_selectors():
    selectors = []

    raw_env = os.environ.get('BLE_GATEWAY_SENSOR_SELECTORS')
    if raw_env:
        try:
            env_payload = json.loads(raw_env)
            if isinstance(env_payload, dict):
                env_payload = env_payload.get('selectors', [])
            if isinstance(env_payload, list):
                selectors.extend(env_payload)
            else:
                logger.warning("BLE_GATEWAY_SENSOR_SELECTORS must be a JSON array or object with 'selectors'")
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid BLE_GATEWAY_SENSOR_SELECTORS JSON: {e}")

    file_path = os.environ.get('BLE_GATEWAY_SENSOR_SELECTORS_FILE')
    if not file_path:
        default_path = Path.cwd() / 'sensor_selectors.json'
        if default_path.exists():
            file_path = str(default_path)
    if file_path:
        try:
            with open(file_path, 'r', encoding='utf-8') as handle:
                file_payload = json.load(handle)
            if isinstance(file_payload, dict):
                file_payload = file_payload.get('selectors', [])
            if isinstance(file_payload, list):
                selectors.extend(file_payload)
            else:
                logger.warning(f"{file_path} must be a JSON array or object with 'selectors'")
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load sensor selectors from {file_path}: {e}")

    return _normalize_selectors(selectors)


def get_latest_snapshot():
    """Return a deep copy of the latest data for thread-safe reads"""
    with LATEST_DATA_LOCK:
        return copy.deepcopy(latest_data)


def init_database():
    """Initialize SQLite database with required tables"""
    with DB_WRITE_LOCK:
        conn = get_db_connection()
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


# Sensor detection patterns (field name -> sensor type, unit)
SENSOR_PATTERNS = {
    # Temperature sensors
    'temp': ('temperature', '°C'),
    'temperature': ('temperature', '°C'),
    # Humidity
    'hum': ('humidity', '%'),
    'humidity': ('humidity', '%'),
    # Pressure
    'pressure': ('pressure', 'hPa'),
    'press': ('pressure', 'hPa'),
    # Battery
    'bat': ('battery', '%'),
    'battery': ('battery', '%'),
    'batt': ('battery', '%'),
    # Voltage
    'volt': ('voltage', 'V'),
    'voltage': ('voltage', 'V'),
    'vdd': ('voltage', 'V'),
    # Energy
    'energy': ('energy', 'nJ'),
    # Current
    'current': ('current', 'A'),
    'curr': ('current', 'A'),
    # Light
    'light': ('light', 'lux'),
    'lux': ('light', 'lux'),
    'illuminance': ('light', 'lux'),
    # Air quality
    'co2': ('co2', 'ppm'),
    'voc': ('voc', 'ppb'),
    'pm25': ('pm25', 'µg/m³'),
    'pm10': ('pm10', 'µg/m³'),
}

SENSOR_SELECTORS = load_sensor_selectors()


def get_supported_sensor_types():
    types = set(sensor_type for sensor_type, _ in SENSOR_PATTERNS.values())
    for selector in SENSOR_SELECTORS:
        sensor_type = selector.get('sensor_type')
        if sensor_type:
            types.add(sensor_type)
    return sorted(types)


def detect_sensors(advertising_data, path=''):
    """
    Recursively detect sensor values in advertising data.
    Returns list of (sensor_type, value, unit) tuples.
    """
    sensors = []

    if SENSOR_SELECTORS:
        for selector in SENSOR_SELECTORS:
            value = _extract_selector_value(advertising_data, selector)
            if value is None:
                continue
            sensors.append((selector['sensor_type'], value, selector['unit']))

    if isinstance(advertising_data, dict):
        for key, value in advertising_data.items():
            # Check if this field matches a sensor pattern
            key_lower = key.lower()
            if key_lower in SENSOR_PATTERNS and isinstance(value, (int, float)):
                sensor_type, unit = SENSOR_PATTERNS[key_lower]
                sensors.append((sensor_type, value, unit))
                logger.debug(f"  Detected sensor: {sensor_type}={value} {unit} (from field: {key})")
            # Recurse into nested dicts
            elif isinstance(value, dict):
                nested_path = f"{path}.{key}" if path else key
                sensors.extend(detect_sensors(value, nested_path))

    if not sensors:
        return sensors

    deduped = []
    seen = set()
    for sensor_type, value, unit in sensors:
        key = (sensor_type, value, unit)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((sensor_type, value, unit))

    return deduped


def _insert_device_reading(cursor, device_id, device_name, rssi, advertising_json, sensors=None):
    """Insert a device reading and any sensor values using an existing cursor"""
    cursor.execute('''
        INSERT INTO device_readings (device_id, device_name, rssi, raw_data)
        VALUES (?, ?, ?, ?)
    ''', (device_id, device_name, rssi, advertising_json))

    reading_id = cursor.lastrowid

    if sensors:
        rows = [
            (reading_id, sensor_type, sensor_value, unit)
            for sensor_type, sensor_value, unit in sensors
        ]
        cursor.executemany('''
            INSERT INTO sensor_data (reading_id, sensor_type, sensor_value, unit)
            VALUES (?, ?, ?, ?)
        ''', rows)
        logger.debug(f"Saved {len(sensors)} sensor readings for {device_name}")

    logger.debug(f"Saved to DB: {device_name} ({device_id})")


def save_to_database(device_id, device_name, rssi, advertising_data, sensors=None, cursor=None):
    """Save device reading and detected sensors to database"""
    advertising_json = _coerce_advertising_json(advertising_data)

    if cursor is not None:
        _insert_device_reading(cursor, device_id, device_name, rssi, advertising_json, sensors)
        return

    with DB_WRITE_LOCK:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            _insert_device_reading(cursor, device_id, device_name, rssi, advertising_json, sensors)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error for {device_id}: {str(e)}")
            raise e
        finally:
            conn.close()


@app.route('/')
def index():
    """Display the latest BLE device data"""
    snapshot = get_latest_snapshot()
    return render_template_string(
        HTML_TEMPLATE,
        devices=snapshot['devices'],
        device_count=snapshot['count'],
        last_update=snapshot['timestamp'] or 'Never'
    )


def process_ble_data(data, source="HTTP", sent_at=None):
    """Process BLE device data from any source (HTTP or MQTT)"""
    try:
        if not data:
            logger.warning(f"Received empty data from {source}")
            return {'error': 'No data received'}, 400

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Log incoming data
        if LOG_COMPACT:
            logger.info(f"📡 {source} data: {len(data)} device(s)")
        else:
            logger.info("=" * 60)
            logger.info(f"📡 INCOMING DATA ({source}) - {len(data)} device(s)")
            if sent_at:
                logger.info(f"📤 Sent at: {sent_at}")
            logger.info("=" * 60)

        total_sensors = 0
        processed_devices = []

        for idx, device in enumerate(data, 1):
            device_id = device.get('id', 'unknown')
            device_name = device.get('name')
            device_name_display = device_name or 'Unknown'
            rssi = device.get('rssi', 0)
            ts_ms = device.get('ts_ms', 0)
            advertising = device.get('advertising', {})

            advertising_safe, advertising_json = normalize_advertising_data(advertising)
            sensors = detect_sensors(advertising_safe) if advertising_safe else []

            # Log device info
            rssi_icon = '📶' if rssi > -70 else '📡' if rssi > -85 else '📉'
            # Calculate device data age
            if ts_ms > 0:
                device_time = datetime.fromtimestamp(ts_ms / 1000)
                now_time = datetime.now()
                age_seconds = (now_time - device_time).total_seconds()
                age_str = f" (scanned {age_seconds:.1f}s ago)"
            else:
                age_str = ""

            if LOG_COMPACT:
                logger.info(
                    f"- {device_id} name={device_name_display} rssi={rssi} dBm {rssi_icon} "
                    f"sensors={len(sensors)}{age_str}"
                )
            else:
                logger.info(f"Device {idx}/{len(data)}: {device_name_display}")
                logger.info(f"  ID: {device_id}")
                logger.info(f"  RSSI: {rssi} dBm {rssi_icon}{age_str}")

            if sensors:
                total_sensors += len(sensors)
                if not LOG_COMPACT:
                    logger.info(f"  Sensors detected: {len(sensors)}")
                    for sensor_type, sensor_value, unit in sensors:
                        logger.info(f"    • {sensor_type}: {sensor_value} {unit}")

            # Log raw advertising data if present (debug level)
            if advertising_safe:
                logger.debug(f"  Raw advertising data: {json.dumps(advertising_safe, indent=2)}")

            device_snapshot = dict(device)
            device_snapshot['advertising'] = advertising_safe
            processed_devices.append({
                'device_id': device_id,
                'device_name': device_name,
                'rssi': rssi,
                'advertising_json': advertising_json,
                'sensors': sensors,
                'snapshot': device_snapshot
            })

            if not LOG_COMPACT:
                logger.info("")  # Blank line between devices

        conn = None
        try:
            with DB_WRITE_LOCK:
                conn = get_db_connection()
                cursor = conn.cursor()
                for item in processed_devices:
                    save_to_database(
                        item['device_id'],
                        item['device_name'],
                        item['rssi'],
                        item['advertising_json'],
                        item['sensors'],
                        cursor=cursor
                    )
                conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error during batch save: {str(e)}")
            raise e
        finally:
            if conn:
                conn.close()

        with LATEST_DATA_LOCK:
            latest_data['devices'] = [item['snapshot'] for item in processed_devices]
            latest_data['timestamp'] = timestamp
            latest_data['count'] = len(processed_devices)

        # Summary
        if LOG_COMPACT:
            logger.info(f"✓ {source} processed {len(data)} device(s), {total_sensors} sensor reading(s)")
        else:
            logger.info(f"✓ Successfully processed {len(data)} device(s), {total_sensors} total sensor reading(s)")
            logger.info("=" * 60)

        return {
            'status': 'success',
            'received': len(data),
            'sensors_detected': total_sensors,
            'timestamp': timestamp
        }, 200

    except Exception as e:
        logger.error(f"❌ Error processing data from {source}: {str(e)}", exc_info=True)
        return {'error': 'Internal server error'}, 500


def on_mqtt_connect(client, userdata, flags, rc):
    """Callback when MQTT client connects to broker"""
    if rc == 0:
        # Subscribe with QoS 1 (at least once delivery)
        client.subscribe(MQTT_TOPIC, qos=1)
        logger.info(f"✓ MQTT connected: {MQTT_BROKER} (topic {MQTT_TOPIC}, QoS 1)")
    else:
        logger.error(f"MQTT connect failed (rc={rc})")


def on_mqtt_message(client, userdata, msg):
    """Callback when MQTT message is received"""
    try:
        payload = msg.payload.decode('utf-8')
        payload_obj = json.loads(payload)
        if MQTT_WORKER_ENABLED:
            try:
                mqtt_queue.put_nowait(payload_obj)
            except queue.Full:
                logger.warning("MQTT worker queue full; dropping message")
        else:
            # Fallback: process inline
            data = None
            api_key = None
            sent_at = None
            if isinstance(payload_obj, list):
                data = payload_obj
            elif isinstance(payload_obj, dict):
                data = payload_obj.get('data') or payload_obj.get('devices')
                api_key = payload_obj.get('api_key') or payload_obj.get('apiKey')
                sent_at = payload_obj.get('sent_at')

            if data is None:
                logger.warning("MQTT message missing device array payload")
                return

            if MQTT_REQUIRE_API_KEY and api_key != API_KEY:
                logger.warning("MQTT message missing or invalid api_key")
                return

            is_valid, error_msg = validate_ble_data(data)
            if not is_valid:
                logger.warning(f"MQTT validation failed: {error_msg}")
                return

            process_ble_data(data, source="MQTT", sent_at=sent_at)
    except json.JSONDecodeError as e:
        logger.error(f"❌ Invalid JSON in MQTT message: {e}")
    except Exception as e:
        logger.error(f"❌ Error processing MQTT message: {e}", exc_info=True)


def on_mqtt_disconnect(client, userdata, rc):
    """Callback when MQTT client disconnects"""
    if rc != 0:
        logger.warning(f"MQTT disconnected (rc={rc}); reconnecting")
        # paho-mqtt's loop_forever() automatically reconnects


def start_mqtt_worker():
    """Start background worker to process MQTT payloads off the network thread"""
    global mqtt_worker_thread

    if not MQTT_WORKER_ENABLED:
        return

    if mqtt_worker_thread and mqtt_worker_thread.is_alive():
        return

    def worker():
        while True:
            payload_obj = mqtt_queue.get()
            try:
                data = None
                api_key = None
                sent_at = None
                if isinstance(payload_obj, list):
                    data = payload_obj
                elif isinstance(payload_obj, dict):
                    data = payload_obj.get('data') or payload_obj.get('devices')
                    api_key = payload_obj.get('api_key') or payload_obj.get('apiKey')
                    sent_at = payload_obj.get('sent_at')

                if data is None:
                    logger.warning("MQTT worker: message missing device array payload")
                    continue

                if MQTT_REQUIRE_API_KEY and api_key != API_KEY:
                    logger.warning("MQTT worker: missing or invalid api_key")
                    continue

                is_valid, error_msg = validate_ble_data(data)
                if not is_valid:
                    logger.warning(f"MQTT worker validation failed: {error_msg}")
                    continue

                process_ble_data(data, source="MQTT(worker)", sent_at=sent_at)

                # Stats
                MQTT_STATS['messages'] += 1
                MQTT_STATS['devices'] += len(data)
                now = time.time()
                elapsed = now - MQTT_STATS['last_log']
                if elapsed >= MQTT_WORKER_LOG_INTERVAL:
                    msg_rate = MQTT_STATS['messages'] / elapsed
                    dev_rate = MQTT_STATS['devices'] / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"MQTT worker: {MQTT_STATS['messages']} msg "
                        f"({msg_rate:.2f}/s), {MQTT_STATS['devices']} devices "
                        f"({dev_rate:.2f}/s) | queue={mqtt_queue.qsize()}"
                    )
                    MQTT_STATS['messages'] = 0
                    MQTT_STATS['devices'] = 0
                    MQTT_STATS['last_log'] = now

                if mqtt_queue.qsize() > MQTT_QUEUE_MAXSIZE * 0.8:
                    logger.warning(
                        f"MQTT worker queue high water mark: {mqtt_queue.qsize()}/{MQTT_QUEUE_MAXSIZE}"
                    )
            except Exception as e:
                logger.error(f"MQTT worker error: {e}", exc_info=True)
            finally:
                mqtt_queue.task_done()

    mqtt_worker_thread = threading.Thread(target=worker, daemon=True)
    mqtt_worker_thread.start()
    logger.info("MQTT worker thread started")


def mqtt_is_available():
    try:
        import paho.mqtt.client as mqtt  # noqa: F401
    except ImportError:
        return False
    return True


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

        start_mqtt_worker()

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


def apply_rate_limit(limit_string):
    """Conditionally apply rate limiting decorator"""
    def decorator(f):
        if limiter:
            return limiter.limit(limit_string)(f)
        return f
    return decorator


@app.route('/api/ble', methods=['POST'])
@require_api_key
@apply_rate_limit("30 per minute")
def receive_ble_data():
    """Receive BLE device data from the gateway via HTTP"""
    try:
        # Check content type
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400

        # Parse JSON
        try:
            data = request.get_json()
        except Exception as e:
            logger.warning(f"Invalid JSON received: {e}")
            return jsonify({'error': 'Invalid JSON'}), 400

        # Validate input
        is_valid, error_msg = validate_ble_data(data)
        if not is_valid:
            logger.warning(f"Validation failed: {error_msg}")
            return jsonify({'error': error_msg}), 400

        # Process data
        result, status_code = process_ble_data(data, source="HTTP")
        return jsonify(result), status_code

    except Exception as e:
        # Log full error but return generic message to client
        logger.error(f"❌ Error in HTTP endpoint: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/devices', methods=['GET'])
@require_api_key
@apply_rate_limit("60 per minute")
def get_devices():
    """Get the latest device data as JSON"""
    return jsonify(get_latest_snapshot())


@app.route('/health', methods=['GET'])
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Check database connectivity
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM device_readings')
        reading_count = cursor.fetchone()[0]
        conn.close()
        db_status = 'healthy'
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = 'unhealthy'
        reading_count = 0

    # Check MQTT status
    mqtt_is_connected = False
    if mqtt_client:
        is_connected = getattr(mqtt_client, 'is_connected', None)
        mqtt_is_connected = is_connected() if callable(is_connected) else False
    mqtt_status = 'connected' if mqtt_is_connected else 'disconnected'

    health = {
        'status': 'healthy' if db_status == 'healthy' else 'degraded',
        'timestamp': datetime.now().isoformat(),
        'components': {
            'database': {
                'status': db_status,
                'readings_count': reading_count
            },
            'mqtt': {
                'status': mqtt_status
            }
        }
    }

    status_code = 200 if health['status'] == 'healthy' else 503
    return jsonify(health), status_code


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

        # Use timezone-aware datetime (fixes deprecated utcnow)
        now = datetime.datetime.now(datetime.timezone.utc)

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            now
        ).not_valid_after(
            now + datetime.timedelta(days=365)
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

        # Set secure file permissions
        import os
        os.chmod(key_file, 0o600)  # Private key: owner read/write only
        os.chmod(cert_file, 0o644)  # Certificate: owner rw, others read

        logger.info(f"✓ SSL certificate generated: {cert_file.absolute()}")
        logger.info(f"✓ SSL key generated: {key_file.absolute()}")
        logger.info(f"✓ Secure file permissions set")

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

        # Set secure file permissions
        import os
        os.chmod(key_file, 0o600)  # Private key: owner read/write only
        os.chmod(cert_file, 0o644)  # Certificate: owner rw, others read

        logger.info(f"✓ SSL certificate generated: {cert_file.absolute()}")
        logger.info(f"✓ SSL key generated: {key_file.absolute()}")
        logger.info(f"✓ Secure file permissions set")

    return str(cert_file), str(key_file)


def generate_new_connection_id():
    """Load existing connection ID or generate a new one if not found"""
    global MQTT_CONNECTION_ID, MQTT_TOPIC, MQTT_CLIENT_ID

    import secrets
    import time

    conn_id_path = Path(CONNECTION_ID_FILE)

    # Try to load existing connection ID from file
    if conn_id_path.exists():
        try:
            with open(conn_id_path, 'r') as f:
                stored_id = f.readline().strip()
                if stored_id and len(stored_id) > 0:
                    MQTT_CONNECTION_ID = stored_id
                    MQTT_TOPIC = f"mikrodesign/ble_scan/{MQTT_CONNECTION_ID}"
                    MQTT_CLIENT_ID = f"ble_gtw_{MQTT_CONNECTION_ID}"
                    logger.info(f"✓ Loaded existing connection ID: {MQTT_CONNECTION_ID}")
                    return MQTT_CONNECTION_ID
        except Exception as e:
            logger.warning(f"Failed to load connection ID from file: {e}, generating new one")

    # Generate new connection ID with timestamp for uniqueness (8 chars + timestamp hash)
    random_part = secrets.token_urlsafe(6)  # ~8 chars
    timestamp_part = hex(int(time.time()))[2:6]  # 4 hex chars from timestamp
    MQTT_CONNECTION_ID = f"{random_part}{timestamp_part}"

    # Set topic and client ID
    MQTT_TOPIC = f"mikrodesign/ble_scan/{MQTT_CONNECTION_ID}"
    MQTT_CLIENT_ID = f"ble_gtw_{MQTT_CONNECTION_ID}"

    # Save to file for persistence
    with open(conn_id_path, 'w') as f:
        f.write(f"{MQTT_CONNECTION_ID}\n")
        f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Topic: {MQTT_TOPIC}\n")

    logger.info(f"✓ Generated new connection ID: {MQTT_CONNECTION_ID}")

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

    mqtt_available = mqtt_is_available()

    print("\n" + "=" * 60)
    print("🚀 BLE Gateway Server Starting...")
    print("=" * 60)

    # MQTT Configuration
    print(f"\n📬 MQTT:")
    if mqtt_available:
        print(f"   Broker: {MQTT_BROKER}:{MQTT_PORT} (Server)")
        print(f"   App Port: {MQTT_WEBSOCKET_PORT} (WebSocket)")
        print(f"   Connection ID: {connection_id}")
        print(f"   Topic: {MQTT_TOPIC}")
        if MQTT_USE_TLS:
            print(f"   TLS: Enabled")

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
        if MQTT_REQUIRE_API_KEY:
            mqtt_config["api_key"] = API_KEY
        if MQTT_USERNAME:
            mqtt_config["username"] = MQTT_USERNAME
        if MQTT_PASSWORD:
            mqtt_config["password"] = MQTT_PASSWORD

        # Compact JSON + lower error correction keeps the ASCII QR smaller on screen.
        config_json = json.dumps(mqtt_config, separators=(',', ':'))

        # Generate QR code
        qr = qrcode.QRCode(
            border=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
        )
        qr.add_data(config_json)
        qr.make()

        print(f"\n   📱 QR:")
        qr.print_ascii(invert=True)
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

    # Show API key information
    print(f"\n🔐 API Authentication:")
    if AUTH_ENABLED:
        print(f"   ✓ Authentication ENABLED")
        # Show partial key for security (first 8 and last 8 chars)
        if len(API_KEY) > 16:
            masked_key = f"{API_KEY[:8]}...{API_KEY[-8:]}"
        else:
            masked_key = API_KEY[:4] + "..." + API_KEY[-4:]
        print(f"   API Key: {masked_key}")
        print(f"\n   📱 Configure your Android app:")
        print(f"      Header: Authorization: Bearer {API_KEY}")
        print(f"      Or: X-API-Key: {API_KEY}")
        print(f"\n   💡 To set a custom key:")
        print(f"      export BLE_GATEWAY_API_KEY='your-key-here'")
        print(f"\n   🧪 To disable auth (testing only):")
        print(f"      export BLE_GATEWAY_AUTH_ENABLED=false")

        # Warn if API key was auto-generated
        if not os.environ.get('BLE_GATEWAY_API_KEY'):
            print(f"\n   ⚠️  WARNING: Using auto-generated key!")
            print(f"      This key will change on restart.")
            print(f"      Set BLE_GATEWAY_API_KEY env var to persist it.")
    else:
        print(f"   ⚠️  Authentication DISABLED (dev mode)")
        print(f"   ⚠️  Anyone can access the API!")
        print(f"   Enable with: export BLE_GATEWAY_AUTH_ENABLED=true")
    print("=" * 60)
    print(f"📝 Logging to: ble_gateway.log")
    print("💾 Database:   ble_gateway.db")
    print("=" * 60)
    print("\nPress Ctrl+C to stop\n")

    if mqtt_available:
        setup_mqtt()

    logger.info("Server started successfully")

    # Disable Flask's default logging to avoid duplicates
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)

    # Run with HTTPS using SSL context
    import ssl
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(cert_file, key_file)

    app.run(host='0.0.0.0', port=8443, ssl_context=ssl_context, debug=False)
