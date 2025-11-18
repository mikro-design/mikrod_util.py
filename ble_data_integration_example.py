#!/usr/bin/env python3
"""
Example: Integrating BLE Data Fetcher with Gateway Server

This example shows how to integrate the BLEDataFetcher into your Flask
gateway server to automatically deduplicate and reassemble BLE packets.

Features:
  - Automatic deduplication of 4× retransmissions
  - Multi-packet stream reassembly (14 packets → 84 samples)
  - Callbacks for completed measurements
  - Statistics tracking
  - Database storage of complete measurements
"""

import logging
from datetime import datetime
from multipacket_ble import BLEDataFetcher, extract_samples_from_stream

# Setup logging
logger = logging.getLogger(__name__)

# ============================================================================
# BLE FETCHER INTEGRATION
# ============================================================================

class BLEGatewayIntegration:
    """
    Integrates BLE data fetching with the gateway server.
    
    Handles:
      - Packet deduplication
      - Stream reassembly
      - Measurement completion callbacks
      - Statistics
    """
    
    def __init__(self):
        """Initialize the BLE data fetcher"""
        self.fetcher = BLEDataFetcher()
        
        # Register callback for completed measurements
        self.fetcher.on_stream_complete(self._on_measurement_complete)
        
        # Statistics
        self.measurements_completed = 0
        self.devices_tracked = set()
    
    def _on_measurement_complete(self, device_id: str, stream_data: dict):
        """Called when a complete measurement arrives"""
        self.measurements_completed += 1
        self.devices_tracked.add(device_id)
        
        logger.info(f"✓ Measurement complete from {device_id}")
        logger.info(f"  Stream ID: {stream_data['stream_id']}")
        logger.info(f"  Packets: {stream_data['packets_received']}/{stream_data['packets_expected']}")
        logger.info(f"  Data: {stream_data['length']} bytes (expected {stream_data['expected_length']})")
        
        if 'parsed' in stream_data:
            parsed = stream_data['parsed']
            logger.info(f"  Samples: {parsed['total_samples']}")
            logger.info(f"  ADC Range: {parsed['adc_range']:.1f}")
        
        # Note: You would store this in the database here
        # save_measurement_to_database(device_id, stream_data)
    
    def process_incoming_packet(self, device_id: str, packet_data: bytes) -> bool:
        """
        Process an incoming BLE packet.
        
        Args:
            device_id: Device MAC address
            packet_data: Raw BLE manufacturer data
        
        Returns:
            True if stream completed, False otherwise
        """
        try:
            result = self.fetcher.receive_packet(
                device_id=device_id,
                manufacturer_data=packet_data,
                timestamp=datetime.now()
            )
            
            if result:
                logger.debug(f"Stream {result['stream_id']} complete!")
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"Error processing packet from {device_id}: {e}", exc_info=True)
            return False
    
    def get_statistics(self) -> dict:
        """Get statistics on data processing"""
        stats = self.fetcher.get_stats()
        return {
            **stats,
            'measurements_completed': self.measurements_completed,
            'devices_tracked': len(self.devices_tracked),
        }
    
    def print_statistics(self):
        """Print formatted statistics"""
        stats = self.get_statistics()
        
        print("\n" + "=" * 60)
        print("BLE Data Fetcher Statistics")
        print("=" * 60)
        print(f"Packets received:        {stats['packets_received']}")
        print(f"Packets duplicate:       {stats['packets_duplicate']}")
        dup_rate = (stats['packets_duplicate'] / max(stats['packets_received'], 1)) * 100
        print(f"Duplicate rate:          {dup_rate:.1f}% (expected ~50%)")
        print(f"\nStreams completed:       {stats['streams_completed']}")
        print(f"Streams timeout:         {stats['streams_timeout']}")
        print(f"Active streams:          {stats['active_streams']}")
        print(f"\nMeasurements delivered:  {stats['measurements_completed']}")
        print(f"Devices tracked:         {stats['devices_tracked']}")
        print(f"Dedup cache size:        {stats['dedup_cache_size']}")
        print("=" * 60 + "\n")


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

def example_basic_usage():
    """Example 1: Basic packet processing"""
    print("\n" + "=" * 60)
    print("Example 1: Basic BLE Packet Processing")
    print("=" * 60)
    
    integration = BLEGatewayIntegration()
    
    # Simulate receiving BLE packets
    device_id = "AA:BB:CC:DD:EE:FF"
    
    # Example manufacturer data (would come from real BLE advertisement)
    # This is a simplified example - real packets are 42 bytes
    example_packet = bytes([
        0xE5, 0xFF,           # Company ID: 0xFFE5
        0xAA,                 # Protocol ID
        0xDD,                 # Data type: 0xDD (captouch)
        0x01, 0x00,           # MAC address (6 bytes)
        0x00, 0x00,
        0x00, 0x00,
        0xE8, 0x03,           # Stream ID: 1000
        0x0E,                 # Total packets: 14
        0x00,                 # Sequence: 0
        0xA8, 0x00,           # Payload length: 168
        # Payload: 6 samples (12 bytes per packet)
        0x05, 0x91, 0x05, 0x90, 0x05, 0x93,
        0x05, 0x91, 0x05, 0x94, 0x05, 0x90,
    ])
    
    # Process first packet
    print(f"\nProcessing packet from {device_id}...")
    result = integration.process_incoming_packet(device_id, example_packet)
    print(f"Stream complete: {result}")
    
    integration.print_statistics()


def example_deduplication():
    """Example 2: Demonstrating deduplication"""
    print("\n" + "=" * 60)
    print("Example 2: Deduplication of Retransmissions")
    print("=" * 60)
    
    integration = BLEGatewayIntegration()
    device_id = "AA:BB:CC:DD:EE:FF"
    
    # Simulate a packet that arrives 4 times (as per your hardware)
    test_packet = bytes([0xE5, 0xFF, 0xAA, 0xDD] + [0x00] * 38)
    
    print("\nSimulating 4× retransmission of same packet...")
    for i in range(4):
        result = integration.process_incoming_packet(device_id, test_packet)
        print(f"  Transmission {i+1}: received (duplicate={i > 0})")
    
    stats = integration.get_statistics()
    print(f"\nResult:")
    print(f"  Packets received: {stats['packets_received']}")
    print(f"  Duplicates detected: {stats['packets_duplicate']}")
    print(f"  Unique packets: {stats['packets_received'] - stats['packets_duplicate']}")


def example_stream_tracking():
    """Example 3: Tracking measurement cycles with stream IDs"""
    print("\n" + "=" * 60)
    print("Example 3: Stream ID Tracking")
    print("=" * 60)
    
    integration = BLEGatewayIntegration()
    device_id = "AA:BB:CC:DD:EE:FF"
    
    print("\nYour hardware sends data in measurement cycles:")
    print("  Every 21 seconds: Stream ID increments")
    print("  Each cycle: 14 packets × 6 samples = 84 samples total")
    print("  Transmitted: 56 times (14 packets × 4 retransmissions)")
    print("  Delivered: 14 packets (3 duplicates removed per packet)")
    
    print("\nExample stream sequence:")
    streams = [
        (1000, "21:00:00", "First measurement"),
        (1001, "21:00:21", "Second measurement"),
        (1002, "21:00:42", "Third measurement"),
        (1003, "21:01:03", "Fourth measurement"),
    ]
    
    for stream_id, timestamp, description in streams:
        print(f"  Stream {stream_id} @ {timestamp}: {description}")
    
    print("\nYou can track these to:")
    print("  ✓ Detect lost measurement cycles")
    print("  ✓ Verify continuous operation")
    print("  ✓ Trigger time-series analysis")


def example_integration_with_flask():
    """Example 4: Integration with Flask server"""
    print("\n" + "=" * 60)
    print("Example 4: Flask Integration")
    print("=" * 60)
    
    example_code = '''
# In your ble_gtw_server.py:

from multipacket_ble import BLEDataFetcher
from ble_data_integration_example import BLEGatewayIntegration

# Initialize at startup
ble_integration = BLEGatewayIntegration()

@app.route('/api/ble', methods=['POST'])
@require_api_key
def receive_ble_data():
    """Receive and process BLE packets"""
    data = request.get_json()
    
    for device in data:
        device_id = device.get('id')
        
        # Get manufacturer data (format depends on your Android app)
        # Could be in several places depending on your BLE advertisement format
        mfr_data = None
        
        if 'advertising' in device:
            adv = device['advertising']
            # Try different possible fields
            if 'manufacturer_data' in adv:
                mfr_data = bytes.fromhex(adv['manufacturer_data'])
            elif 'mfr_data' in adv:
                mfr_data = bytes.fromhex(adv['mfr_data'])
            elif 'raw' in adv:
                mfr_data = bytes.fromhex(adv['raw'])
        
        if mfr_data:
            # Process through deduplication/reassembly
            stream_complete = ble_integration.process_incoming_packet(
                device_id, mfr_data
            )
            
            if stream_complete:
                logger.info(f"Complete measurement received from {device_id}")
    
    # Return status
    stats = ble_integration.get_statistics()
    return jsonify({
        'status': 'success',
        'packets_received': stats['packets_received'],
        'duplicates': stats['packets_duplicate'],
        'streams_complete': stats['streams_completed']
    })

# Periodic stats logging
import threading
def log_stats_periodic():
    ble_integration.print_statistics()
    timer = threading.Timer(60, log_stats_periodic)
    timer.daemon = True
    timer.start()

log_stats_periodic()
'''
    
    print("\nCode example:\n")
    print(example_code)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("\n" + "=" * 60)
    print("BLE Data Fetcher Integration Examples")
    print("=" * 60)
    
    example_basic_usage()
    example_deduplication()
    example_stream_tracking()
    example_integration_with_flask()
    
    print("\n" + "=" * 60)
    print("Next Steps:")
    print("=" * 60)
    print("""
1. Review: Read BLE_DATA_FETCHING.md for detailed documentation
2. Integrate: Add BLEGatewayIntegration to your ble_gtw_server.py
3. Configure: Set up database storage for complete measurements
4. Test: Run with real BLE packets from your device
5. Monitor: Check statistics and adjust timeouts if needed
""")
    print("=" * 60 + "\n")
