#!/usr/bin/env python3
"""
Example: How to integrate multipacket_ble with your existing gateway
"""
from multipacket_ble import MultiPacketBLEReceiver, parse_captouch_data
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create global receiver instance
ble_receiver = MultiPacketBLEReceiver(
    stream_timeout_seconds=60,
    dedup_timeout_seconds=120
)

# Register parsers for your data types
ble_receiver.register_parser(0xDD, parse_captouch_data)


def process_ble_data_with_multipacket(data, source="HTTP"):
    """
    Modified version of your process_ble_data() function.
    Add this to your ble_gtw_server.py
    """
    try:
        for device in data:
            device_id = device.get('id', 'unknown')
            device_name = device.get('name', 'Unknown')
            rssi = device.get('rssi', 0)
            advertising = device.get('advertising', {})

            # Check if device has manufacturer data
            manufacturer_data = advertising.get('manufacturerData')

            if manufacturer_data:
                # Try to process as multi-packet stream
                completed = ble_receiver.process_packet(
                    device_id=device_id,
                    manufacturer_data=manufacturer_data
                )

                if completed:
                    logger.info(f"🎉 Complete stream received from {device_name}!")
                    logger.info(f"   Stream ID: {completed['stream_id']}")
                    logger.info(f"   Data type: 0x{completed['data_type']:02X}")
                    logger.info(f"   Length: {completed['length']} bytes")

                    # If parsed data available
                    if 'parsed' in completed:
                        parsed = completed['parsed']
                        logger.info(f"   ADC range: {parsed.get('adc_range', 'N/A'):.1f} counts")
                        logger.info(f"   VDD avg: {parsed.get('vdd_avg', 'N/A'):.1f}")
                        logger.info(f"   GND avg: {parsed.get('gnd_avg', 'N/A'):.1f}")

                    # Save complete stream to database
                    # save_complete_stream_to_database(device_id, device_name, completed)

            # Periodic cleanup (every ~100 packets)
            if ble_receiver.stats['packets_received'] % 100 == 0:
                ble_receiver.cleanup()
                stats = ble_receiver.get_stats()
                logger.info(f"📊 Receiver stats: {stats}")

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)


def save_complete_stream_to_database(device_id, device_name, stream_data):
    """
    Save complete multi-packet stream to database.
    Add this to your ble_gtw_server.py
    """
    import sqlite3
    import json

    conn = sqlite3.connect('ble_gateway.db')
    cursor = conn.cursor()

    try:
        # You might want a separate table for complete streams
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS multipacket_streams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                device_id TEXT NOT NULL,
                device_name TEXT,
                stream_id INTEGER,
                data_type INTEGER,
                payload_length INTEGER,
                complete BOOLEAN,
                raw_data BLOB,
                parsed_data TEXT
            )
        ''')

        # Insert stream
        cursor.execute('''
            INSERT INTO multipacket_streams
            (device_id, device_name, stream_id, data_type, payload_length,
             complete, raw_data, parsed_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            device_id,
            device_name,
            stream_data['stream_id'],
            stream_data['data_type'],
            stream_data['length'],
            stream_data['complete'],
            stream_data['data'],
            json.dumps(stream_data.get('parsed', {}))
        ))

        conn.commit()
        logger.info(f"✓ Saved stream {stream_data['stream_id']} to database")

    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
    finally:
        conn.close()


if __name__ == '__main__':
    # Test with simulated device data (same format as your Android app sends)
    test_data = [
        {
            'id': 'AA:BB:CC:DD:EE:FF',
            'name': 'Hexagon Sensor 1',
            'rssi': -65,
            'advertising': {
                'manufacturerData': 'FFE5AA DD 0100 0E 00 00A8 05910590059305910594 0590'
                # Format: CompanyID Protocol DataType StreamID TotalPkts Seq PayloadLen [12 bytes payload]
            }
        }
    ]

    # Process it
    process_ble_data_with_multipacket(test_data)
