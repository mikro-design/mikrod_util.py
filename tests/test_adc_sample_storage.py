import runpy
import sqlite3

from adc_sample_storage import (
    ADCMeasurementHandler,
    get_all_devices,
    get_latest_measurement,
    get_measurements,
    init_adc_storage,
    store_adc_measurement,
)


def _create_legacy_table(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE adc_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            device_id TEXT NOT NULL,
            stream_id INTEGER,
            sample_count INTEGER,
            samples TEXT,
            stats TEXT,
            raw_bytes BLOB,
            FOREIGN KEY (device_id) REFERENCES device_readings(device_id)
        )
    ''')
    conn.commit()
    conn.close()


def test_init_adc_storage_migrates_foreign_key(tmp_path):
    db_path = tmp_path / 'adc_legacy.db'
    _create_legacy_table(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('PRAGMA foreign_key_list(adc_measurements)')
    assert cursor.fetchall()
    conn.close()

    assert init_adc_storage(str(db_path)) is True

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('PRAGMA foreign_key_list(adc_measurements)')
    assert cursor.fetchall() == []
    conn.close()


def test_store_and_fetch_measurements(tmp_path):
    db_path = tmp_path / 'adc.db'
    assert init_adc_storage(str(db_path)) is True

    samples = list(range(84))
    meas_id = store_adc_measurement('AA:BB:CC:DD:EE:FF', samples, stream_id=7, db_file=str(db_path))
    assert meas_id is not None

    latest = get_latest_measurement('AA:BB:CC:DD:EE:FF', db_file=str(db_path))
    assert latest is not None
    assert latest['sample_count'] == 84
    assert latest['stats']['min'] == 0
    assert latest['stats']['max'] == 83

    recent = get_measurements('AA:BB:CC:DD:EE:FF', hours=1, limit=1, db_file=str(db_path))
    assert len(recent) == 1

    devices = get_all_devices(db_file=str(db_path))
    assert devices == ['AA:BB:CC:DD:EE:FF']


def test_adc_measurement_handler_stores_samples(tmp_path):
    db_path = tmp_path / 'adc_handler.db'
    handler = ADCMeasurementHandler(db_file=str(db_path))

    stream_data = {
        'stream_id': 42,
        'parsed': {
            'vdd_ref': [10] * 8,
            'gnd_ref': [1] * 8,
            'self_cap_raw': [5] * 34,
            'mutual_cap_raw': [6] * 34,
        }
    }
    handler.on_stream_complete('AA:BB:CC:DD:EE:FF', stream_data)

    latest = get_latest_measurement('AA:BB:CC:DD:EE:FF', db_file=str(db_path))
    assert latest is not None
    assert latest['stream_id'] == 42


def test_empty_and_error_paths(tmp_path, monkeypatch):
    db_path = tmp_path / 'adc_empty.db'
    assert init_adc_storage(str(db_path)) is True

    assert get_latest_measurement('AA:BB:CC:DD:EE:FF', db_file=str(db_path)) is None
    assert get_measurements('AA:BB:CC:DD:EE:FF', hours=1, limit='nope', db_file=str(db_path)) == []

    handler = ADCMeasurementHandler(db_file=str(db_path))
    handler.on_stream_complete('AA:BB:CC:DD:EE:FF', {'stream_id': 1})
    handler.on_stream_complete('AA:BB:CC:DD:EE:FF', {
        'stream_id': 2,
        'parsed': {
            'vdd_ref': [1] * 4,
            'gnd_ref': [2] * 4,
            'self_cap_raw': [3] * 4,
            'mutual_cap_raw': [4] * 4,
        }
    })

    def fail_connect(*_args, **_kwargs):
        raise sqlite3.OperationalError('fail')

    monkeypatch.setattr(sqlite3, 'connect', fail_connect)
    assert store_adc_measurement('AA:BB:CC:DD:EE:FF', [1] * 84, db_file=str(db_path)) is None


def test_main_block_runs(tmp_path, monkeypatch):
    db_path = tmp_path / 'adc_main.db'
    original_connect = sqlite3.connect

    def fake_connect(_path):
        return original_connect(db_path)

    monkeypatch.setattr(sqlite3, 'connect', fake_connect)
    runpy.run_module('adc_sample_storage', run_name='__main__')
