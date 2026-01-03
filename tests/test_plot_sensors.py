import json
import os
import sqlite3
from datetime import datetime

import pytest

os.environ.setdefault('MPLBACKEND', 'Agg')
import matplotlib

matplotlib.use('Agg')

import plot_sensors


def _create_empty_db(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE device_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            device_id TEXT NOT NULL,
            device_name TEXT,
            rssi INTEGER,
            raw_data TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reading_id INTEGER,
            sensor_type TEXT NOT NULL,
            sensor_value REAL NOT NULL,
            unit TEXT,
            FOREIGN KEY (reading_id) REFERENCES device_readings(id)
        )
    ''')
    conn.commit()
    return conn


@pytest.fixture
def sensor_db(tmp_path):
    db_path = tmp_path / 'plot.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE device_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            device_id TEXT NOT NULL,
            device_name TEXT,
            rssi INTEGER,
            raw_data TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reading_id INTEGER,
            sensor_type TEXT NOT NULL,
            sensor_value REAL NOT NULL,
            unit TEXT,
            FOREIGN KEY (reading_id) REFERENCES device_readings(id)
        )
    ''')

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    raw_data_1 = {
        'temp': 22.5,
        'humidity': 40.0,
        'manufacturerData': {'004c': {'bytes': [1, 2, 3, 4]}},
        'rawData': [10, 11, 12]
    }
    cursor.execute('''
        INSERT INTO device_readings (timestamp, device_id, device_name, rssi, raw_data)
        VALUES (?, ?, ?, ?, ?)
    ''', (now, 'AA:BB:CC:DD:EE:FF', 'DeviceOne', -65, json.dumps(raw_data_1)))
    reading_id_1 = cursor.lastrowid
    cursor.execute('''
        INSERT INTO sensor_data (reading_id, sensor_type, sensor_value, unit)
        VALUES (?, ?, ?, ?)
    ''', (reading_id_1, 'temperature', 22.5, 'C'))

    raw_data_2 = {
        'temp': 24.0,
        'pressure': 1010.0,
        'rawData': [13, 14, 15]
    }
    cursor.execute('''
        INSERT INTO device_readings (timestamp, device_id, device_name, rssi, raw_data)
        VALUES (?, ?, ?, ?, ?)
    ''', (now, '11:22:33:44:55:66', 'DeviceTwo', -72, json.dumps(raw_data_2)))
    reading_id_2 = cursor.lastrowid
    cursor.execute('''
        INSERT INTO sensor_data (reading_id, sensor_type, sensor_value, unit)
        VALUES (?, ?, ?, ?)
    ''', (reading_id_2, 'pressure', 1010.0, 'hPa'))

    conn.commit()
    yield conn
    conn.close()


def test_extract_field_value():
    data = {'a': {'b': [1, 2, {'c': 5}]}}
    assert plot_sensors.extract_field_value(data, 'a.b.0') == 1
    assert plot_sensors.extract_field_value(data, 'a.b.2.c') == 5
    assert plot_sensors.extract_field_value(data, 'a.b.9') is None


def test_get_available_devices_and_sensor_types(sensor_db):
    devices = plot_sensors.get_available_devices(sensor_db)
    assert devices

    all_types = plot_sensors.get_sensor_types(sensor_db)
    assert any(row[0] == 'temperature' for row in all_types)

    device_types = plot_sensors.get_sensor_types(sensor_db, device_id='AA:BB:CC:DD:EE:FF')
    assert device_types


def test_get_sensor_data_and_raw_fields(sensor_db):
    data = plot_sensors.get_sensor_data(sensor_db, 'temperature')
    assert data

    device_data = plot_sensors.get_sensor_data(sensor_db, 'temperature', device_id='AA:BB:CC:DD:EE:FF')
    assert device_data

    raw = plot_sensors.get_raw_field_data(sensor_db, 'rawData.1')
    assert raw

    nested = plot_sensors.get_raw_field_data(sensor_db, 'manufacturerData.004c.bytes.0')
    assert nested


def test_plot_functions(sensor_db, tmp_path):
    multi_path = tmp_path / 'multi.png'
    plot_sensors.plot_multiple_fields(
        sensor_db,
        ['temp', 'rawData.1'],
        save_path=str(multi_path)
    )
    assert multi_path.exists()

    sensor_data = plot_sensors.get_sensor_data(sensor_db, 'temperature')
    single_path = tmp_path / 'single.png'
    plot_sensors.plot_sensor_data('temperature', sensor_data, save_path=str(single_path))
    assert single_path.exists()

    rssi_all = tmp_path / 'rssi_all.png'
    plot_sensors.plot_rssi(sensor_db, save_path=str(rssi_all))
    assert rssi_all.exists()

    rssi_device = tmp_path / 'rssi_device.png'
    plot_sensors.plot_rssi(sensor_db, device_id='AA:BB:CC:DD:EE:FF', save_path=str(rssi_device))
    assert rssi_device.exists()


def test_list_and_clear_database(sensor_db, monkeypatch, capsys):
    plot_sensors.list_available_data(sensor_db)
    output = capsys.readouterr().out
    assert 'DeviceOne' in output

    monkeypatch.setattr('builtins.input', lambda _: 'no')
    plot_sensors.clear_database(sensor_db)

    monkeypatch.setattr('builtins.input', lambda _: 'yes')
    plot_sensors.clear_database(sensor_db)


def test_main_cli_branches(sensor_db, monkeypatch, tmp_path):
    cursor = sensor_db.cursor()
    cursor.execute('PRAGMA database_list')
    db_path = cursor.fetchone()[2]

    def run_main(args, input_value=None):
        if input_value is not None:
            monkeypatch.setattr('builtins.input', lambda _: input_value)
        monkeypatch.setattr(plot_sensors.sys, 'argv', ['plot_sensors.py'] + args)
        plot_sensors.main()

    run_main(['--list', '--db', db_path])

    run_main(['--rssi', '--db', db_path, '--save', str(tmp_path / 'rssi.png')])
    run_main(['--field', 'temp', '--db', db_path, '--save', str(tmp_path / 'field.png')])
    run_main([
        '--fields', 'rawData.0', 'rawData.1',
        '--db', db_path,
        '--save', str(tmp_path / 'fields.png')
    ])
    run_main(['--sensor', 'temperature', '--db', db_path, '--save', str(tmp_path / 'sensor.png')])

    run_main(['--clear', '--db', db_path], input_value='no')


def test_live_plot_helpers(sensor_db, monkeypatch):
    cursor = sensor_db.cursor()
    cursor.execute('PRAGMA database_list')
    db_path = cursor.fetchone()[2]

    monkeypatch.setattr(plot_sensors.plt, 'pause', lambda *_: None)

    plot_sensors.live_plot_field(db_path, 'rawData.1', refresh_seconds=0, max_iterations=1)
    plot_sensors.live_plot_fields(db_path, ['rawData.1', 'rawData.2'], refresh_seconds=0, max_iterations=1)
    plot_sensors.live_plot_sensor(db_path, 'temperature', refresh_seconds=0, max_iterations=1)
    plot_sensors.live_plot_rssi(db_path, refresh_seconds=0, max_iterations=1)


def test_main_live_branch(sensor_db, monkeypatch):
    cursor = sensor_db.cursor()
    cursor.execute('PRAGMA database_list')
    db_path = cursor.fetchone()[2]

    called = {}

    def fake_live(db_path_arg, field_path, device_id, hours, refresh):
        called['args'] = (db_path_arg, field_path, device_id, hours, refresh)

    monkeypatch.setattr(plot_sensors, 'live_plot_field', fake_live)
    monkeypatch.setattr(plot_sensors.sys, 'argv', [
        'plot_sensors.py', '--live', '--field', 'rawData.1', '--db', db_path
    ])
    plot_sensors.main()

    assert called['args'][1] == 'rawData.1'


def test_main_live_fields_branch(sensor_db, monkeypatch):
    cursor = sensor_db.cursor()
    cursor.execute('PRAGMA database_list')
    db_path = cursor.fetchone()[2]

    called = {}

    def fake_live(db_path_arg, field_paths, device_id, hours, refresh):
        called['args'] = (db_path_arg, field_paths, device_id, hours, refresh)

    monkeypatch.setattr(plot_sensors, 'live_plot_fields', fake_live)
    monkeypatch.setattr(plot_sensors.sys, 'argv', [
        'plot_sensors.py', '--live', '--fields', 'rawData.1', 'rawData.2', '--db', db_path
    ])
    plot_sensors.main()

    assert called['args'][1] == ['rawData.1', 'rawData.2']


def test_helper_branches(tmp_path, capsys):
    assert plot_sensors._ensure_positive_refresh(None) == 1.0
    assert plot_sensors._ensure_positive_refresh('bad') == 1.0
    assert plot_sensors._ensure_positive_refresh(-1) == 0.1

    fig, ax = plot_sensors.plt.subplots()
    plot_sensors.render_sensor_plot(ax, 'temperature', [], None)
    plot_sensors.render_rssi_plot(ax, [], device_id=None)
    plot_sensors.plt.close(fig)

    conn = _create_empty_db(tmp_path / 'empty.db')
    plot_sensors.list_available_data(conn)
    output = capsys.readouterr().out
    assert "No devices found" in output
    conn.close()
