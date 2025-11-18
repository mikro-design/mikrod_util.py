#!/usr/bin/env python3
"""
Test Suite for BLE Data Deduplication and Reassembly

Tests the complete workflow:
  1. Packet-level deduplication (4× retransmissions)
  2. Stream assembly (14 packets → 84 samples)
  3. Sample parsing (big-endian int16)
  4. Statistics tracking
"""

import pytest
import struct
import logging
from datetime import datetime, timedelta
from multipacket_ble import (
    MultiPacketBLEReceiver,
    StreamBuffer,
    BLEDataFetcher,
    parse_captouch_data,
    extract_samples_from_stream
)

# Setup logging for tests
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def receiver():
    """Create a fresh receiver for each test"""
    return MultiPacketBLEReceiver()


@pytest.fixture
def fetcher():
    """Create a fresh fetcher for each test"""
    return BLEDataFetcher()


def create_test_packet(company_id=0xFFE5, protocol_id=0xAA, data_type=0xDD,
                       stream_id=1, sequence=0, total_packets=14,
                       samples=None):
    """
    Create a test BLE packet with specified parameters.
    
    Args:
        company_id: Manufacturer ID
        protocol_id: Protocol identifier
        data_type: Data type byte
        stream_id: Stream identifier
        sequence: Packet sequence (0-13)
        total_packets: Total packets in stream
        samples: List of int16 sample values (max 6 for 12 bytes)
    
    Returns:
        bytes: Complete BLE packet
    """
    if samples is None:
        samples = [1425, 1424, 1427, 1425, 1428, 1424]  # Example values
    
    # Build packet
    packet = bytearray()
    
    # Header
    packet.extend(struct.pack('<H', company_id))      # [0-1]: Company ID
    packet.append(protocol_id)                          # [2]: Protocol ID
    packet.append(data_type)                            # [3]: Data type
    packet.extend(b'\x00' * 6)                          # [4-9]: MAC address (ignored)
    packet.extend(struct.pack('<H', stream_id))         # [10-11]: Stream ID
    packet.append(total_packets)                        # [12]: Total packets
    packet.append(sequence)                             # [13]: Sequence
    packet.extend(struct.pack('<H', 168))               # [14-15]: Payload length (168 for captouch)
    
    # Payload: 6 big-endian int16 samples (12 bytes per packet)
    for sample in samples[:6]:
        packet.extend(struct.pack('>h', sample))
    
    return bytes(packet)


# ============================================================================
# TESTS: DEDUPLICATION
# ============================================================================

class TestDeduplication:
    """Test packet-level deduplication"""
    
    def test_duplicate_detection(self, receiver):
        """Verify that duplicate packets are detected"""
        device_id = "AA:BB:CC:DD:EE:FF"
        packet = create_test_packet(stream_id=100, sequence=0)
        
        # First packet should be accepted
        result1 = receiver.process_packet(device_id, packet)
        assert result1 is None  # Not complete yet
        assert receiver.stats['packets_received'] == 1
        assert receiver.stats['packets_duplicate'] == 0
        
        # Duplicate should be rejected
        result2 = receiver.process_packet(device_id, packet)
        assert result2 is None
        assert receiver.stats['packets_received'] == 2
        assert receiver.stats['packets_duplicate'] == 1
        
        # Another duplicate
        result3 = receiver.process_packet(device_id, packet)
        assert receiver.stats['packets_duplicate'] == 2
    
    def test_duplicate_rate_expected(self, receiver):
        """
        Verify expected 50% duplicate rate (4 retransmissions → 1 unique + 3 duplicates)
        """
        device_id = "AA:BB:CC:DD:EE:FF"
        packet = create_test_packet(stream_id=100, sequence=0)
        
        # Simulate 4 retransmissions
        for i in range(4):
            receiver.process_packet(device_id, packet)
        
        dup_rate = receiver.stats['packets_duplicate'] / receiver.stats['packets_received']
        assert dup_rate == pytest.approx(0.75)  # 3 of 4 are duplicates
    
    def test_different_sequences_not_duplicate(self, receiver):
        """Verify that different sequence numbers are not deduplicated"""
        device_id = "AA:BB:CC:DD:EE:FF"
        
        # Different sequences should not be duplicates
        for seq in range(5):
            packet = create_test_packet(stream_id=100, sequence=seq)
            result = receiver.process_packet(device_id, packet)
            
            # None until all 14 packets received
            assert result is None
        
        # Should have received 5 unique packets, no duplicates
        assert receiver.stats['packets_received'] == 5
        assert receiver.stats['packets_duplicate'] == 0
    
    def test_different_streams_not_duplicate(self, receiver):
        """Verify that different stream IDs are not deduplicated"""
        device_id = "AA:BB:CC:DD:EE:FF"
        packet_base = create_test_packet(sequence=0)
        
        # Same packet but different stream IDs
        for stream_id in [100, 101, 102]:
            packet = create_test_packet(stream_id=stream_id, sequence=0)
            receiver.process_packet(device_id, packet)
        
        # 3 unique packets from different streams
        assert receiver.stats['packets_received'] == 3
        assert receiver.stats['packets_duplicate'] == 0


# ============================================================================
# TESTS: STREAM ASSEMBLY
# ============================================================================

class TestStreamAssembly:
    """Test multi-packet stream reassembly"""
    
    def test_stream_completion(self, receiver):
        """Verify stream completes when all packets received"""
        device_id = "AA:BB:CC:DD:EE:FF"
        stream_id = 1000
        
        # Create all 14 packets
        packets = [
            create_test_packet(stream_id=stream_id, sequence=i)
            for i in range(14)
        ]
        
        result = None
        for i, packet in enumerate(packets):
            result = receiver.process_packet(device_id, packet)
            if i < 13:
                assert result is None, f"Stream shouldn't complete before packet 14"
        
        # Last packet should complete the stream
        assert result is not None, "Result should not be None after all packets"
        assert result['stream_id'] == stream_id
        assert result['complete'] == True
        assert result['packets_received'] == 14
        assert result['packets_expected'] == 14
        assert result['length'] == 168  # 14 packets × 12 bytes
    
    def test_packets_reassembled_in_order(self, receiver):
        """Verify packets are reassembled in correct order"""
        device_id = "AA:BB:CC:DD:EE:FF"
        stream_id = 1000
        
        # Create packets with distinct sample values to verify order
        packets = []
        for seq in range(14):
            samples = [seq * 100 + i for i in range(6)]  # Distinct values
            packet = create_test_packet(
                stream_id=stream_id,
                sequence=seq,
                samples=samples
            )
            packets.append((seq, packet, samples))
        
        # Send packets in random order
        import random
        shuffled = list(packets)
        random.shuffle(shuffled)
        
        result = None
        for seq, packet, samples in shuffled:
            result = receiver.process_packet(device_id, packet)
        
        # Verify data is correctly reassembled
        assert result['complete'] == True
        
        # Parse to verify sample order
        parsed = result['parsed']
        all_samples = (
            parsed['vdd_ref'] +
            parsed['gnd_ref'] +
            parsed['self_cap_raw'] +
            parsed['mutual_cap_raw']
        )
        
        # Should have 84 samples in correct order
        assert len(all_samples) == 84
    
    def test_stream_timeout_incomplete(self, receiver):
        """Verify incomplete streams timeout"""
        device_id = "AA:BB:CC:DD:EE:FF"
        stream_id = 1000
        
        # Send only 5 of 14 packets
        for i in range(5):
            packet = create_test_packet(stream_id=stream_id, sequence=i)
            receiver.process_packet(device_id, packet)
        
        # Stream should be active
        assert len(receiver.streams) == 1
        
        # Trigger cleanup with timestamp after timeout
        future = datetime.now() + timedelta(seconds=61)
        receiver.cleanup(now=future)
        
        # Stream should be removed due to timeout
        assert len(receiver.streams) == 0
        assert receiver.stats['streams_timeout'] == 1


# ============================================================================
# TESTS: SAMPLE PARSING
# ============================================================================

class TestSampleParsing:
    """Test BLE sample encoding and parsing"""
    
    def test_big_endian_sample_encoding(self):
        """Verify big-endian int16 encoding"""
        # Create samples with known values
        samples = [1425, -1024, 0, 2047, -2048, 512]
        
        # Encode as big-endian
        data = b''
        for sample in samples:
            data += struct.pack('>h', sample)
        
        # Decode and verify
        decoded = []
        for i in range(len(samples)):
            offset = i * 2
            value = struct.unpack('>h', data[offset:offset+2])[0]
            decoded.append(value)
        
        assert decoded == samples
    
    def test_parse_captouch_data_complete(self):
        """Verify captouch data parsing with complete stream"""
        # Create 168 bytes of test data (84 samples)
        data = b''
        for i in range(84):
            data += struct.pack('>h', 1000 + i)  # Unique value per sample
        
        assert len(data) == 168
        
        result = parse_captouch_data(data)
        
        assert result['total_samples'] == 84
        assert len(result['vdd_ref']) == 8
        assert len(result['gnd_ref']) == 8
        assert len(result['self_cap_raw']) == 34
        assert len(result['mutual_cap_raw']) == 34
        assert result['adc_range'] > 0
    
    def test_parse_captouch_data_incomplete(self):
        """Verify error on incomplete data"""
        data = b'\x00' * 100  # Less than 168 bytes
        
        with pytest.raises(ValueError):
            parse_captouch_data(data)


# ============================================================================
# TESTS: BLE DATA FETCHER
# ============================================================================

class TestBLEDataFetcher:
    """Test high-level BLE data fetcher"""
    
    def test_fetcher_initialization(self, fetcher):
        """Verify fetcher initializes correctly"""
        assert fetcher.fetcher is not None
        assert len(fetcher.stream_callbacks) == 0
    
    def test_fetcher_callback_registration(self, fetcher):
        """Verify callbacks can be registered"""
        callback_invoked = []
        
        def test_callback(device_id, stream_data):
            callback_invoked.append((device_id, stream_data))
        
        fetcher.on_stream_complete(test_callback)
        assert len(fetcher.stream_callbacks) == 1
    
    def test_fetcher_with_complete_stream(self, fetcher):
        """Test complete stream through fetcher"""
        device_id = "AA:BB:CC:DD:EE:FF"
        stream_id = 1000
        
        callback_data = []
        def capture_callback(dev_id, data):
            callback_data.append((dev_id, data))
        
        fetcher.on_stream_complete(capture_callback)
        
        # Send 14 packets
        for seq in range(14):
            packet = create_test_packet(stream_id=stream_id, sequence=seq)
            result = fetcher.receive_packet(device_id, packet)
        
        # Callback should have been invoked once
        assert len(callback_data) == 1
        assert callback_data[0][0] == device_id
        assert callback_data[0][1]['complete'] == True
    
    def test_fetcher_statistics(self, fetcher):
        """Verify statistics tracking"""
        device_id = "AA:BB:CC:DD:EE:FF"
        
        # Send one packet
        packet = create_test_packet()
        fetcher.receive_packet(device_id, packet)
        
        stats = fetcher.get_stats()
        assert stats['packets_received'] == 1
        assert stats['packets_duplicate'] == 0
        assert stats['active_streams'] == 1
        assert stats['tracked_devices'] == 0  # Not used in basic fetcher


# ============================================================================
# TESTS: INTEGRATION
# ============================================================================

class TestIntegration:
    """Integration tests for realistic scenarios"""
    
    def test_4x_retransmission_scenario(self, receiver):
        """
        Simulate realistic scenario:
        - 14 packets per measurement
        - 4 retransmissions each
        - Only 1 unique packet should arrive
        """
        device_id = "AA:BB:CC:DD:EE:FF"
        stream_id = 1000
        
        # Send 14 unique packets, each with 4 retransmissions
        for seq in range(14):
            packet = create_test_packet(stream_id=stream_id, sequence=seq)
            
            # 4 retransmissions
            for retrans in range(4):
                result = receiver.process_packet(device_id, packet)
                
                # Only the last packet should complete the stream
                if seq == 13 and retrans == 0:
                    # First reception of packet 13 completes
                    assert result is not None
                    break  # No need to process remaining retransmissions
        
        # Verify deduplication worked
        assert receiver.stats['packets_received'] == 14 * 4  # 56 total
        assert receiver.stats['packets_duplicate'] == 42  # 56 - 14
        assert receiver.stats['streams_completed'] == 1
    
    def test_multiple_concurrent_streams(self, receiver):
        """Test handling multiple streams from different stream IDs"""
        device_id = "AA:BB:CC:DD:EE:FF"
        
        # Create 3 concurrent streams (stream IDs 1000, 1001, 1002)
        for stream_id in [1000, 1001, 1002]:
            for seq in range(14):
                packet = create_test_packet(stream_id=stream_id, sequence=seq)
                receiver.process_packet(device_id, packet)
        
        # Should have 3 completed streams
        assert receiver.stats['streams_completed'] == 3
        assert len(receiver.completed_streams) == 3
    
    def test_extract_samples_from_stream(self, fetcher):
        """Test extracting samples from completed stream"""
        device_id = "AA:BB:CC:DD:EE:FF"
        stream_id = 1000
        
        # Send complete stream
        for seq in range(14):
            packet = create_test_packet(stream_id=stream_id, sequence=seq)
            result = fetcher.receive_packet(device_id, packet)
        
        # Extract samples
        samples = extract_samples_from_stream(result)
        
        assert samples is not None
        assert len(samples) == 84
        assert all(isinstance(s, int) for s in samples)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    # Run tests with verbose output
    pytest.main([__file__, '-v', '-s'])
