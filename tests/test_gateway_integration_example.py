import sqlite3

import gateway_integration_example as gateway_example


def test_process_ble_data_with_multipacket_calls_save(monkeypatch):
    called = {'saved': False}

    def fake_process_packet(device_id, manufacturer_data):
        return {
            'stream_id': 1,
            'data_type': 0xDD,
            'length': 10,
            'complete': True,
            'data': b'\x00\x01',
            'parsed': {'adc_range': 1.0, 'vdd_avg': 2.0, 'gnd_avg': 1.0}
        }

    def fake_save(*_args, **_kwargs):
        called['saved'] = True

    monkeypatch.setattr(gateway_example.ble_receiver, 'process_packet', fake_process_packet)
    monkeypatch.setattr(gateway_example, 'save_complete_stream_to_database', fake_save)

    data = [{
        'id': 'AA:BB:CC:DD:EE:FF',
        'name': 'DeviceOne',
        'rssi': -65,
        'advertising': {'manufacturerData': 'FFE5AADD'}
    }]
    gateway_example.process_ble_data_with_multipacket(data)
    assert called['saved'] is True


def test_process_ble_data_with_multipacket_missing_data(monkeypatch):
    called = {'saved': False}

    def fake_save(*_args, **_kwargs):
        called['saved'] = True

    monkeypatch.setattr(gateway_example, 'save_complete_stream_to_database', fake_save)

    data = [{
        'id': 'AA:BB:CC:DD:EE:FF',
        'name': 'DeviceOne',
        'rssi': -65,
        'advertising': {}
    }]
    gateway_example.process_ble_data_with_multipacket(data)
    assert called['saved'] is False


def test_save_complete_stream_to_database_inserts_row(tmp_path, monkeypatch):
    db_path = tmp_path / 'streams.db'
    original_connect = sqlite3.connect

    def fake_connect(_path):
        return original_connect(db_path)

    monkeypatch.setattr(sqlite3, 'connect', fake_connect)

    stream_data = {
        'stream_id': 123,
        'data_type': 0xDD,
        'length': 2,
        'complete': True,
        'data': b'\x01\x02',
        'parsed': {'adc_range': 1.0}
    }
    gateway_example.save_complete_stream_to_database('AA:BB:CC:DD:EE:FF', 'DeviceOne', stream_data)

    conn = original_connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM multipacket_streams')
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 1
