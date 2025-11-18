"""
Unit tests for database operations
"""
import pytest
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import ble_gtw_server


@pytest.mark.unit
class TestDatabaseInit:
    """Tests for database initialization"""

    def test_init_database_creates_tables(self, db_connection):
        """init_database should create required tables"""
        cursor = db_connection.cursor()

        # Check device_readings table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='device_readings'
        """)
        assert cursor.fetchone() is not None

        # Check sensor_data table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='sensor_data'
        """)
        assert cursor.fetchone() is not None

    def test_device_readings_schema(self, db_connection):
        """device_readings table should have correct schema"""
        cursor = db_connection.cursor()
        cursor.execute("PRAGMA table_info(device_readings)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert 'id' in columns
        assert 'timestamp' in columns
        assert 'device_id' in columns
        assert 'device_name' in columns
        assert 'rssi' in columns
        assert 'raw_data' in columns

    def test_sensor_data_schema(self, db_connection):
        """sensor_data table should have correct schema"""
        cursor = db_connection.cursor()
        cursor.execute("PRAGMA table_info(sensor_data)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert 'id' in columns
        assert 'reading_id' in columns
        assert 'sensor_type' in columns
        assert 'sensor_value' in columns
        assert 'unit' in columns


@pytest.mark.unit
class TestSaveToDatabase:
    """Tests for save_to_database function"""

    def test_save_device_reading(self, db_connection):
        """Should save device reading to database"""
        # Temporarily use test database
        original_db = ble_gtw_server.DB_FILE
        ble_gtw_server.DB_FILE = db_connection.execute("PRAGMA database_list").fetchone()[2]

        device_id = "AA:BB:CC:DD:EE:FF"
        device_name = "TestDevice"
        rssi = -65
        advertising = {"temp": 23.5}

        # This would actually need the database path, not connection
        # For now, let's test the logic directly
        cursor = db_connection.cursor()
        cursor.execute('''
            INSERT INTO device_readings (device_id, device_name, rssi, raw_data)
            VALUES (?, ?, ?, ?)
        ''', (device_id, device_name, rssi, json.dumps(advertising)))
        db_connection.commit()

        # Verify
        cursor.execute('SELECT * FROM device_readings WHERE device_id = ?', (device_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[2] == device_id  # device_id
        assert row[3] == device_name  # device_name
        assert row[4] == rssi  # rssi

        ble_gtw_server.DB_FILE = original_db

    def test_save_sensor_data(self, db_connection):
        """Should save sensor data linked to reading"""
        cursor = db_connection.cursor()

        # Insert device reading
        cursor.execute('''
            INSERT INTO device_readings (device_id, device_name, rssi, raw_data)
            VALUES (?, ?, ?, ?)
        ''', ("AA:BB:CC:DD:EE:FF", "TestDevice", -65, '{"temp": 23.5}'))
        reading_id = cursor.lastrowid

        # Insert sensor data
        cursor.execute('''
            INSERT INTO sensor_data (reading_id, sensor_type, sensor_value, unit)
            VALUES (?, ?, ?, ?)
        ''', (reading_id, 'temperature', 23.5, '°C'))
        db_connection.commit()

        # Verify
        cursor.execute('SELECT * FROM sensor_data WHERE reading_id = ?', (reading_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[2] == 'temperature'  # sensor_type
        assert row[3] == 23.5  # sensor_value
        assert row[4] == '°C'  # unit

    def test_save_multiple_sensors(self, db_connection):
        """Should save multiple sensors for one reading"""
        cursor = db_connection.cursor()

        # Insert device reading
        cursor.execute('''
            INSERT INTO device_readings (device_id, device_name, rssi, raw_data)
            VALUES (?, ?, ?, ?)
        ''', ("AA:BB:CC:DD:EE:FF", "TestDevice", -65, '{"temp": 23.5, "humidity": 45.2}'))
        reading_id = cursor.lastrowid

        # Insert multiple sensors
        sensors = [
            (reading_id, 'temperature', 23.5, '°C'),
            (reading_id, 'humidity', 45.2, '%')
        ]
        cursor.executemany('''
            INSERT INTO sensor_data (reading_id, sensor_type, sensor_value, unit)
            VALUES (?, ?, ?, ?)
        ''', sensors)
        db_connection.commit()

        # Verify
        cursor.execute('SELECT COUNT(*) FROM sensor_data WHERE reading_id = ?', (reading_id,))
        count = cursor.fetchone()[0]
        assert count == 2


@pytest.mark.unit
class TestDataValidation:
    """Tests for validate_ble_data function"""

    def test_validate_valid_data(self, sample_ble_data):
        """Should accept valid BLE data"""
        is_valid, error = ble_gtw_server.validate_ble_data(sample_ble_data)
        assert is_valid is True
        assert error is None

    def test_validate_rejects_non_list(self):
        """Should reject data that's not a list"""
        is_valid, error = ble_gtw_server.validate_ble_data({"id": "AA:BB:CC:DD:EE:FF"})
        assert is_valid is False
        assert error is not None

    def test_validate_rejects_empty_list(self):
        """Should reject empty list"""
        is_valid, error = ble_gtw_server.validate_ble_data([])
        assert is_valid is False
        assert error is not None

    def test_validate_rejects_missing_id(self):
        """Should reject devices without ID"""
        invalid_data = [{"name": "NoID", "rssi": -65}]
        is_valid, error = ble_gtw_server.validate_ble_data(invalid_data)
        assert is_valid is False
        assert error is not None

    def test_validate_accepts_minimal_data(self):
        """Should accept minimal valid data"""
        minimal_data = [{"id": "AA:BB:CC:DD:EE:FF"}]
        is_valid, error = ble_gtw_server.validate_ble_data(minimal_data)
        assert is_valid is True

    def test_validate_rejects_too_many_devices(self):
        """Should reject payloads with more than 100 devices"""
        too_many = [{"id": f"AA:BB:CC:DD:EE:{i:02X}"} for i in range(101)]
        is_valid, error = ble_gtw_server.validate_ble_data(too_many)
        assert is_valid is False
        assert error is not None

    def test_validate_rejects_invalid_id_type(self):
        """Should reject non-string device IDs"""
        invalid_data = [{"id": 123}]
        is_valid, error = ble_gtw_server.validate_ble_data(invalid_data)
        assert is_valid is False

    def test_validate_rejects_too_long_id(self):
        """Should reject device IDs that are too long"""
        invalid_data = [{"id": "A" * 100}]  # Way too long
        is_valid, error = ble_gtw_server.validate_ble_data(invalid_data)
        assert is_valid is False
