"""
Unit tests for sensor detection functionality
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import ble_gtw_server


@pytest.mark.unit
class TestSensorDetection:
    """Tests for detect_sensors function"""

    def test_detect_temperature(self):
        """Should detect temperature sensor"""
        data = {"temp": 23.5}
        sensors = ble_gtw_server.detect_sensors(data)
        assert len(sensors) == 1
        assert sensors[0][0] == 'temperature'
        assert sensors[0][1] == 23.5
        assert sensors[0][2] == '°C'

    def test_detect_humidity(self):
        """Should detect humidity sensor"""
        data = {"humidity": 45.2}
        sensors = ble_gtw_server.detect_sensors(data)
        assert len(sensors) == 1
        assert sensors[0][0] == 'humidity'
        assert sensors[0][1] == 45.2
        assert sensors[0][2] == '%'

    def test_detect_pressure(self):
        """Should detect pressure sensor"""
        data = {"pressure": 1013.25}
        sensors = ble_gtw_server.detect_sensors(data)
        assert len(sensors) == 1
        assert sensors[0][0] == 'pressure'
        assert sensors[0][1] == 1013.25
        assert sensors[0][2] == 'hPa'

    def test_detect_battery(self):
        """Should detect battery sensor"""
        data = {"bat": 87}
        sensors = ble_gtw_server.detect_sensors(data)
        assert len(sensors) == 1
        assert sensors[0][0] == 'battery'
        assert sensors[0][1] == 87
        assert sensors[0][2] == '%'

    def test_detect_voltage(self):
        """Should detect voltage sensor"""
        data = {"voltage": 3.3}
        sensors = ble_gtw_server.detect_sensors(data)
        assert len(sensors) == 1
        assert sensors[0][0] == 'voltage'
        assert sensors[0][1] == 3.3
        assert sensors[0][2] == 'V'

    def test_detect_multiple_sensors(self):
        """Should detect multiple sensors"""
        data = {
            "temp": 23.5,
            "humidity": 45.2,
            "pressure": 1013.25,
            "bat": 87
        }
        sensors = ble_gtw_server.detect_sensors(data)
        assert len(sensors) == 4
        sensor_types = [s[0] for s in sensors]
        assert 'temperature' in sensor_types
        assert 'humidity' in sensor_types
        assert 'pressure' in sensor_types
        assert 'battery' in sensor_types

    def test_detect_nested_sensors(self):
        """Should detect sensors in nested structures"""
        data = {
            "sensors": {
                "environmental": {
                    "temperature": 23.5
                }
            }
        }
        sensors = ble_gtw_server.detect_sensors(data)
        assert len(sensors) >= 1
        # Should find temperature even though nested
        sensor_types = [s[0] for s in sensors]
        assert 'temperature' in sensor_types

    def test_ignore_non_numeric_values(self):
        """Should ignore non-numeric values"""
        data = {
            "temp": "23.5",  # String, not number
            "humidity": 45.2  # Number, should be detected
        }
        sensors = ble_gtw_server.detect_sensors(data)
        # Should only detect humidity (numeric value)
        assert len(sensors) == 1
        assert sensors[0][0] == 'humidity'

    def test_ignore_unknown_fields(self):
        """Should ignore fields that don't match sensor patterns"""
        data = {
            "unknown_field": 123,
            "temp": 23.5
        }
        sensors = ble_gtw_server.detect_sensors(data)
        # Should only detect temp
        assert len(sensors) == 1
        assert sensors[0][0] == 'temperature'

    def test_empty_data(self):
        """Should handle empty data"""
        data = {}
        sensors = ble_gtw_server.detect_sensors(data)
        assert len(sensors) == 0

    def test_case_insensitive_detection(self):
        """Should detect sensors regardless of case"""
        data = {
            "TEMP": 23.5,
            "Humidity": 45.2,
            "BAt": 87
        }
        sensors = ble_gtw_server.detect_sensors(data)
        assert len(sensors) == 3


@pytest.mark.unit
class TestSensorPatterns:
    """Tests for SENSOR_PATTERNS configuration"""

    def test_sensor_patterns_exist(self):
        """SENSOR_PATTERNS should be defined"""
        assert hasattr(ble_gtw_server, 'SENSOR_PATTERNS')
        assert isinstance(ble_gtw_server.SENSOR_PATTERNS, dict)

    def test_sensor_patterns_complete(self):
        """SENSOR_PATTERNS should include all documented sensors"""
        expected_sensors = [
            'temp', 'temperature',
            'hum', 'humidity',
            'pressure', 'press',
            'bat', 'battery', 'batt',
            'volt', 'voltage', 'vdd',
            'current', 'curr',
            'light', 'lux', 'illuminance',
            'co2', 'voc', 'pm25', 'pm10'
        ]
        for sensor in expected_sensors:
            assert sensor in ble_gtw_server.SENSOR_PATTERNS

    def test_sensor_patterns_have_units(self):
        """Each sensor pattern should have a type and unit"""
        for key, value in ble_gtw_server.SENSOR_PATTERNS.items():
            assert isinstance(value, tuple)
            assert len(value) == 2
            sensor_type, unit = value
            assert isinstance(sensor_type, str)
            assert isinstance(unit, str)
            assert len(sensor_type) > 0
            assert len(unit) > 0
