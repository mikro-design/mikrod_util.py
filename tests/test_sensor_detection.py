"""
Unit tests for sensor detection functionality
"""
import base64
import json
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
class TestSensorSelectors:
    """Tests for configurable sensor selectors"""

    def test_selector_extracts_numeric_path(self, monkeypatch):
        selectors = [{
            "sensor_type": "temperature",
            "unit": "C",
            "path": "metrics.t1",
            "scale": 0.1
        }]
        monkeypatch.setenv("BLE_GATEWAY_SENSOR_SELECTORS", json.dumps(selectors))
        loaded = ble_gtw_server.load_sensor_selectors()
        monkeypatch.setattr(ble_gtw_server, "SENSOR_SELECTORS", loaded)

        data = {"metrics": {"t1": 250}}
        sensors = ble_gtw_server.detect_sensors(data)
        assert any(s[0] == "temperature" and s[1] == 25.0 and s[2] == "C" for s in sensors)

    def test_selector_extracts_bytes(self, monkeypatch):
        selectors = [{
            "sensor_type": "energy",
            "unit": "nJ",
            "path": "rawData",
            "format": "u16le",
            "byte_offset": 2
        }]
        monkeypatch.setenv("BLE_GATEWAY_SENSOR_SELECTORS", json.dumps(selectors))
        loaded = ble_gtw_server.load_sensor_selectors()
        monkeypatch.setattr(ble_gtw_server, "SENSOR_SELECTORS", loaded)

        data = {"rawData": [0x34, 0x12, 0x10, 0x00]}
        sensors = ble_gtw_server.detect_sensors(data)
        assert any(s[0] == "energy" and s[1] == 16 and s[2] == "nJ" for s in sensors)


@pytest.mark.unit
class TestSelectorHelpers:
    """Tests for selector helper utilities"""

    def test_extract_path_value(self):
        data = {"a": {"b": [{"c": 1}]}}
        assert ble_gtw_server._extract_path_value(data, "a.b.0.c") == 1
        assert ble_gtw_server._extract_path_value(data, "a.b.1.c") is None
        assert ble_gtw_server._extract_path_value(data, "a.b.x") is None

    def test_coerce_bytes_variants(self):
        raw = b"\x01\x02\x03"
        assert ble_gtw_server._coerce_bytes([1, 2, 3]) == raw
        assert ble_gtw_server._coerce_bytes({"bytes": [1, 2, 3]}) == raw
        assert ble_gtw_server._coerce_bytes("0x010203") == raw
        assert ble_gtw_server._coerce_bytes(base64.b64encode(raw).decode("ascii")) == raw
        assert ble_gtw_server._coerce_bytes({"unknown": "data"}) is None
        assert ble_gtw_server._coerce_bytes([1, "x"]) is None

    def test_decode_helpers(self):
        data = b"\x10\x00\x00\x01"
        assert ble_gtw_server._decode_with_format(data, "u16le") == 16
        assert ble_gtw_server._decode_with_format(data, "u16le", byte_offset=2) == 256
        assert ble_gtw_server._decode_with_format(data, "nope") is None
        assert ble_gtw_server._decode_bytes(data, byte_length=None) is None
        assert ble_gtw_server._decode_bytes(data, byte_offset=-1, byte_length=1) is None
        assert ble_gtw_server._decode_bytes(data, byte_offset=4, byte_length=1) is None
        assert ble_gtw_server._decode_bytes(data, byte_offset=0, byte_length=2, endian="big") == 4096

    def test_extract_selector_value(self):
        selector = {
            "sensor_type": "temperature",
            "unit": "C",
            "path": "metrics.t",
            "scale": 0.1,
            "value_offset": 1
        }
        data = {"metrics": {"t": 250}}
        assert ble_gtw_server._extract_selector_value(data, selector) == 26.0

        byte_selector = {
            "sensor_type": "energy",
            "unit": "nJ",
            "path": "rawData",
            "format": "u16le",
            "byte_offset": 1
        }
        data = {"rawData": [0x00, 0x10, 0x00]}
        assert ble_gtw_server._extract_selector_value(data, byte_selector) == 16

        missing_selector = {"sensor_type": "energy", "unit": "nJ", "path": "missing"}
        assert ble_gtw_server._extract_selector_value({}, missing_selector) is None

    def test_load_sensor_selectors_and_supported_types(self, monkeypatch, tmp_path):
        env_selectors = [{"sensor_type": "turbidity", "unit": "ntu", "path": "metrics.t"}]
        file_selectors = {"selectors": [{"sensor_type": "energy", "unit": "nJ", "path": "rawData", "format": "u16le"}]}
        file_path = tmp_path / "selectors.json"
        file_path.write_text(json.dumps(file_selectors))

        monkeypatch.setenv("BLE_GATEWAY_SENSOR_SELECTORS", json.dumps(env_selectors))
        monkeypatch.setenv("BLE_GATEWAY_SENSOR_SELECTORS_FILE", str(file_path))
        selectors = ble_gtw_server.load_sensor_selectors()
        assert len(selectors) == 2

        monkeypatch.setattr(ble_gtw_server, "SENSOR_SELECTORS", selectors)
        supported = ble_gtw_server.get_supported_sensor_types()
        assert "turbidity" in supported


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
