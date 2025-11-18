# BLE Data Fetching with Automatic Deduplication

## Overview

This guide explains how to fetch BLE sensor data while automatically handling deduplication of repeated frames. Your hardware transmits data using a sophisticated redundancy strategy:

- **14 packets per measurement** (each containing 6 ADC samples = 12 bytes)
- **4× retransmissions** per packet (56 total transmissions per cycle)
- **~21-second cycles** between measurements
- **Result: 84 total samples** (168 bytes) per measurement cycle

## Why Deduplication is Critical

Without deduplication, you would receive:
- Packet 0: 4 copies (retransmissions)
- Packet 1: 4 copies
- ... (×14 packets)
- **Result: 56 identical data packets that must be deduplicated**

The system automatically handles this and only delivers unique packets.

## Quick Start

### Basic Usage

```python
from multipacket_ble import BLEDataFetcher

# Create fetcher with automatic deduplication
fetcher = BLEDataFetcher()

# Register callback for completed measurements
def on_measurement_complete(device_id, stream_data):
    print(f"Device {device_id}: {stream_data['data_type']:02x}")
    if 'parsed' in stream_data:
        parsed = stream_data['parsed']
        print(f"  Total samples: {parsed['total_samples']}")
        print(f"  VDD range: {parsed['adc_range']:.1f}")

fetcher.on_stream_complete(on_measurement_complete)

# Process incoming packets (raw from BLE advertisement)
result = fetcher.receive_packet(
    device_id='AA:BB:CC:DD:EE:FF',
    manufacturer_data=raw_ble_data,
    timestamp=datetime.now()
)

if result:
    # Stream completed - all 14 packets received, deduplicated
    print(f"Measurement complete: {result['length']} bytes")
    samples = result['parsed']['self_cap_raw']
    print(f"Self-cap samples: {samples}")
```

## How Deduplication Works

### Packet-Level Deduplication

Each packet is identified by:
```
Key = (device_id, stream_id, sequence_number)
```

The system remembers all received packets for 2 minutes. When a duplicate arrives, it's automatically discarded.

**Example:**
```
Packet 1 arrives → stored
Packet 1 arrives again (retransmission) → rejected (duplicate)
Packet 1 arrives again (retransmission) → rejected (duplicate)
Packet 1 arrives again (retransmission) → rejected (duplicate)
```

### Stream Assembly

Once all 14 unique packets arrive, they're automatically reassembled in order:

```
Packet 0: samples 0-5
Packet 1: samples 6-11
Packet 2: samples 12-17
... (14 packets total)
Packet 13: samples 78-83
Result: 84 samples complete ✓
```

### Stream ID Tracking

Stream IDs increment every 21 seconds:

```
21:00:00 - Stream ID 1000 → 84 samples delivered
21:00:21 - Stream ID 1001 → 84 new samples delivered
21:00:42 - Stream ID 1002 → 84 new samples delivered
...
```

You can use stream IDs to detect measurement cycles and ensure no samples are lost.

## Packet Structure Reference

### Physical Layer
- **Frequency:** Channel 37 (2402 MHz - BLE advertising channel)
- **Modulation:** 1 Mbps BLE
- **CRC:** 24-bit CRC
- **Whitening:** Data whitening applied

### BLE Advertisement Structure (42 bytes)
```
Bytes  0-15:  BLE PDU header
Bytes 16+:    Manufacturer-specific data
  [16]:      Protocol version (0xDD = raw mode)
  [17-23]:   Reserved
  [24-25]:   Stream ID (little-endian)
  [26]:      Reserved  
  [27]:      Packet number (0-13)
  [28]:      Reserved
  [29]:      Total packets (14)
  [30-41]:   ADC Samples (6 × int16, big-endian, 12 bytes)
```

### Sample Encoding
Each 16-bit sample is big-endian signed integer:
```
Byte N:     MSB (most significant byte)
Byte N+1:   LSB (least significant byte)

Formula: (MSB << 8) | LSB
Range: -2048 to +2047

Example: 0x0591 = (0x05 << 8) | 0x91 = 1425
```

## Data Flow

### Step 1: Raw BLE Advertisement
```
BLE packet from device:
  Device: AA:BB:CC:DD:EE:FF
  RSSI: -65 dBm
  Manufacturer data: FFE5 AA DD ... (42 bytes)
```

### Step 2: Duplicate Detection
```
Extract key: (AA:BB:CC:DD:EE:FF, stream_id=1000, seq=0)
Check: Is this packet already seen?
  - NO: Add to stream, continue
  - YES: Discard (duplicate)
```

### Step 3: Stream Assembly
```
Stream 1000 state:
  Packet 0: received ✓
  Packet 1: received ✓
  Packet 2: received ✓
  ... (11 more packets needed)
```

### Step 4: Completion & Parsing
```
All 14 packets received!
  Reassemble: 84 samples
  Parse: VDD reference, GND reference, self-cap, mutual-cap
  Invoke: Callbacks with complete data
  Return: Structured measurement
```

## Integration with Gateway Server

The BLE fetcher integrates seamlessly with the Flask server:

```python
# In ble_gtw_server.py

from multipacket_ble import BLEDataFetcher

# Initialize at startup
ble_fetcher = BLEDataFetcher()

def on_ble_stream_complete(device_id, stream_data):
    """Called when a complete BLE measurement arrives"""
    logger.info(f"Complete measurement from {device_id}")
    
    # Extract the data
    if 'parsed' in stream_data:
        parsed = stream_data['parsed']
        samples = parsed['self_cap_raw']
        
        # Process/store as needed
        save_samples_to_database(device_id, samples)

ble_fetcher.on_stream_complete(on_ble_stream_complete)

@app.route('/api/ble', methods=['POST'])
@require_api_key
def receive_ble_data():
    """Modified to use BLE fetcher"""
    data = request.get_json()
    
    for device_data in data:
        device_id = device_data.get('id')
        mfr_data = device_data.get('advertising', {}).get('mfr_data')
        
        if mfr_data:
            # Process through fetcher
            result = ble_fetcher.receive_packet(device_id, mfr_data)
            
            if result:
                # Stream completed!
                logger.info(f"Got {result['packets_received']}/{result['packets_expected']} packets")
    
    # Return stats
    stats = ble_fetcher.get_stats()
    return jsonify({
        'status': 'received',
        'dedup_stats': stats
    })
```

## Validation Checklist

When a stream completes, verify:

### ✓ Data Integrity
```python
result = fetcher.receive_packet(device_id, data)
if result:
    assert result['complete'] == True          # All packets received
    assert result['length'] == 168             # Exactly 168 bytes
    assert len(result['missing_packets']) == 0 # No gaps
    assert result['packets_received'] == 14    # All 14 packets
```

### ✓ Sample Validation
```python
parsed = result['parsed']
assert len(parsed['vdd_ref']) == 8       # VDD: 8 samples
assert len(parsed['gnd_ref']) == 8       # GND: 8 samples  
assert len(parsed['self_cap_raw']) == 34 # Self-cap: 34 samples
assert len(parsed['mutual_cap_raw']) == 34 # Mutual: 34 samples
assert parsed['adc_range'] > 100         # Reasonable voltage range
```

### ✓ Deduplication Metrics
```python
stats = fetcher.get_stats()
print(f"Packets received: {stats['packets_received']}")
print(f"Packets duplicate: {stats['packets_duplicate']} (should be ~50% of received)")
print(f"Streams completed: {stats['streams_completed']}")
print(f"Active streams: {stats['active_streams']}")
```

Expected duplication rate: **~50%** (4 copies received, 3 are duplicates).

## Advanced Usage

### Custom Parsing

To handle different data types:

```python
def parse_custom_data(data: bytes) -> Dict:
    """Parse custom sensor format"""
    # Your parsing logic
    return {'custom': 'data'}

fetcher.receiver.register_parser(0xAA, parse_custom_data)
```

### Timeout Handling

Incomplete streams timeout after 30 seconds:

```python
# Automatic cleanup happens in background
# To manually trigger:
fetcher.receiver.cleanup()

# Check for timeouts:
stats = fetcher.get_stats()
if stats['streams_timeout'] > 0:
    print(f"Warning: {stats['streams_timeout']} streams timed out")
```

### Performance Monitoring

```python
def log_stats():
    stats = fetcher.get_stats()
    print(f"Processing:")
    print(f"  Packets: {stats['packets_received']}")
    print(f"  Duplicates: {stats['packets_duplicate']}")
    print(f"  Complete streams: {stats['streams_completed']}")
    print(f"  Timeouts: {stats['streams_timeout']}")
    print(f"  Active: {stats['active_streams']}")
    print(f"  Cache size: {stats['dedup_cache_size']}")

# Schedule periodic logging
import threading
timer = threading.Timer(60, log_stats)
timer.daemon = True
timer.start()
```

## Troubleshooting

### Problem: Streams not completing

**Check:**
1. Are all 14 packets arriving?
   ```python
   stats = fetcher.get_stats()
   if stats['packets_received'] < 14:
       print("Not all packets received")
   ```

2. Is the device sending continuously?
   ```python
   # Add timestamp logging
   fetcher.receive_packet(device_id, data, timestamp=datetime.now())
   ```

3. Check stream timeout setting
   ```python
   # Default: 30 seconds. May need adjustment for slow networks
   fetcher.receiver.stream_timeout  # Check value
   ```

### Problem: High duplicate rate

**Check:**
1. Are retransmissions working as expected?
   ```python
   stats = fetcher.get_stats()
   dup_rate = stats['packets_duplicate'] / stats['packets_received']
   # Expected: ~0.5 (50% are duplicates)
   ```

2. Dedup cache might be too small
   ```python
   stats = fetcher.get_stats()
   if stats['dedup_cache_size'] > 5000:
       print("Warning: Large dedup cache")
   ```

### Problem: Memory usage growing

The dedup cache grows over time. Ensure cleanup is running:

```python
# Should be automatic, but verify:
stats = fetcher.get_stats()
print(f"Dedup cache: {stats['dedup_cache_size']} entries")

# Manually trigger cleanup if needed:
fetcher.receiver.cleanup()
```

## Performance Characteristics

### Latency
- Per packet: ~1-2 ms processing
- Per stream: ~21 seconds (natural measurement cycle)
- Deduplication: Zero additional latency

### Memory
- Per active stream: ~500 bytes
- Per cached packet: ~50 bytes  
- Expected: <1 MB for typical use

### CPU
- Per packet: Negligible (<1% on modern CPU)
- Cleanup thread: Periodic, <1% average

## Next Steps

1. **Integration:** Add `BLEDataFetcher` to your Flask server
2. **Database:** Store the parsed 84 samples in your SQLite database
3. **Visualization:** Plot time-series of samples over multiple measurement cycles
4. **Analysis:** Apply signal processing (filtering, features, etc.)

See `ble_gtw_server.py` for integration examples.
