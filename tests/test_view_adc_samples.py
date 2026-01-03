import json
import runpy
import sqlite3
import sys
from datetime import datetime

import pytest

from view_adc_samples import (
    ADCViewer,
    cmd_latest,
    cmd_list,
    cmd_show,
    cmd_stats,
    compute_stats,
    format_samples,
    print_help,
    plot_samples,
)


@pytest.fixture
def viewer_db(tmp_path):
    db_path = tmp_path / 'viewer.db'
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
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
        INSERT INTO device_readings (timestamp, device_id, device_name, rssi, raw_data)
        VALUES (?, ?, ?, ?, ?)
    ''', (now, 'AA:BB:CC:DD:EE:FF', 'DeviceOne', -55, json.dumps({'samples': [1, 2, 3]})))
    cursor.execute('''
        INSERT INTO device_readings (timestamp, device_id, device_name, rssi, raw_data)
        VALUES (?, ?, ?, ?, ?)
    ''', (now, '11:22:33:44:55:66', 'DeviceTwo', -70, 'not-json'))
    conn.commit()
    conn.close()

    viewer = ADCViewer(db_file=str(db_path))
    assert viewer.connect()
    yield viewer
    viewer.close()


def test_viewer_queries(viewer_db):
    devices = viewer_db.get_devices()
    assert 'AA:BB:CC:DD:EE:FF' in devices

    latest = viewer_db.get_latest()
    assert latest is not None

    latest_device = viewer_db.get_latest('AA:BB:CC:DD:EE:FF')
    assert latest_device is not None

    readings = viewer_db.get_device_readings('AA:BB:CC:DD:EE:FF', hours=1, limit=1)
    assert readings

    formatted = viewer_db.format_row(latest_device)
    assert formatted['device_id'] == 'AA:BB:CC:DD:EE:FF'

    invalid_row = viewer_db.get_latest('11:22:33:44:55:66')
    invalid_formatted = viewer_db.format_row(invalid_row)
    assert invalid_formatted['data'] == {}


def test_connect_failure(monkeypatch):
    def fail_connect(_path):
        raise sqlite3.OperationalError('fail')

    monkeypatch.setattr(sqlite3, 'connect', fail_connect)
    viewer = ADCViewer(db_file='bad.db')
    assert viewer.connect() is False


def test_query_error_paths():
    viewer = ADCViewer(db_file='bad.db')
    viewer.cursor = None
    assert viewer.get_devices() == []
    assert viewer.get_latest() is None
    assert viewer.get_device_readings('AA:BB:CC:DD:EE:FF') == []


def test_format_and_stats_helpers():
    samples = [1, 2, 3, 4, 5, 6]
    formatted = format_samples(samples, samples_per_line=3)
    assert '[ 0]:' in formatted

    stats = compute_stats(samples + ['x'])
    assert stats['min'] == 1
    assert stats['max'] == 6
    assert stats['count'] == 6

    empty_stats = compute_stats([])
    assert empty_stats == {}

    plot = plot_samples(samples, width=10, height=4)
    lines = plot.splitlines()
    assert len(lines) >= 4
    assert '1' in lines[-1]
    assert '6' in lines[-1]


def test_cli_helpers(viewer_db, capsys):
    cmd_list(viewer_db)
    output = capsys.readouterr().out
    assert 'AA:BB:CC:DD:EE:FF' in output

    cmd_latest(viewer_db)
    output = capsys.readouterr().out
    assert 'LATEST MEASUREMENT' in output

    cmd_show(viewer_db, 'AA:BB:CC:DD:EE:FF')
    output = capsys.readouterr().out
    assert 'MEASUREMENTS FOR' in output

    cmd_stats(viewer_db, 'AA:BB:CC:DD:EE:FF')
    output = capsys.readouterr().out
    assert 'STATISTICS' in output


def test_cli_error_paths(viewer_db, capsys):
    cmd_latest(viewer_db, 'AA:BB:CC:DD:EE:FF')
    output = capsys.readouterr().out
    assert 'LATEST MEASUREMENT' in output

    cmd_show(viewer_db, '00:00:00:00:00:00')
    output = capsys.readouterr().out
    assert 'No measurements' in output

    cmd_stats(viewer_db, '00:00:00:00:00:00')
    output = capsys.readouterr().out
    assert 'No measurements' in output

    print_help()
    output = capsys.readouterr().out
    assert 'Usage:' in output


def test_main_block_runs(tmp_path, monkeypatch):
    db_path = tmp_path / 'main_viewer.db'
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
        INSERT INTO device_readings (device_id, device_name, rssi, raw_data)
        VALUES (?, ?, ?, ?)
    ''', ('AA:BB:CC:DD:EE:FF', 'DeviceOne', -55, json.dumps({'samples': [1]})))
    conn.commit()
    conn.close()

    original_connect = sqlite3.connect

    def fake_connect(_path):
        return original_connect(db_path)

    monkeypatch.setattr(sqlite3, 'connect', fake_connect)

    monkeypatch.setattr(sys, 'argv', ['view_adc_samples.py'])
    runpy.run_module('view_adc_samples', run_name='__main__')

    monkeypatch.setattr(sys, 'argv', ['view_adc_samples.py', 'list'])
    runpy.run_module('view_adc_samples', run_name='__main__')

    monkeypatch.setattr(sys, 'argv', ['view_adc_samples.py', 'unknown'])
    runpy.run_module('view_adc_samples', run_name='__main__')
