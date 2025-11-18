"""
Pytest configuration and fixtures for BLE Gateway Server tests
"""
import pytest
import os
import sys
import tempfile
import sqlite3
from pathlib import Path

# Add parent directory to path so we can import the server module
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope='session', autouse=True)
def setup_test_environment():
    """Set up test environment before importing ble_gtw_server"""
    # Set environment variables before importing
    os.environ['BLE_GATEWAY_AUTH_ENABLED'] = 'false'
    os.environ['BLE_GATEWAY_API_KEY'] = 'test-api-key-12345'
    yield
    # Cleanup after all tests
    os.environ.pop('BLE_GATEWAY_AUTH_ENABLED', None)
    os.environ.pop('BLE_GATEWAY_API_KEY', None)


# Import after environment is set up
import ble_gtw_server


@pytest.fixture
def app():
    """Create and configure a test Flask application"""
    # Disable authentication for tests
    original_auth = ble_gtw_server.AUTH_ENABLED
    ble_gtw_server.AUTH_ENABLED = False

    # Create a temporary database
    db_fd, db_path = tempfile.mkstemp()
    original_db = ble_gtw_server.DB_FILE
    ble_gtw_server.DB_FILE = db_path

    # Configure app for testing
    ble_gtw_server.app.config['TESTING'] = True
    ble_gtw_server.app.config['WTF_CSRF_ENABLED'] = False

    # Disable rate limiting in tests
    if hasattr(ble_gtw_server, 'limiter') and ble_gtw_server.limiter:
        ble_gtw_server.limiter.enabled = False

    # Initialize database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()

    yield ble_gtw_server.app

    # Cleanup
    ble_gtw_server.AUTH_ENABLED = original_auth
    ble_gtw_server.DB_FILE = original_db
    try:
        os.close(db_fd)
    except:
        pass
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
def client(app):
    """Create a test client for the Flask app"""
    return app.test_client()


@pytest.fixture
def app_with_auth():
    """Create and configure a test Flask application with auth enabled"""
    # Temporarily enable authentication
    original_auth = ble_gtw_server.AUTH_ENABLED
    ble_gtw_server.AUTH_ENABLED = True
    ble_gtw_server.API_KEY = 'test-api-key-12345'

    # Create a temporary database
    db_fd, db_path = tempfile.mkstemp()
    original_db = ble_gtw_server.DB_FILE
    ble_gtw_server.DB_FILE = db_path

    # Configure app for testing
    ble_gtw_server.app.config['TESTING'] = True
    ble_gtw_server.app.config['WTF_CSRF_ENABLED'] = False

    # Disable rate limiting in tests
    if hasattr(ble_gtw_server, 'limiter') and ble_gtw_server.limiter:
        ble_gtw_server.limiter.enabled = False

    # Initialize database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()

    yield ble_gtw_server.app

    # Cleanup
    ble_gtw_server.AUTH_ENABLED = original_auth
    ble_gtw_server.DB_FILE = original_db
    try:
        os.close(db_fd)
    except:
        pass
    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
def client_with_auth(app_with_auth):
    """Create a test client with authentication enabled"""
    return app_with_auth.test_client()


@pytest.fixture
def sample_ble_data():
    """Sample BLE device data for testing"""
    return [
        {
            "id": "AA:BB:CC:DD:EE:FF",
            "name": "TestDevice1",
            "rssi": -65,
            "advertising": {
                "temp": 23.5,
                "humidity": 45.2
            }
        },
        {
            "id": "11:22:33:44:55:66",
            "name": "TestDevice2",
            "rssi": -72,
            "advertising": {
                "battery": 87,
                "voltage": 3.3
            }
        }
    ]


@pytest.fixture
def sample_ble_device():
    """Single BLE device data for testing"""
    return {
        "id": "AA:BB:CC:DD:EE:FF",
        "name": "TestDevice",
        "rssi": -65,
        "advertising": {
            "temp": 23.5,
            "humidity": 45.2,
            "pressure": 1013.25
        }
    }


@pytest.fixture
def db_connection():
    """Create a temporary database connection for testing"""
    db_fd, db_path = tempfile.mkstemp()
    conn = sqlite3.connect(db_path)

    # Initialize schema
    cursor = conn.cursor()
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
    conn.commit()

    yield conn

    # Cleanup
    conn.close()
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def api_key():
    """Return the test API key"""
    return 'test-api-key-12345'
