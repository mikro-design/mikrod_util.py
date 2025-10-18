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


def list_available_data(conn):
    """List all available devices and sensors"""
    print("\n" + "=" * 60)
    print("Available Data in Database")
    print("=" * 60)

    # Devices
    devices = get_available_devices(conn)
    if devices:
        print("\nDevices with sensor data:")
        for dev_id, dev_name, count in devices:
            print(f"  - {dev_name or 'Unknown'} ({dev_id}): {count} readings")
    else:
        print("\nNo devices found in database")

    # Sensor types
    sensor_types = get_sensor_types(conn)
    if sensor_types:
        print("\nAvailable sensor types:")
        for sensor_type, unit, count in sensor_types:
            print(f"  - {sensor_type}: {count} readings ({unit})")
    else:
        print("\nNo sensor data found in database")

    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Plot BLE sensor data from gateway database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s --list                          List available devices and sensors
  %(prog)s --sensor temperature            Plot temperature for all devices
  %(prog)s --sensor humidity --device XX   Plot humidity for specific device
  %(prog)s --rssi                          Plot RSSI for all devices
  %(prog)s --rssi --device XX --hours 12   Plot RSSI for device, last 12 hours
  %(prog)s --sensor temp --save plot.png   Save plot to file
        '''
    )

    parser.add_argument('--list', action='store_true',
                       help='List available devices and sensor types')
    parser.add_argument('--sensor', type=str,
                       help='Sensor type to plot (temperature, humidity, etc.)')
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
        # List mode
        if args.list:
            list_available_data(conn)
            return

        # Plot RSSI
        if args.rssi:
            plot_rssi(conn, args.device, args.hours, args.save)
            return

        # Plot sensor
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
