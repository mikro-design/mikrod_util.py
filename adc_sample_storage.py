#!/usr/bin/env python3
"""
ADC Sample Storage - Store and retrieve ADC samples in database

Stores complete BLE measurements with ADC samples:
  - Raw 84 ADC samples
  - Computed statistics
  - Stream ID and metadata
  - Timestamp and device ID
"""

import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def init_adc_storage(db_file='ble_gateway.db'):
    """Initialize ADC samples table in database"""
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        table_schema = '''
            CREATE TABLE IF NOT EXISTS adc_measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                device_id TEXT NOT NULL,
                stream_id INTEGER,
                sample_count INTEGER,
                samples TEXT,
                stats TEXT,
                raw_bytes BLOB
            )
        '''

        # Migrate old schema with invalid foreign key if needed
        cursor.execute('''
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='adc_measurements'
        ''')
        table_exists = cursor.fetchone() is not None
        if table_exists:
            cursor.execute('PRAGMA foreign_key_list(adc_measurements)')
            if cursor.fetchall():
                cursor.execute('ALTER TABLE adc_measurements RENAME TO adc_measurements_old')
                cursor.execute(table_schema)
                cursor.execute('''
                    INSERT INTO adc_measurements
                    (id, timestamp, device_id, stream_id, sample_count, samples, stats, raw_bytes)
                    SELECT id, timestamp, device_id, stream_id, sample_count, samples, stats, raw_bytes
                    FROM adc_measurements_old
                ''')
                cursor.execute('DROP TABLE adc_measurements_old')
        else:
            cursor.execute(table_schema)
        
        # Create index for fast queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_adc_device_time
            ON adc_measurements(device_id, timestamp)
        ''')
        
        conn.commit()
        conn.close()
        logger.info("ADC storage table initialized")
        return True
    except Exception as e:
        logger.error(f"Error initializing ADC storage: {e}")
        return False


def store_adc_measurement(device_id: str, samples: List[int], 
                         stream_id: Optional[int] = None,
                         db_file='ble_gateway.db') -> Optional[int]:
    """
    Store a complete ADC measurement.
    
    Args:
        device_id: Device MAC address
        samples: List of 84 int16 ADC samples
        stream_id: Optional stream ID (measurement cycle)
        db_file: Database file path
    
    Returns:
        Measurement ID or None
    """
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # Compute statistics
        stats = {
            'min': min(samples),
            'max': max(samples),
            'mean': sum(samples) / len(samples),
            'range': max(samples) - min(samples),
        }
        
        # Store measurement
        cursor.execute('''
            INSERT INTO adc_measurements 
            (device_id, stream_id, sample_count, samples, stats)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            device_id,
            stream_id,
            len(samples),
            json.dumps(samples),
            json.dumps(stats)
        ))
        
        measurement_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Stored measurement {measurement_id}: {device_id}, {len(samples)} samples")
        return measurement_id
    
    except Exception as e:
        logger.error(f"Error storing ADC measurement: {e}")
        return None


def get_latest_measurement(device_id: str, db_file='ble_gateway.db') -> Optional[Dict]:
    """Get the latest measurement for a device"""
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, timestamp, device_id, stream_id, sample_count, samples, stats
            FROM adc_measurements
            WHERE device_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
        ''', (device_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                'id': row[0],
                'timestamp': row[1],
                'device_id': row[2],
                'stream_id': row[3],
                'sample_count': row[4],
                'samples': json.loads(row[5]),
                'stats': json.loads(row[6])
            }
    except Exception as e:
        logger.error(f"Error fetching measurement: {e}")
    
    return None


def get_measurements(device_id: str, hours: int = 1, limit: Optional[int] = None,
                    db_file='ble_gateway.db') -> List[Dict]:
    """Get recent measurements for a device"""
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        query = '''
            SELECT id, timestamp, device_id, stream_id, sample_count, samples, stats
            FROM adc_measurements
            WHERE device_id = ?
            AND timestamp > datetime('now', '-' || ? || ' hours')
            ORDER BY timestamp DESC
        '''
        params = [device_id, hours]
        
        if limit and isinstance(limit, int):
            query += f' LIMIT {limit}'
        
        cursor.execute(query, params)
        
        measurements = []
        for row in cursor.fetchall():
            measurements.append({
                'id': row[0],
                'timestamp': row[1],
                'device_id': row[2],
                'stream_id': row[3],
                'sample_count': row[4],
                'samples': json.loads(row[5]),
                'stats': json.loads(row[6])
            })
        
        conn.close()
        return measurements
    except Exception as e:
        logger.error(f"Error fetching measurements: {e}")
        return []


def get_all_devices(db_file='ble_gateway.db') -> List[str]:
    """Get all devices with measurements"""
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        cursor.execute('SELECT DISTINCT device_id FROM adc_measurements ORDER BY device_id')
        devices = [row[0] for row in cursor.fetchall()]
        conn.close()
        return devices
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")
        return []


class ADCMeasurementHandler:
    """
    Integration class for storing ADC measurements when BLE streams complete.
    
    Usage:
        handler = ADCMeasurementHandler()
        fetcher.on_stream_complete(handler.on_stream_complete)
    """
    
    def __init__(self, db_file='ble_gateway.db'):
        self.db_file = db_file
        init_adc_storage(db_file)
    
    def on_stream_complete(self, device_id: str, stream_data: Dict):
        """
        Callback when BLE stream completes.
        
        Extracts ADC samples and stores in database.
        """
        try:
            # Extract samples from parsed data
            if 'parsed' not in stream_data:
                logger.warning(f"No parsed data in stream from {device_id}")
                return
            
            parsed = stream_data['parsed']
            
            # Get all samples
            samples = (
                parsed.get('vdd_ref', []) +
                parsed.get('gnd_ref', []) +
                parsed.get('self_cap_raw', []) +
                parsed.get('mutual_cap_raw', [])
            )
            
            if len(samples) != 84:
                logger.warning(f"Unexpected sample count: {len(samples)}, expected 84")
                return
            
            # Store measurement
            meas_id = store_adc_measurement(
                device_id=device_id,
                samples=samples,
                stream_id=stream_data.get('stream_id'),
                db_file=self.db_file
            )
            
            if meas_id:
                logger.info(f"✓ Stored ADC measurement {meas_id} from {device_id}")
                logger.info(f"  {len(samples)} samples: min={min(samples)}, max={max(samples)}")
        
        except Exception as e:
            logger.error(f"Error storing ADC measurement: {e}", exc_info=True)


# ============================================================================
# EXAMPLE INTEGRATION
# ============================================================================

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 70)
    print("ADC Sample Storage Example")
    print("=" * 70)
    
    # Initialize storage
    init_adc_storage()
    print("✓ Storage initialized")
    
    # Simulate storing measurements
    device_id = "AA:BB:CC:DD:EE:FF"
    
    # Create fake ADC samples
    import random
    samples = [random.randint(-2000, 2000) for _ in range(84)]
    
    meas_id = store_adc_measurement(device_id, samples, stream_id=1000)
    print(f"✓ Stored measurement {meas_id}")
    
    # Retrieve and display
    latest = get_latest_measurement(device_id)
    if latest:
        print(f"\nLatest measurement:")
        print(f"  Time: {latest['timestamp']}")
        print(f"  Stream: {latest['stream_id']}")
        print(f"  Samples: {latest['sample_count']}")
        print(f"  Stats: {latest['stats']}")
    
    print("\n" + "=" * 70)
    print("Usage in Flask server:")
    print("=" * 70)
    print("""
from adc_sample_storage import ADCMeasurementHandler
from multipacket_ble import BLEDataFetcher

# Initialize handler and fetcher
adc_handler = ADCMeasurementHandler()
fetcher = BLEDataFetcher()

# Register callback
fetcher.on_stream_complete(adc_handler.on_stream_complete)

# Now when BLE streams complete, ADC samples are automatically stored!
    """)
