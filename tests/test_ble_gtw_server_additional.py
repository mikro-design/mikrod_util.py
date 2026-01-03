import json
import sqlite3

import ble_gtw_server as server


class DummyMsg:
    def __init__(self, payload):
        self.payload = payload


def test_json_helpers():
    assert server._json_default(b'\x01\x02') == '0102'

    safe_obj, safe_json = server.normalize_advertising_data({'data': b'\x01'})
    assert safe_obj['data'] == '01'
    assert json.loads(safe_json)['data'] == '01'

    safe_obj, safe_json = server.normalize_advertising_data({'bad': {1, 2}})
    assert safe_obj == {}
    assert safe_json == "{}"

    assert server._coerce_advertising_json(None) == "{}"
    assert json.loads(server._coerce_advertising_json({'a': 1})) == {'a': 1}


def test_process_ble_data_and_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'ble.db'
    monkeypatch.setattr(server, 'DB_FILE', str(db_path))
    server.init_database()

    data = [{
        'id': 'AA:BB:CC:DD:EE:FF',
        'name': 'DeviceOne',
        'rssi': -60,
        'advertising': {'temp': 1.0, 'payload': b'\x01\x02'}
    }]
    result, status = server.process_ble_data(data, source='TEST')
    assert status == 200
    assert result['received'] == 1

    snapshot = server.get_latest_snapshot()
    assert snapshot['count'] == 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM device_readings')
    assert cursor.fetchone()[0] == 1
    conn.close()

    result, status = server.process_ble_data([], source='TEST')
    assert status == 400


def test_on_mqtt_message_validation(monkeypatch):
    called = {'count': 0}

    def fake_process(data, source='MQTT'):
        called['count'] += 1
        return {'status': 'ok'}, 200

    monkeypatch.setattr(server, 'process_ble_data', fake_process)
    monkeypatch.setattr(server, 'API_KEY', 'secret')
    monkeypatch.setattr(server, 'MQTT_REQUIRE_API_KEY', True)

    payload = json.dumps({
        'api_key': 'secret',
        'data': [{'id': 'AA:BB:CC:DD:EE:FF'}]
    }).encode('utf-8')
    server.on_mqtt_message(None, None, DummyMsg(payload))
    assert called['count'] == 1

    bad_payload = json.dumps({
        'api_key': 'wrong',
        'data': [{'id': 'AA:BB:CC:DD:EE:FF'}]
    }).encode('utf-8')
    server.on_mqtt_message(None, None, DummyMsg(bad_payload))
    assert called['count'] == 1

    monkeypatch.setattr(server, 'MQTT_REQUIRE_API_KEY', False)
    list_payload = json.dumps([{'id': 'AA:BB:CC:DD:EE:FF'}]).encode('utf-8')
    server.on_mqtt_message(None, None, DummyMsg(list_payload))
    assert called['count'] == 2


def test_generate_new_connection_id(tmp_path, monkeypatch):
    conn_file = tmp_path / 'connection_id.txt'
    monkeypatch.setattr(server, 'CONNECTION_ID_FILE', str(conn_file))
    conn_id = server.generate_new_connection_id()
    assert conn_id
    assert conn_file.exists()
    content = conn_file.read_text()
    assert conn_id in content
