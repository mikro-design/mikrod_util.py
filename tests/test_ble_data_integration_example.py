import pytest

import ble_data_integration_example as integration


def test_measurement_callback_and_stats(capsys):
    handler = integration.BLEGatewayIntegration()
    stream_data = {
        'stream_id': 1,
        'packets_received': 14,
        'packets_expected': 14,
        'length': 168,
        'expected_length': 168,
        'parsed': {
            'total_samples': 84,
            'adc_range': 10.0,
        }
    }
    handler._on_measurement_complete('AA:BB:CC:DD:EE:FF', stream_data)
    stats = handler.get_statistics()
    assert stats['measurements_completed'] == 1
    assert stats['devices_tracked'] == 1

    handler.print_statistics()
    output = capsys.readouterr().out
    assert 'Packets received' in output


def test_process_incoming_packet_paths(monkeypatch):
    handler = integration.BLEGatewayIntegration()

    def fake_receive(*_args, **_kwargs):
        return {'stream_id': 1}

    monkeypatch.setattr(handler.fetcher, 'receive_packet', fake_receive)
    assert handler.process_incoming_packet('AA:BB:CC:DD:EE:FF', b'\x00') is True

    monkeypatch.setattr(handler.fetcher, 'receive_packet', lambda *_args, **_kwargs: None)
    assert handler.process_incoming_packet('AA:BB:CC:DD:EE:FF', b'\x00') is False

    def raise_error(*_args, **_kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr(handler.fetcher, 'receive_packet', raise_error)
    assert handler.process_incoming_packet('AA:BB:CC:DD:EE:FF', b'\x00') is False


def test_example_helpers_run(capsys):
    integration.example_basic_usage()
    integration.example_deduplication()
    integration.example_stream_tracking()
    integration.example_integration_with_flask()
    output = capsys.readouterr().out
    assert 'Example' in output
