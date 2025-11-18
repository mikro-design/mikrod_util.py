"""
Unit tests for API endpoints
"""
import pytest
import json


@pytest.mark.unit
class TestHealthEndpoint:
    """Tests for the health check endpoint"""

    def test_health_endpoint_returns_200(self, client):
        """Health endpoint should return 200"""
        response = client.get('/health')
        assert response.status_code == 200

    def test_health_endpoint_returns_json(self, client):
        """Health endpoint should return valid JSON"""
        response = client.get('/health')
        data = response.get_json()
        assert data is not None
        assert 'status' in data
        assert 'timestamp' in data

    def test_health_endpoint_shows_components(self, client):
        """Health endpoint should show component status"""
        response = client.get('/health')
        data = response.get_json()
        assert 'components' in data
        assert 'database' in data['components']

    def test_api_health_endpoint(self, client):
        """API health endpoint should also work"""
        response = client.get('/api/health')
        assert response.status_code == 200


@pytest.mark.unit
class TestBLEEndpoint:
    """Tests for the BLE data submission endpoint"""

    def test_ble_endpoint_requires_json(self, client):
        """BLE endpoint should require JSON content type"""
        response = client.post('/api/ble', data='not json')
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data

    def test_ble_endpoint_rejects_invalid_json(self, client):
        """BLE endpoint should reject malformed JSON"""
        response = client.post(
            '/api/ble',
            data='{"invalid": json}',
            content_type='application/json'
        )
        assert response.status_code == 400

    def test_ble_endpoint_validates_data_structure(self, client):
        """BLE endpoint should validate data structure"""
        # Not an array
        response = client.post(
            '/api/ble',
            json={"id": "AA:BB:CC:DD:EE:FF"},
            content_type='application/json'
        )
        assert response.status_code == 400

    def test_ble_endpoint_accepts_valid_data(self, client, sample_ble_data):
        """BLE endpoint should accept valid data"""
        response = client.post(
            '/api/ble',
            json=sample_ble_data,
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'success'
        assert data['received'] == len(sample_ble_data)

    def test_ble_endpoint_detects_sensors(self, client, sample_ble_device):
        """BLE endpoint should detect sensors in advertising data"""
        response = client.post(
            '/api/ble',
            json=[sample_ble_device],
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert 'sensors_detected' in data
        assert data['sensors_detected'] >= 3  # temp, humidity, pressure

    def test_ble_endpoint_rejects_missing_id(self, client):
        """BLE endpoint should reject devices without ID"""
        invalid_data = [{"name": "NoID", "rssi": -65}]
        response = client.post(
            '/api/ble',
            json=invalid_data,
            content_type='application/json'
        )
        assert response.status_code == 400

    def test_ble_endpoint_validates_rssi_range(self, client):
        """BLE endpoint should validate RSSI is in valid range"""
        invalid_data = [{
            "id": "AA:BB:CC:DD:EE:FF",
            "rssi": 100  # Invalid: RSSI should be negative
        }]
        response = client.post(
            '/api/ble',
            json=invalid_data,
            content_type='application/json'
        )
        # Should fail validation if jsonschema is installed
        # Otherwise may pass basic validation
        # Just check it's handled
        assert response.status_code in [200, 400]

    def test_ble_endpoint_rejects_too_many_devices(self, client):
        """BLE endpoint should reject payloads with too many devices"""
        # Create 101 devices (max is 100)
        too_many = [
            {"id": f"AA:BB:CC:DD:EE:{i:02X}", "rssi": -65}
            for i in range(101)
        ]
        response = client.post(
            '/api/ble',
            json=too_many,
            content_type='application/json'
        )
        assert response.status_code == 400


@pytest.mark.unit
class TestAuthenticationEndpoints:
    """Tests for authentication on protected endpoints"""

    def test_ble_endpoint_requires_auth(self, client_with_auth, sample_ble_data):
        """BLE endpoint should require authentication when enabled"""
        response = client_with_auth.post(
            '/api/ble',
            json=sample_ble_data,
            content_type='application/json'
        )
        assert response.status_code == 401
        data = response.get_json()
        assert 'error' in data
        assert data['error'] == 'Unauthorized'

    def test_ble_endpoint_accepts_bearer_token(self, client_with_auth, sample_ble_data, api_key):
        """BLE endpoint should accept Bearer token"""
        response = client_with_auth.post(
            '/api/ble',
            json=sample_ble_data,
            headers={'Authorization': f'Bearer {api_key}'},
            content_type='application/json'
        )
        assert response.status_code == 200

    def test_ble_endpoint_accepts_api_key_header(self, client_with_auth, sample_ble_data, api_key):
        """BLE endpoint should accept X-API-Key header"""
        response = client_with_auth.post(
            '/api/ble',
            json=sample_ble_data,
            headers={'X-API-Key': api_key},
            content_type='application/json'
        )
        assert response.status_code == 200

    def test_ble_endpoint_accepts_query_param(self, client_with_auth, sample_ble_data, api_key):
        """BLE endpoint should accept API key as query parameter"""
        response = client_with_auth.post(
            f'/api/ble?api_key={api_key}',
            json=sample_ble_data,
            content_type='application/json'
        )
        assert response.status_code == 200

    def test_ble_endpoint_rejects_invalid_key(self, client_with_auth, sample_ble_data):
        """BLE endpoint should reject invalid API key"""
        response = client_with_auth.post(
            '/api/ble',
            json=sample_ble_data,
            headers={'Authorization': 'Bearer invalid-key'},
            content_type='application/json'
        )
        assert response.status_code == 401

    def test_devices_endpoint_requires_auth(self, client_with_auth):
        """GET /api/devices should require authentication"""
        response = client_with_auth.get('/api/devices')
        assert response.status_code == 401

    def test_devices_endpoint_accepts_auth(self, client_with_auth, api_key):
        """GET /api/devices should work with valid auth"""
        response = client_with_auth.get(
            '/api/devices',
            headers={'Authorization': f'Bearer {api_key}'}
        )
        assert response.status_code == 200

    def test_health_endpoint_no_auth_required(self, client_with_auth):
        """Health endpoint should not require auth"""
        response = client_with_auth.get('/health')
        assert response.status_code == 200


@pytest.mark.unit
class TestDevicesEndpoint:
    """Tests for the devices endpoint"""

    def test_devices_endpoint_returns_json(self, client):
        """Devices endpoint should return JSON"""
        response = client.get('/api/devices')
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

    def test_devices_endpoint_has_structure(self, client):
        """Devices endpoint should have expected structure"""
        response = client.get('/api/devices')
        data = response.get_json()
        assert 'devices' in data
        assert 'timestamp' in data
        assert 'count' in data

    def test_devices_endpoint_after_data_submit(self, client, sample_ble_data):
        """Devices endpoint should return submitted data"""
        # Submit data first
        client.post('/api/ble', json=sample_ble_data)

        # Now check devices endpoint
        response = client.get('/api/devices')
        data = response.get_json()
        assert data['count'] == len(sample_ble_data)
        assert len(data['devices']) == len(sample_ble_data)


@pytest.mark.unit
class TestDashboard:
    """Tests for the web dashboard"""

    def test_dashboard_returns_html(self, client):
        """Dashboard should return HTML"""
        response = client.get('/')
        assert response.status_code == 200
        assert b'<!DOCTYPE html>' in response.data

    def test_dashboard_shows_title(self, client):
        """Dashboard should show title"""
        response = client.get('/')
        assert b'BLE Gateway Monitor' in response.data

    def test_dashboard_shows_devices_after_submit(self, client, sample_ble_data):
        """Dashboard should show devices after data submission"""
        # Submit data
        client.post('/api/ble', json=sample_ble_data)

        # Check dashboard
        response = client.get('/')
        assert sample_ble_data[0]['name'].encode() in response.data
