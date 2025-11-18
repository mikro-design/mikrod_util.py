#!/usr/bin/env python3
"""
Generic Multi-Packet BLE Data Receiver
Handles reassembly of data transmitted across multiple BLE advertising packets
with automatic deduplication of repeated frames
"""
import struct
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, List, Callable

logger = logging.getLogger(__name__)


class MultiPacketBLEReceiver:
    """
    Generic receiver for multi-packet BLE transmissions with deduplication.

    Handles:
    - Automatic deduplication of repeated advertising frames
    - Multi-packet data reassembly
    - Timeout cleanup of incomplete streams
    - Pluggable parsers for different data types
    """

    # Protocol constants
    COMPANY_ID = 0xFFE5
    PROTOCOL_ID = 0xAA

    # Data types
    DATA_TYPE_LEGACY = 0x01      # Single packet sensor data
    DATA_TYPE_BINARY = 0x02      # Multi-packet binary stream
    DATA_TYPE_JSON = 0x03        # Multi-packet JSON
    DATA_TYPE_CAPTOUCH = 0xDD    # Raw capacitive touch samples

    def __init__(self,
                 stream_timeout_seconds=60,
                 dedup_timeout_seconds=120,
                 auto_cleanup=True,
                 cleanup_interval_seconds=10):
        """
        Args:
            stream_timeout_seconds: How long to wait for incomplete streams
            dedup_timeout_seconds: How long to remember seen packets
            auto_cleanup: Enable automatic cleanup thread (default: True)
            cleanup_interval_seconds: How often to run cleanup (default: 10)
        """
        self.stream_timeout = timedelta(seconds=stream_timeout_seconds)
        self.dedup_timeout = timedelta(seconds=dedup_timeout_seconds)

        # Active streams being assembled
        self.streams = {}  # {(device_id, stream_id): StreamBuffer}

        # Deduplication tracking
        self.seen_packets = {}  # {(device_id, stream_id, sequence): timestamp}

        # Completed streams ready for retrieval
        self.completed_streams = []

        # Data type parsers
        self.parsers = {}  # {data_type: parser_function}

        # Statistics
        self.stats = {
            'packets_received': 0,
            'packets_duplicate': 0,
            'streams_completed': 0,
            'streams_timeout': 0,
            'parse_errors': 0
        }

        # Automatic cleanup thread
        self._cleanup_thread = None
        self._cleanup_stop_event = threading.Event()
        if auto_cleanup:
            self._start_cleanup_thread(cleanup_interval_seconds)

    def register_parser(self, data_type: int, parser_func: Callable):
        """
        Register a parser function for a specific data type.

        Args:
            data_type: Data type byte (e.g., 0xDD for captouch)
            parser_func: Function that takes (data_bytes) and returns parsed dict
        """
        self.parsers[data_type] = parser_func
        logger.info(f"Registered parser for data type 0x{data_type:02X}")

    def _start_cleanup_thread(self, interval_seconds):
        """Start automatic cleanup background thread"""
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            args=(interval_seconds,),
            daemon=True,
            name="MultiPacketBLE-Cleanup"
        )
        self._cleanup_thread.start()
        logger.debug(f"Started automatic cleanup thread (interval: {interval_seconds}s)")

    def _cleanup_loop(self, interval_seconds):
        """Background cleanup loop"""
        while not self._cleanup_stop_event.is_set():
            self.cleanup()
            self._cleanup_stop_event.wait(interval_seconds)

    def stop(self):
        """Stop automatic cleanup thread"""
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            logger.debug("Stopping cleanup thread...")
            self._cleanup_stop_event.set()
            self._cleanup_thread.join(timeout=5)
            logger.debug("Cleanup thread stopped")

    def __del__(self):
        """Cleanup when object is destroyed"""
        self.stop()

    def process_packet(self, device_id: str, manufacturer_data, timestamp=None) -> Optional[Dict]:
        """
        Process a single BLE advertising packet.

        Args:
            device_id: Device MAC address or identifier
            manufacturer_data: Raw manufacturer data (hex string or bytes)
            timestamp: Packet timestamp (defaults to now)

        Returns:
            dict: Completed stream data if this packet completed a stream, None otherwise
        """
        self.stats['packets_received'] += 1

        if timestamp is None:
            timestamp = datetime.now()

        try:
            # Parse manufacturer data
            data_bytes = self._parse_manufacturer_data(manufacturer_data)
            if data_bytes is None:
                return None

            # Parse packet header
            header = self._parse_packet_header(data_bytes)
            if header is None:
                return None

            # Check for duplicate packet
            if self._is_duplicate(device_id, header, timestamp):
                self.stats['packets_duplicate'] += 1
                logger.debug(f"Duplicate packet: stream {header['stream_id']}, seq {header['sequence']}")
                return None

            # Mark packet as seen
            self._mark_seen(device_id, header, timestamp)

            # Get or create stream buffer
            stream_key = (device_id, header['stream_id'])
            if stream_key not in self.streams:
                self.streams[stream_key] = StreamBuffer(
                    device_id=device_id,
                    stream_id=header['stream_id'],
                    data_type=header['data_type'],
                    total_packets=header['total_packets'],
                    payload_length=header['payload_length'],
                    timestamp=timestamp
                )

            stream = self.streams[stream_key]

            # Add packet data to stream
            stream.add_packet(header['sequence'], header['payload'])

            logger.debug(f"Stream {header['stream_id']}: packet {header['sequence']+1}/{header['total_packets']} "
                        f"({stream.bytes_received()}/{header['payload_length']} bytes)")

            # Check if stream is complete
            if stream.is_complete():
                logger.info(f"✓ Stream {header['stream_id']} complete: {stream.bytes_received()} bytes, "
                           f"type 0x{header['data_type']:02X}")

                # Get complete data
                complete_data = stream.get_data()

                # Parse if parser available
                if header['data_type'] in self.parsers:
                    try:
                        parsed = self.parsers[header['data_type']](complete_data['data'])
                        complete_data['parsed'] = parsed
                    except Exception as e:
                        logger.error(f"Parser error for type 0x{header['data_type']:02X}: {e}")
                        self.stats['parse_errors'] += 1

                # Clean up
                del self.streams[stream_key]
                self.stats['streams_completed'] += 1

                # Store for retrieval
                self.completed_streams.append(complete_data)

                return complete_data

            return None

        except Exception as e:
            logger.error(f"Error processing packet: {e}", exc_info=True)
            return None

    def cleanup(self, now=None):
        """
        Remove old incomplete streams and deduplication entries.
        Call periodically (e.g., every 10 seconds).
        """
        if now is None:
            now = datetime.now()

        # Cleanup incomplete streams
        to_remove = []
        for key, stream in self.streams.items():
            if now - stream.first_packet_time > self.stream_timeout:
                logger.warning(f"Timeout: Stream {stream.stream_id} incomplete "
                             f"({stream.packets_received()}/{stream.total_packets} packets)")
                to_remove.append(key)
                self.stats['streams_timeout'] += 1

        for key in to_remove:
            del self.streams[key]

        # Cleanup deduplication cache
        to_remove = []
        for key, timestamp in self.seen_packets.items():
            if now - timestamp > self.dedup_timeout:
                to_remove.append(key)

        for key in to_remove:
            del self.seen_packets[key]

        logger.debug(f"Cleanup: removed {len(to_remove)} old dedup entries")

    def get_completed_stream(self) -> Optional[Dict]:
        """Get and remove the oldest completed stream"""
        if self.completed_streams:
            return self.completed_streams.pop(0)
        return None

    def get_stats(self) -> Dict:
        """Get receiver statistics"""
        return {
            **self.stats,
            'active_streams': len(self.streams),
            'dedup_cache_size': len(self.seen_packets),
            'completed_pending': len(self.completed_streams)
        }

    def _parse_manufacturer_data(self, manufacturer_data) -> Optional[bytes]:
        """Convert manufacturer data to bytes"""
        try:
            if isinstance(manufacturer_data, bytes):
                return manufacturer_data
            elif isinstance(manufacturer_data, str):
                # Remove common prefixes and whitespace
                cleaned = manufacturer_data.replace('0x', '').replace(' ', '').replace(':', '')
                return bytes.fromhex(cleaned)
            else:
                logger.warning(f"Unknown manufacturer data type: {type(manufacturer_data)}")
                return None
        except Exception as e:
            logger.error(f"Error parsing manufacturer data: {e}")
            return None

    def _parse_packet_header(self, data_bytes: bytes) -> Optional[Dict]:
        """Parse packet header and extract fields"""
        # Minimum packet size: header (10 bytes) + at least some payload
        if len(data_bytes) < 10:
            logger.debug(f"Packet too short: {len(data_bytes)} bytes")
            return None

        try:
            # Parse header
            # Manufacturer data format:
            # [0-1]: Company ID (0xFFE5)
            # [2]: Protocol ID (0xAA)
            # [3]: Data type (0xDD for raw captouch)
            # [4-9]: MAC address (6 bytes)
            # [10]: Stream ID low
            # [11]: Stream ID high
            # [12]: Total packets
            # [13]: Sequence
            # [14-15]: Payload length
            # [16+]: Sample data

            company_id = struct.unpack('<H', data_bytes[0:2])[0]
            protocol_id = data_bytes[2]
            data_type = data_bytes[3]
            # Skip MAC at [4-9]
            stream_id = struct.unpack('<H', data_bytes[10:12])[0]
            total_packets = data_bytes[12]
            sequence = data_bytes[13]
            payload_length = struct.unpack('<H', data_bytes[14:16])[0]

            # Verify protocol
            if company_id != self.COMPANY_ID:
                logger.debug(f"Unknown company ID: 0x{company_id:04X}")
                return None

            if protocol_id != self.PROTOCOL_ID:
                logger.debug(f"Unknown protocol ID: 0x{protocol_id:02X}")
                return None

            # Validate fields
            if sequence >= total_packets:
                logger.warning(f"Invalid sequence {sequence} >= total {total_packets}")
                return None

            # Extract payload
            payload = data_bytes[16:]

            return {
                'data_type': data_type,
                'stream_id': stream_id,
                'total_packets': total_packets,
                'sequence': sequence,
                'payload_length': payload_length,
                'payload': payload
            }

        except Exception as e:
            logger.error(f"Error parsing header: {e}")
            return None

    def _is_duplicate(self, device_id: str, header: Dict, timestamp: datetime) -> bool:
        """Check if this packet has been seen before"""
        key = (device_id, header['stream_id'], header['sequence'])
        return key in self.seen_packets

    def _mark_seen(self, device_id: str, header: Dict, timestamp: datetime):
        """Mark a packet as seen"""
        key = (device_id, header['stream_id'], header['sequence'])
        self.seen_packets[key] = timestamp


class StreamBuffer:
    """Buffer for assembling a single multi-packet stream"""

    def __init__(self, device_id: str, stream_id: int, data_type: int,
                 total_packets: int, payload_length: int, timestamp: datetime):
        self.device_id = device_id
        self.stream_id = stream_id
        self.data_type = data_type
        self.total_packets = total_packets
        self.payload_length = payload_length
        self.first_packet_time = timestamp

        # Packet storage
        self.packets = {}  # {sequence: payload_bytes}

    def add_packet(self, sequence: int, payload: bytes):
        """Add a packet's payload"""
        if sequence in self.packets:
            logger.warning(f"Overwriting duplicate packet {sequence} for stream {self.stream_id}")
        self.packets[sequence] = payload

    def is_complete(self) -> bool:
        """Check if all packets received"""
        return len(self.packets) == self.total_packets

    def packets_received(self) -> int:
        """Number of packets received"""
        return len(self.packets)

    def bytes_received(self) -> int:
        """Total bytes received"""
        return sum(len(payload) for payload in self.packets.values())

    def get_data(self) -> Dict:
        """Get complete stream data"""
        # Reconstruct data in order
        data_bytes = bytearray()
        missing = []

        for seq in range(self.total_packets):
            if seq in self.packets:
                data_bytes.extend(self.packets[seq])
            else:
                missing.append(seq)

        # Trim to expected length
        if len(data_bytes) > self.payload_length:
            data_bytes = data_bytes[:self.payload_length]

        if missing:
            logger.error(f"Stream {self.stream_id} missing packets: {missing}")

        return {
            'device_id': self.device_id,
            'stream_id': self.stream_id,
            'data_type': self.data_type,
            'timestamp': self.first_packet_time.isoformat(),
            'data': bytes(data_bytes),
            'length': len(data_bytes),
            'expected_length': self.payload_length,
            'packets_received': len(self.packets),
            'packets_expected': self.total_packets,
            'complete': len(missing) == 0,
            'missing_packets': missing
        }


# Example parsers for different data types

def parse_captouch_data(data: bytes) -> Dict:
     """
     Parser for capacitive touch raw samples (data_type=0xDD)

     Expected format: 84 int16_t samples (168 bytes)
     Transmitted as: 14 packets × 12 bytes (6 samples) per packet
     """
     if len(data) < 168:
         raise ValueError(f"Incomplete captouch data: {len(data)}/168 bytes")

     # Parse samples (big-endian signed int16)
     samples = []
     for i in range(84):
         offset = i * 2
         sample = struct.unpack('>h', data[offset:offset+2])[0]
         samples.append(sample)

     # Structure the data
     result = {
         'total_samples': len(samples),
         'vdd_ref': samples[0:8],
         'gnd_ref': samples[8:16],
         'self_cap_raw': samples[16:50],
         'mutual_cap_raw': samples[50:84],
     }

     # Calculate averages
     result['vdd_avg'] = sum(result['vdd_ref']) / len(result['vdd_ref'])
     result['gnd_avg'] = sum(result['gnd_ref']) / len(result['gnd_ref'])
     result['adc_range'] = result['vdd_avg'] - result['gnd_avg']

     return result


class BLEDataFetcher:
     """
     High-level interface for fetching BLE data with automatic deduplication.
     
     Handles the complete workflow:
     - Deduplication of 4× retransmissions per packet
     - Multi-packet stream reassembly (14 packets → 84 samples)
     - Stream ID tracking to detect measurement cycles
     - Automatic data validation
     
     Usage:
         fetcher = BLEDataFetcher()
         
         # Process incoming BLE advertisement packets
         result = fetcher.receive_packet(
             device_id='AA:BB:CC:DD:EE:FF',
             manufacturer_data=raw_bytes
         )
         
         if result:
             print(f"Complete stream: {result['samples']}")
     """
     
     def __init__(self):
         """Initialize fetcher with deduplication and reassembly"""
         self.receiver = MultiPacketBLEReceiver(
             stream_timeout_seconds=30,  # Complete within 30s window
             dedup_timeout_seconds=120,  # Remember duplicates for 2 minutes
             auto_cleanup=True,
             cleanup_interval_seconds=5
         )
         # Register the captouch parser
         self.receiver.register_parser(0xDD, parse_captouch_data)
         
         # Track stream IDs per device to detect new measurement cycles
         self.device_stream_history = {}  # {device_id: last_stream_id}
         self.stream_callbacks = []  # List of callbacks for completed streams
     
     def on_stream_complete(self, callback: Callable):
         """Register callback for when a stream completes"""
         self.stream_callbacks.append(callback)
     
     def receive_packet(self, device_id: str, manufacturer_data, timestamp=None) -> Optional[Dict]:
         """
         Process an incoming BLE advertisement packet.
         
         Automatically deduplicates and reassembles data across multiple packets.
         
         Args:
             device_id: Device MAC address
             manufacturer_data: Raw BLE manufacturer data (bytes or hex string)
             timestamp: Optional packet timestamp
         
         Returns:
             dict with complete measurement if stream is complete, None otherwise
         """
         result = self.receiver.process_packet(device_id, manufacturer_data, timestamp)
         
         if result:
             # Stream is complete, invoke callbacks
             for callback in self.stream_callbacks:
                 try:
                     callback(device_id, result)
                 except Exception as e:
                     logger.error(f"Callback error: {e}", exc_info=True)
         
         return result
     
     def get_stats(self) -> Dict:
         """Get statistics on packet processing and deduplication"""
         stats = self.receiver.get_stats()
         stats['tracked_devices'] = len(self.device_stream_history)
         return stats


# ============================================================================
# BLE Data Fetching Helpers
# ============================================================================

def create_ble_fetcher() -> BLEDataFetcher:
     """Factory function to create a preconfigured BLE data fetcher"""
     return BLEDataFetcher()


def extract_samples_from_stream(stream_data: Dict) -> Optional[List[int]]:
     """
     Extract 84 ADC samples from a complete captouch stream.
     
     Args:
         stream_data: Complete stream dict from BLEDataFetcher
     
     Returns:
         List of 84 samples, or None if parsing failed
     """
     try:
         if 'parsed' in stream_data and 'self_cap_raw' in stream_data['parsed']:
             parsed = stream_data['parsed']
             # Combine all samples in order: VDD, GND, self-cap, mutual-cap
             all_samples = (
                 parsed.get('vdd_ref', []) +
                 parsed.get('gnd_ref', []) +
                 parsed.get('self_cap_raw', []) +
                 parsed.get('mutual_cap_raw', [])
             )
             return all_samples
     except Exception as e:
         logger.error(f"Error extracting samples: {e}")
     return None


if __name__ == '__main__':
    # Test example
    logging.basicConfig(level=logging.DEBUG)

    receiver = MultiPacketBLEReceiver()
    receiver.register_parser(0xDD, parse_captouch_data)

    # Simulate receiving the same packet multiple times
    test_packet = bytes([
        0xE5, 0xFF,  # Company ID
        0xAA,        # Protocol ID
        0xDD,        # Data type (captouch)
        0x01, 0x00,  # Stream ID = 1
        0x0E,        # Total packets = 14
        0x00,        # Sequence = 0
        0xA8, 0x00,  # Payload length = 168 bytes
        # Payload (6 samples, 12 bytes)
        0x05, 0x91, 0x05, 0x90, 0x05, 0x93,
        0x05, 0x91, 0x05, 0x94, 0x05, 0x90,
    ])

    device_id = 'AA:BB:CC:DD:EE:FF'

    # First reception
    result1 = receiver.process_packet(device_id, test_packet)
    print(f"First: {result1}")

    # Duplicate (should be ignored)
    result2 = receiver.process_packet(device_id, test_packet)
    print(f"Duplicate: {result2}")

    # Another duplicate
    result3 = receiver.process_packet(device_id, test_packet)
    print(f"Another duplicate: {result3}")

    print(f"\nStats: {receiver.get_stats()}")
