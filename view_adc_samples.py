#!/usr/bin/env python3
"""
ADC Sample Viewer - Display BLE ADC samples from database

Shows captured measurements with statistics and visualization.

Usage:
  python3 view_adc_samples.py list              # List all devices
  python3 view_adc_samples.py latest            # Show latest measurement
  python3 view_adc_samples.py show DEVICE_ID    # Show device measurements
  python3 view_adc_samples.py stats DEVICE_ID   # Show statistics
"""

import sqlite3
import json
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional


class ADCViewer:
    """View ADC samples from database"""
    
    def __init__(self, db_file='ble_gateway.db'):
        self.db_file = db_file
    
    def connect(self):
        """Connect to database"""
        try:
            self.conn = sqlite3.connect(self.db_file)
            self.cursor = self.conn.cursor()
            return True
        except Exception as e:
            print(f"Error: Cannot connect to {self.db_file}: {e}")
            return False
    
    def close(self):
        """Close database"""
        if hasattr(self, 'conn'):
            self.conn.close()
    
    def get_devices(self) -> List[str]:
        """Get all devices"""
        try:
            self.cursor.execute('SELECT DISTINCT device_id FROM device_readings ORDER BY device_id')
            return [row[0] for row in self.cursor.fetchall()]
        except:
            return []
    
    def get_latest(self, device_id=None):
        """Get latest measurement"""
        try:
            if device_id:
                self.cursor.execute('''
                    SELECT id, device_id, device_name, timestamp, rssi, raw_data
                    FROM device_readings
                    WHERE device_id = ?
                    ORDER BY timestamp DESC LIMIT 1
                ''', (device_id,))
            else:
                self.cursor.execute('''
                    SELECT id, device_id, device_name, timestamp, rssi, raw_data
                    FROM device_readings
                    ORDER BY timestamp DESC LIMIT 1
                ''')
            return self.cursor.fetchone()
        except:
            return None
    
    def get_device_readings(self, device_id, hours=1, limit=None):
        """Get readings for device"""
        try:
            query = '''
                SELECT id, device_id, device_name, timestamp, rssi, raw_data
                FROM device_readings
                WHERE device_id = ?
                AND timestamp > datetime('now', '-' || ? || ' hours')
                ORDER BY timestamp DESC
            '''
            params = [device_id, hours]
            
            if limit:
                query += f' LIMIT {limit}'
            
            self.cursor.execute(query, params)
            return self.cursor.fetchall()
        except:
            return []
    
    def format_row(self, row):
        """Format a database row for display"""
        reading_id, device_id, device_name, timestamp, rssi, raw_data = row
        
        # Parse raw_data
        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        except:
            data = {}
        
        return {
            'id': reading_id,
            'device_id': device_id,
            'device_name': device_name,
            'timestamp': timestamp,
            'rssi': rssi,
            'data': data
        }


def format_samples(samples: List[int], samples_per_line: int = 12) -> str:
    """Format samples for display"""
    if not samples:
        return "  (no samples)"
    
    lines = []
    for i in range(0, len(samples), samples_per_line):
        chunk = samples[i:i+samples_per_line]
        formatted = ' '.join(f'{s:6d}' for s in chunk)
        lines.append(f"    [{i:2d}]: {formatted}")
    return '\n'.join(lines)


def compute_stats(values: List) -> Dict:
    """Compute basic statistics"""
    if not values:
        return {}
    
    values = [v for v in values if isinstance(v, (int, float))]
    if not values:
        return {}
    
    return {
        'min': min(values),
        'max': max(values),
        'avg': sum(values) / len(values),
        'count': len(values)
    }


def plot_samples(samples: List[int], width: int = 70, height: int = 15) -> str:
    """Create ASCII plot of samples"""
    if not samples or len(samples) == 0:
        return "  (no data to plot)"
    
    # Normalize
    min_val = min(samples)
    max_val = max(samples)
    range_val = max_val - min_val if max_val != min_val else 1
    
    # Create grid
    grid = [[' ' for _ in range(width)] for _ in range(height)]
    
    # Plot points
    step = max(1, len(samples) // width)
    for x in range(width):
        idx = min(x * step, len(samples) - 1)
        val = samples[idx]
        y = int((val - min_val) / range_val * (height - 1))
        y = max(0, min(y, height - 1))
        grid[height - 1 - y][x] = '█'
    
    # Format output
    lines = ['  ' + ''.join(row) for row in grid]
    lines.append(f"  {min_val:6d}" + ' ' * (width - 12) + f"{max_val:6d}")
    
    return '\n'.join(lines)


def cmd_list(viewer):
    """List all devices"""
    devices = viewer.get_devices()
    
    if not devices:
        print("No devices in database")
        return
    
    print("\n" + "=" * 70)
    print("DEVICES IN DATABASE")
    print("=" * 70)
    for i, dev in enumerate(devices, 1):
        print(f"  {i}. {dev}")
    print("=" * 70)


def cmd_latest(viewer, device_id=None):
    """Show latest measurement"""
    row = viewer.get_latest(device_id)
    
    if not row:
        print("No measurements found")
        return
    
    fmt = viewer.format_row(row)
    
    print("\n" + "=" * 70)
    print("LATEST MEASUREMENT")
    print("=" * 70)
    print(f"Device:    {fmt['device_id']}")
    print(f"Name:      {fmt['device_name'] or '(unnamed)'}")
    print(f"Time:      {fmt['timestamp']}")
    print(f"RSSI:      {fmt['rssi']} dBm")
    print(f"\nData fields:")
    
    for key, value in fmt['data'].items():
        if isinstance(value, list):
            print(f"  {key}: {len(value)} values")
        else:
            print(f"  {key}: {value}")
    
    print("=" * 70)


def cmd_show(viewer, device_id, hours=1, count=10):
    """Show device measurements"""
    rows = viewer.get_device_readings(device_id, hours=hours, limit=count)
    
    if not rows:
        print(f"No measurements for {device_id}")
        return
    
    print("\n" + "=" * 70)
    print(f"MEASUREMENTS FOR {device_id} (Last {hours} hours)")
    print("=" * 70)
    
    for i, row in enumerate(rows, 1):
        fmt = viewer.format_row(row)
        print(f"\n{i}. {fmt['timestamp']} | RSSI: {fmt['rssi']} dBm")
        
        # Show data fields
        for key, value in fmt['data'].items():
            if isinstance(value, list):
                print(f"   {key}: {len(value)} values")
            elif isinstance(value, (int, float)):
                print(f"   {key}: {value}")
    
    print("\n" + "=" * 70)


def cmd_stats(viewer, device_id):
    """Show detailed statistics"""
    row = viewer.get_latest(device_id)
    
    if not row:
        print(f"No measurements for {device_id}")
        return
    
    fmt = viewer.format_row(row)
    
    print("\n" + "=" * 70)
    print(f"STATISTICS - {fmt['device_id']}")
    print("=" * 70)
    print(f"Time:    {fmt['timestamp']}")
    print(f"RSSI:    {fmt['rssi']} dBm")
    
    # Analyze each field
    for key, value in fmt['data'].items():
        if isinstance(value, list):
            stats = compute_stats(value)
            print(f"\n{key} ({len(value)} samples):")
            print(f"  Min:    {stats.get('min', 'N/A')}")
            print(f"  Max:    {stats.get('max', 'N/A')}")
            print(f"  Avg:    {stats.get('avg', 'N/A'):.2f}" if 'avg' in stats else "")
            print(f"\nWaveform:")
            print(plot_samples(value))
            print(f"\nSample values:")
            print(format_samples(value))


def print_help():
    """Print help"""
    print("""
ADC Sample Viewer - View BLE measurements from database

Usage:
  python3 view_adc_samples.py <command> [args]

Commands:
  list              List all devices
  latest [DEV]      Show latest measurement
  show DEV          Show recent measurements
  stats DEV         Show detailed statistics and plot
  help              Show this help

Examples:
  python3 view_adc_samples.py list
  python3 view_adc_samples.py latest
  python3 view_adc_samples.py latest AA:BB:CC:DD:EE:FF
  python3 view_adc_samples.py show AA:BB:CC:DD:EE:FF
  python3 view_adc_samples.py stats AA:BB:CC:DD:EE:FF

Database: ble_gateway.db
    """)


if __name__ == '__main__':
    viewer = ADCViewer()
    
    if not viewer.connect():
        sys.exit(1)
    
    try:
        if len(sys.argv) < 2:
            print_help()
        else:
            cmd = sys.argv[1].lower()
            
            if cmd == 'help' or cmd == '-h':
                print_help()
            elif cmd == 'list':
                cmd_list(viewer)
            elif cmd == 'latest':
                dev = sys.argv[2] if len(sys.argv) > 2 else None
                cmd_latest(viewer, dev)
            elif cmd == 'show':
                if len(sys.argv) < 3:
                    print("Usage: show <device_id>")
                else:
                    cmd_show(viewer, sys.argv[2])
            elif cmd == 'stats':
                if len(sys.argv) < 3:
                    print("Usage: stats <device_id>")
                else:
                    cmd_stats(viewer, sys.argv[2])
            else:
                print(f"Unknown command: {cmd}")
                print_help()
    finally:
        viewer.close()
