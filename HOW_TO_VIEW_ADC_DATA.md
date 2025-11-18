# How to View ADC Sample Data

Your system now captures 84 ADC samples per measurement cycle. Here are all the ways to view them:

## Quick Answer: Three Methods

### Method 1: Command Line Tool (Easiest)

```bash
# List all devices
python3 view_adc_samples.py list

# Show latest measurement
python3 view_adc_samples.py latest

# Show latest from specific device
python3 view_adc_samples.py latest AA:BB:CC:DD:EE:FF

# Show statistics and waveform plot
python3 view_adc_samples.py stats AA:BB:CC:DD:EE:FF

# Show recent measurements
python3 view_adc_samples.py show AA:BB:CC:DD:EE:FF
```

### Method 2: Python API

```python
from adc_sample_storage import (
    get_latest_measurement,
    get_measurements,
    get_all_devices
)

# Get latest measurement
data = get_latest_measurement('AA:BB:CC:DD:EE:FF')
print(f"Samples: {data['samples']}")
print(f"Stats: {data['stats']}")

# Get last 10 measurements
measurements = get_measurements('AA:BB:CC:DD:EE:FF', hours=24, limit=10)
for m in measurements:
    print(f"{m['timestamp']}: min={m['stats']['min']}, max={m['stats']['max']}")

# Get all devices with data
devices = get_all_devices()
for dev in devices:
    print(f"Device: {dev}")
```

### Method 3: Flask Integration

```python
from adc_sample_storage import ADCMeasurementHandler
from multipacket_ble import BLEDataFetcher

# Create handler and fetcher
adc_handler = ADCMeasurementHandler()
fetcher = BLEDataFetcher()

# Register callback - automatic storage when stream completes
fetcher.on_stream_complete(adc_handler.on_stream_complete)

# In your Flask route
@app.route('/api/ble', methods=['POST'])
def receive_ble_data():
    data = request.get_json()
    for device in data:
        device_id = device.get('id')
        mfr_data = device.get('advertising', {}).get('mfr_data')
        
        if mfr_data:
            result = fetcher.receive_packet(device_id, mfr_data)
            # Measurement stored automatically if complete!
    
    return jsonify({'status': 'ok'})
```

## Data Structure

Each stored measurement contains:

```python
{
    'id': 42,                          # Database ID
    'timestamp': '2025-11-18 12:34:56', # When captured
    'device_id': 'AA:BB:CC:DD:EE:FF',   # Device MAC
    'stream_id': 1000,                 # Measurement cycle ID
    'sample_count': 84,                # Always 84 for captouch
    'samples': [                       # The 84 ADC samples
        1425, 1424, 1427, 1425, ...    # int16 values (-2048 to +2047)
    ],
    'stats': {
        'min': -2048,                  # Minimum sample value
        'max': 2047,                   # Maximum sample value
        'mean': 1425.5,                # Average
        'range': 4095                  # Max - Min
    }
}
```

## Sample Breakdown (84 total samples)

The 84 samples are organized as:

- **Samples 0-7**: VDD reference (8 samples)
- **Samples 8-15**: GND reference (8 samples)
- **Samples 16-49**: Self-capacitance raw (34 samples)
- **Samples 50-83**: Mutual-capacitance raw (34 samples)

You can access them via the `parsed` structure:

```python
from multipacket_ble import extract_samples_from_stream

# When stream completes
result = fetcher.receive_packet(device_id, ble_data)
if result:
    samples = extract_samples_from_stream(result)
    # samples is list of 84 values
    
    # Or access by type
    vdd_ref = result['parsed']['vdd_ref']        # 8 samples
    gnd_ref = result['parsed']['gnd_ref']        # 8 samples
    self_cap = result['parsed']['self_cap_raw']  # 34 samples
    mutual_cap = result['parsed']['mutual_cap_raw']  # 34 samples
```

## Real-Time Monitoring

View data as it arrives:

```python
import logging
logging.basicConfig(level=logging.INFO)

# Enable debug logging
from multipacket_ble import logger as ble_logger
ble_logger.setLevel(logging.DEBUG)

# Server logs show:
# INFO: ✓ Stream 1000 complete: 168 bytes
# INFO: Measurement stored: min=1200, max=1650
```

## Viewing Database Directly

```bash
# Query database with sqlite3
sqlite3 ble_gateway.db

# List all measurements
sqlite3 ble_gateway.db "SELECT timestamp, device_id, stats FROM adc_measurements LIMIT 10;"

# Export to CSV
sqlite3 ble_gateway.db ".mode csv" "SELECT timestamp, device_id, sample_count FROM adc_measurements;" > data.csv

# Count measurements per device
sqlite3 ble_gateway.db "SELECT device_id, COUNT(*) FROM adc_measurements GROUP BY device_id;"
```

## Troubleshooting

### No data appearing?

1. Check if server is running:
   ```bash
   python3 ble_gtw_server.py
   ```

2. Check if measurements are being captured:
   ```bash
   python3 view_adc_samples.py list
   ```

3. Check server logs:
   ```bash
   tail -f ble_gateway.log
   ```

### Missing samples?

```python
from adc_sample_storage import get_latest_measurement

data = get_latest_measurement('AA:BB:CC:DD:EE:FF')
print(f"Got {data['sample_count']} samples (expected 84)")
print(f"Stats: {data['stats']}")
```

### Want to export all data?

```python
from adc_sample_storage import get_measurements
import csv

measurements = get_measurements('AA:BB:CC:DD:EE:FF', hours=24)

with open('export.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['timestamp', 'device_id', 'min', 'max', 'mean'])
    writer.writeheader()
    for m in measurements:
        writer.writerow({
            'timestamp': m['timestamp'],
            'device_id': m['device_id'],
            'min': m['stats']['min'],
            'max': m['stats']['max'],
            'mean': m['stats']['mean']
        })
```

## Next Steps

1. **View existing data**: `python3 view_adc_samples.py list`
2. **Analyze samples**: `python3 view_adc_samples.py stats <device>`
3. **Store new data**: Integrate `ADCMeasurementHandler` with Flask server
4. **Process samples**: Write analysis code using the Python API
5. **Visualize trends**: Export data and use plotting tools

## Complete Integration Example

```python
#!/usr/bin/env python3
"""Complete example: Capture and view ADC samples"""

from flask import Flask, request, jsonify
from adc_sample_storage import ADCMeasurementHandler
from multipacket_ble import BLEDataFetcher
import logging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
adc_handler = ADCMeasurementHandler()
fetcher = BLEDataFetcher()

# Automatic storage when stream completes
fetcher.on_stream_complete(adc_handler.on_stream_complete)

@app.route('/api/ble', methods=['POST'])
def receive_ble_data():
    """Receive BLE packets"""
    data = request.get_json()
    
    for device in data:
        device_id = device.get('id')
        mfr_data = device.get('advertising', {}).get('mfr_data')
        
        if mfr_data:
            # Process packet (deduplicates automatically)
            result = fetcher.receive_packet(device_id, mfr_data)
            
            if result:
                # Stream complete! Samples stored automatically
                print(f"✓ Measurement complete: {result['length']} bytes")
    
    return jsonify({'status': 'ok'})

@app.route('/api/samples/<device_id>', methods=['GET'])
def get_samples(device_id):
    """Get latest samples for device"""
    from adc_sample_storage import get_latest_measurement
    
    data = get_latest_measurement(device_id)
    if data:
        return jsonify(data)
    return jsonify({'error': 'No data'}), 404

if __name__ == '__main__':
    app.run(debug=True)
```

Then access: `http://localhost:5000/api/samples/AA:BB:CC:DD:EE:FF`
