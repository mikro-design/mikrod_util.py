#!/usr/bin/env python3
"""
BLE Sensor Data Plotter - Visualize sensor data from the gateway database
"""
import sqlite3
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import argparse
import sys
from pathlib import Path

DB_FILE = 'ble_gateway.db'


def get_available_devices(conn):
    """Get list of devices that have sensor data"""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT dr.device_id, dr.device_name, COUNT(sd.id) as sensor_count
        FROM device_readings dr
        JOIN sensor_data sd ON dr.id = sd.reading_id
        GROUP BY dr.device_id
        ORDER BY sensor_count DESC
    ''')
    return cursor.fetchall()


def get_sensor_types(conn, device_id=None):
    """Get available sensor types, optionally filtered by device"""
    cursor = conn.cursor()
    if device_id:
        cursor.execute('''
            SELECT DISTINCT sd.sensor_type, sd.unit, COUNT(sd.id) as reading_count
            FROM sensor_data sd
            JOIN device_readings dr ON sd.reading_id = dr.id
            WHERE dr.device_id = ?
            GROUP BY sd.sensor_type
            ORDER BY reading_count DESC
        ''', (device_id,))
    else:
        cursor.execute('''
            SELECT DISTINCT sensor_type, unit, COUNT(id) as reading_count
            FROM sensor_data
            GROUP BY sensor_type
            ORDER BY reading_count DESC
        ''')
    return cursor.fetchall()


def get_sensor_data(conn, sensor_type, device_id=None, hours=24):
    """Retrieve sensor data for plotting"""
    cursor = conn.cursor()
    time_limit = datetime.now() - timedelta(hours=hours)

    if device_id:
        cursor.execute('''
            SELECT dr.timestamp, sd.sensor_value, sd.unit, dr.device_name
            FROM sensor_data sd
            JOIN device_readings dr ON sd.reading_id = dr.id
            WHERE sd.sensor_type = ?
              AND dr.device_id = ?
              AND dr.timestamp >= ?
            ORDER BY dr.timestamp
        ''', (sensor_type, device_id, time_limit))
    else:
        cursor.execute('''
            SELECT dr.timestamp, sd.sensor_value, sd.unit, dr.device_name, dr.device_id
            FROM sensor_data sd
            JOIN device_readings dr ON sd.reading_id = dr.id
            WHERE sd.sensor_type = ?
              AND dr.timestamp >= ?
            ORDER BY dr.timestamp
        ''', (sensor_type, time_limit))

    return cursor.fetchall()


def extract_field_value(data, field_path):
    """Extract a field value from JSON data using dot notation (e.g., 'txPowerLevel' or 'manufacturerData.004c.bytes.0')"""
    import json

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except:
            return None

    parts = field_path.split('.')
    current = data

    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                index = int(part)
                current = current[index] if index < len(current) else None
            except ValueError:
                return None
        else:
            return None

        if current is None:
            return None

    return current if isinstance(current, (int, float)) else None


def get_raw_field_data(conn, field_path, device_id=None, hours=24):
    """Extract field data from raw advertising JSON"""
    import json

    cursor = conn.cursor()
    time_limit = datetime.now() - timedelta(hours=hours)

    if device_id:
        cursor.execute('''
            SELECT timestamp, raw_data, device_name, device_id
            FROM device_readings
            WHERE device_id = ? AND timestamp >= ?
            ORDER BY timestamp
        ''', (device_id, time_limit))
    else:
        cursor.execute('''
            SELECT timestamp, raw_data, device_name, device_id
            FROM device_readings
            WHERE timestamp >= ?
            ORDER BY timestamp
        ''', (time_limit,))

    rows = cursor.fetchall()
    result = []

    for row in rows:
        timestamp, raw_data, device_name, dev_id = row
        value = extract_field_value(raw_data, field_path)
        if value is not None:
            result.append((timestamp, value, field_path, device_name, dev_id))

    return result


def plot_multiple_fields(conn, field_paths, device_id=None, hours=24, save_path=None):
    """Plot multiple advertising data fields on the same graph"""

    fig, ax = plt.subplots(figsize=(12, 6))

    colors = ['#007AFF', '#34C759', '#FF9500', '#FF3B30', '#5856D6', '#AF52DE', '#FF2D55', '#64D2FF']

    for idx, field_path in enumerate(field_paths):
        data = get_raw_field_data(conn, field_path, device_id, hours)

        if not data:
            print(f"No data for field: {field_path}")
            continue

        # Extract timestamps and values
        timestamps = [datetime.fromisoformat(row[0]) for row in data]
        values = [row[1] for row in data]

        color = colors[idx % len(colors)]
        ax.plot(timestamps, values, marker='o', linestyle='-',
               linewidth=1.5, markersize=4, color=color, alpha=0.7,
               label=field_path)

    # Format plot
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Value', fontsize=12)

    title = 'Multiple Advertising Data Fields over Time'
    if device_id:
        title += f' - {device_id}'
    ax.set_title(title, fontsize=14, fontweight='bold')

    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.xticks(rotation=45)

    # Legend
    ax.legend(loc='best')

    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')

    # Tight layout
    plt.tight_layout()

    # Save or show
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {save_path}")
    else:
        plt.show()

    plt.close()


def plot_sensor_data(sensor_type, data, device_name=None, save_path=None):
    """Create a plot for sensor data"""
    if not data:
        print(f"No data available for {sensor_type}")
        return

    # Parse timestamps and values
    timestamps = [datetime.fromisoformat(row[0]) for row in data]
    values = [row[1] for row in data]
    unit = data[0][2] if len(data[0]) > 2 else ''

    # Group by device if multiple devices
    if len(data[0]) > 3:
        devices = {}
        for row in data:
            dev_id = row[4] if len(row) > 4 else row[3]
            if dev_id not in devices:
                devices[dev_id] = {'timestamps': [], 'values': [], 'name': row[3]}
            devices[dev_id]['timestamps'].append(datetime.fromisoformat(row[0]))
            devices[dev_id]['values'].append(row[1])

        # Create plot
        fig, ax = plt.subplots(figsize=(12, 6))

        for dev_id, dev_data in devices.items():
            ax.plot(dev_data['timestamps'], dev_data['values'],
                   marker='o', linestyle='-', linewidth=1.5, markersize=4,
                   label=dev_data['name'], alpha=0.7)

        ax.legend()
    else:
        # Single device plot
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(timestamps, values, marker='o', linestyle='-',
               linewidth=2, markersize=4, color='#007AFF', alpha=0.7)

    # Format plot
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel(f'{sensor_type.capitalize()} ({unit})', fontsize=12)

    title = f'{sensor_type.capitalize()} over Time'
    if device_name:
        title += f' - {device_name}'
    ax.set_title(title, fontsize=14, fontweight='bold')

    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.xticks(rotation=45)

    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')

    # Tight layout
    plt.tight_layout()

    # Save or show
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {save_path}")
    else:
        plt.show()

    plt.close()


def plot_rssi(conn, device_id=None, hours=24, save_path=None):
    """Plot RSSI (signal strength) over time"""
    cursor = conn.cursor()
    time_limit = datetime.now() - timedelta(hours=hours)

    if device_id:
        cursor.execute('''
            SELECT timestamp, rssi, device_name
            FROM device_readings
            WHERE device_id = ? AND timestamp >= ?
            ORDER BY timestamp
        ''', (device_id, time_limit))
        title_suffix = f" - {cursor.fetchone()[2] if cursor.rowcount > 0 else device_id}"
        cursor.execute('''
            SELECT timestamp, rssi, device_name
            FROM device_readings
            WHERE device_id = ? AND timestamp >= ?
            ORDER BY timestamp
        ''', (device_id, time_limit))
    else:
        cursor.execute('''
            SELECT timestamp, rssi, device_name, device_id
            FROM device_readings
            WHERE timestamp >= ?
            ORDER BY timestamp
        ''', (time_limit,))
        title_suffix = ""

    data = cursor.fetchall()

    if not data:
        print("No RSSI data available")
        return

    # Group by device
    devices = {}
    for row in data:
        dev_id = row[3] if len(row) > 3 else device_id
        if dev_id not in devices:
            devices[dev_id] = {'timestamps': [], 'values': [], 'name': row[2]}
        devices[dev_id]['timestamps'].append(datetime.fromisoformat(row[0]))
        devices[dev_id]['values'].append(row[1])

    # Create plot
    fig, ax = plt.subplots(figsize=(12, 6))

    for dev_id, dev_data in devices.items():
        ax.plot(dev_data['timestamps'], dev_data['values'],
               marker='o', linestyle='-', linewidth=1.5, markersize=4,
               label=dev_data['name'], alpha=0.7)

    if len(devices) > 1:
        ax.legend()

    # Format plot
    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('RSSI (dBm)', fontsize=12)
    ax.set_title(f'Signal Strength over Time{title_suffix}', fontsize=14, fontweight='bold')

    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    plt.xticks(rotation=45)

    # Grid and reference lines
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.axhline(y=-70, color='green', linestyle='--', alpha=0.5, label='Good')
    ax.axhline(y=-85, color='orange', linestyle='--', alpha=0.5, label='Medium')

    # Tight layout
    plt.tight_layout()

    # Save or show
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Plot saved to: {save_path}")
    else:
        plt.show()

    plt.close()


def clear_database(conn):
    """Clear all data from the database tables"""
    cursor = conn.cursor()

    try:
        # Get row counts before clearing
        cursor.execute('SELECT COUNT(*) FROM device_readings')
        device_count = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM sensor_data')
        sensor_count = cursor.fetchone()[0]

        print(f"\n⚠️  About to delete:")
        print(f"   - {device_count} device readings")
        print(f"   - {sensor_count} sensor data entries")

        response = input("\nAre you sure you want to clear all data? (yes/no): ")

        if response.lower() not in ['yes', 'y']:
            print("❌ Cancelled - no data was deleted")
            return

        # Clear tables
        cursor.execute('DELETE FROM sensor_data')
        cursor.execute('DELETE FROM device_readings')
        conn.commit()

        print(f"\n✓ Database cleared successfully!")
        print(f"   - Deleted {device_count} device readings")
        print(f"   - Deleted {sensor_count} sensor data entries")

    except Exception as e:
        print(f"❌ Error clearing database: {e}")
        conn.rollback()


def list_available_data(conn):
    """List all available devices and sensors"""
    import json

    print("\n" + "=" * 60)
    print("Available Data in Database")
    print("=" * 60)

    # Get all devices from device_readings
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT device_id, device_name, COUNT(*) as reading_count
        FROM device_readings
        GROUP BY device_id
        ORDER BY reading_count DESC
    ''')
    devices = cursor.fetchall()

    if devices:
        print("\nDevices in database:")
        for dev_id, dev_name, count in devices:
            print(f"  - {dev_name or 'Unknown'} ({dev_id}): {count} readings")
    else:
        print("\nNo devices found in database")
        print("=" * 60 + "\n")
        return

    # Get a sample raw data frame from the most recent reading
    cursor.execute('''
        SELECT device_id, device_name, rssi, raw_data, timestamp
        FROM device_readings
        ORDER BY timestamp DESC
        LIMIT 1
    ''')
    sample = cursor.fetchone()

    if sample:
        dev_id, dev_name, rssi, raw_data, timestamp = sample
        print(f"\n📋 Sample data frame (most recent):")
        print(f"   Device: {dev_name or 'Unknown'} ({dev_id})")
        print(f"   Time: {timestamp}")
        print(f"   RSSI: {rssi} dBm")
        print(f"   Raw advertising data:")

        try:
            data = json.loads(raw_data)
            print(json.dumps(data, indent=6))

            # Try to recognize fields
            print(f"\n🔍 Recognizable numeric fields (can be plotted):")
            recognized = []

            def scan_fields(obj, prefix=''):
                """Recursively scan for all numeric fields including arrays"""
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        full_key = f"{prefix}.{key}" if prefix else key
                        if isinstance(value, (int, float)):
                            recognized.append(f"      {full_key}: {value}")
                        elif isinstance(value, list):
                            # Handle arrays - show first few elements
                            numeric_items = [v for v in value if isinstance(v, (int, float))]
                            if numeric_items:
                                preview = numeric_items[:3]
                                more = f" ... +{len(numeric_items)-3}" if len(numeric_items) > 3 else ""
                                recognized.append(f"      {full_key}: [{', '.join(map(str, preview))}{more}] ({len(numeric_items)} values)")
                        elif isinstance(value, dict):
                            scan_fields(value, full_key)
                elif isinstance(obj, list):
                    for i, value in enumerate(obj):
                        full_key = f"{prefix}[{i}]"
                        if isinstance(value, (int, float)):
                            recognized.append(f"      {full_key}: {value}")
                        elif isinstance(value, dict):
                            scan_fields(value, full_key)

            scan_fields(data)

            if recognized:
                for field in recognized:
                    print(field)
            else:
                print("      (No numeric fields found)")

            # Decode manufacturer data if present
            if "manufacturerData" in data:
                print(f"\n📱 Manufacturer Data:")
                for company_id, mfg_data in data["manufacturerData"].items():
                    # Known company IDs
                    companies = {
                        "004c": "Apple Inc.",
                        "0059": "Nordic Semiconductor",
                        "0075": "Samsung Electronics",
                        "00e0": "Google",
                        "0157": "Xiaomi",
                    }
                    company_name = companies.get(company_id, f"Unknown (0x{company_id})")
                    print(f"      Company: {company_name}")
                    if isinstance(mfg_data, dict) and "bytes" in mfg_data:
                        bytes_data = mfg_data["bytes"]
                        print(f"      Bytes: {bytes_data[:10]}{'...' if len(bytes_data) > 10 else ''}")
                        print(f"      Length: {len(bytes_data)} bytes")

        except json.JSONDecodeError:
            print(f"      {raw_data}")

    # Sensor types from sensor_data table (if any)
    sensor_types = get_sensor_types(conn)
    if sensor_types:
        print("\n📊 Sensor data table (legacy):")
        for sensor_type, unit, count in sensor_types:
            print(f"  - {sensor_type}: {count} readings ({unit})")

    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Plot BLE sensor data from gateway database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s --list                                 List devices and show sample data
  %(prog)s --clear                                Clear all data from database

  Single field plots:
  %(prog)s --field txPowerLevel                   Plot txPowerLevel from advertising data
  %(prog)s --field rawData.5                      Plot byte 5 from raw advertising packet

  Multiple fields on same graph:
  %(prog)s --fields rawData.5 rawData.6 rawData.7  Compare multiple bytes
  %(prog)s --fields txPowerLevel manufacturerData.004c.bytes.0  Compare different fields

  Other options:
  %(prog)s --rssi                                 Plot RSSI for all devices
  %(prog)s --rssi --device XX --hours 12          Plot RSSI for device, last 12 hours
  %(prog)s --fields rawData.5 rawData.6 --save plot.png  Save to file
  %(prog)s --sensor temperature                   Plot from sensor_data table (legacy)
        '''
    )

    parser.add_argument('--list', action='store_true',
                       help='List available devices and show sample data')
    parser.add_argument('--clear', action='store_true',
                       help='Clear all data from the database')
    parser.add_argument('--field', type=str,
                       help='Plot single advertising data field (e.g., txPowerLevel)')
    parser.add_argument('--fields', type=str, nargs='+',
                       help='Plot multiple fields on same graph (e.g., rawData.5 rawData.6 rawData.7)')
    parser.add_argument('--sensor', type=str,
                       help='Sensor type to plot from sensor_data table (legacy)')
    parser.add_argument('--rssi', action='store_true',
                       help='Plot RSSI (signal strength)')
    parser.add_argument('--device', type=str,
                       help='Filter by device ID')
    parser.add_argument('--hours', type=int, default=24,
                       help='Hours of data to plot (default: 24)')
    parser.add_argument('--save', type=str,
                       help='Save plot to file instead of displaying')
    parser.add_argument('--db', type=str, default=DB_FILE,
                       help=f'Database file (default: {DB_FILE})')

    args = parser.parse_args()

    # Check if database exists
    if not Path(args.db).exists():
        print(f"Error: Database file not found: {args.db}")
        print("Make sure the BLE gateway server has been run first.")
        sys.exit(1)

    # Connect to database
    conn = sqlite3.connect(args.db)

    try:
        # Clear database
        if args.clear:
            clear_database(conn)
            return

        # List mode
        if args.list:
            list_available_data(conn)
            return

        # Plot RSSI
        if args.rssi:
            plot_rssi(conn, args.device, args.hours, args.save)
            return

        # Plot multiple advertising fields (NEW - multiple fields on same graph)
        if args.fields:
            plot_multiple_fields(conn, args.fields, args.device, args.hours, args.save)
            return

        # Plot single advertising field (NEW - extracts from raw data)
        if args.field:
            data = get_raw_field_data(conn, args.field, args.device, args.hours)
            device_name = None
            if args.device and data:
                device_name = data[0][3]
            plot_sensor_data(args.field, data, device_name, args.save)
            return

        # Plot sensor (legacy - from sensor_data table)
        if args.sensor:
            data = get_sensor_data(conn, args.sensor, args.device, args.hours)
            device_name = None
            if args.device and data:
                device_name = data[0][3]
            plot_sensor_data(args.sensor, data, device_name, args.save)
            return

        # No action specified
        parser.print_help()

    finally:
        conn.close()


if __name__ == '__main__':
    main()
