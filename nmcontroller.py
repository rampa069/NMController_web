# -*- coding: utf-8 -*-
"""
@file: nmcontroller.py
@author: NM
@copyright  Copyright (c) 2024, NMTech. All rights reserved

This script initializes and runs the NMMiner monitoring server using Flask.
It listens for miner updates via UDP and retrieves Bitcoin block reward and price information.
"""

import os
import socket
import sys
import time
import logging

import waitress
from flask import Flask, render_template, request, jsonify, redirect, url_for

from threads.btcinfo_thread import BtcInfoThread
from threads.udp_thread import UdpThread
from utils import hashrate_formatter, firmware_utils
from utils.time_format_utils import split_time_string, compact_uptime, time_difference
from utils.network_discovery import NetworkDeviceManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Set up template folder for Flask (for PyInstaller compatibility)
if hasattr(sys, '_MEIPASS'):
    template_folder = os.path.join(sys._MEIPASS, 'templates')
else:
    template_folder = 'templates'

app = Flask(__name__, template_folder=template_folder)
hasher = hashrate_formatter.HashrateFormatter()

# Initialize network device manager
network_manager = NetworkDeviceManager()


@app.route('/', methods=['GET', 'POST'])
@app.route('/web_monitor', methods=['GET', 'POST'])
def web_monitor():
    """
    Web route for the monitoring page.

    Retrieves miner data from both UDP thread and network discovery,
    processes statistics, and renders the web interface.

    :return: Rendered HTML template with miner details and Bitcoin stats.
    """
    nmminer_list = []
    total_hashrate = 0.0
    all_miners = {}

    # Get data from original UDP thread
    original_miners = udp_thread.get_miner_map()
    all_miners.update(original_miners)
    
    # Get data from network discovery (merge with original data)
    network_miners = network_manager.get_miner_map()
    
    # Merge network discovered devices with original data
    for ip, network_data in network_miners.items():
        if ip in all_miners:
            # Update existing entry with network data
            all_miners[ip].update(network_data)
        else:
            # Add new network device
            all_miners[ip] = network_data

    # Process all miner data
    for miner_id, miner_data in sorted(all_miners.items()):
        version = miner_data.get('Version', 'Unknown')

        # Check if firmware version is outdated
        if version != 'Unknown' and not firmware_utils.compare_versions(version, latest_version):
            version += '*'

        upTime, _ = split_time_string(miner_data.get('Uptime', '0'))

        # Handle share data safely
        share_data = miner_data.get("Share", "0/0")
        if isinstance(share_data, str) and '/' in share_data:
            try:
                if '(' in share_data and ')' in share_data:
                    # Format: "rejected/accepted (percentage%)"
                    parts = share_data.split('(')
                    rejected, accepted = parts[0].strip().split('/')
                    percentage = parts[1].replace(')', '').strip()
                    share_display = f'{rejected}/{accepted} ({percentage})'
                else:
                    # Simple format: "rejected/accepted"
                    rejected, accepted = share_data.split('/')
                    share_display = f'{rejected}/{accepted}'
            except (ValueError, IndexError):
                share_display = share_data
        else:
            share_display = str(share_data)

        # Append relevant miner details
        nmminer_list.append([
            miner_data.get('ip', 'Unknown'),
            miner_data.get("BoardType", 'Unknown'),
            miner_data.get('HashRate', '0'),
            share_display,
            miner_data.get('NetDiff', 0),
            miner_data.get('BestDiff', 0),
            miner_data.get('Valid', 0),
            round(float(miner_data.get('Temp', 0.0)), 1),
            miner_data.get('RSSI', 0),
            round(float(miner_data.get('FreeHeap', 0.0)), 2),
            version,
            compact_uptime(upTime),
            time_difference(miner_data.get('UpdateTime', 'Unknown')),
            miner_data.get('LastDiff', 0),
        ])

        # Convert and accumulate hashrate
        hashrate_value = miner_data.get('HashRate')
        if hashrate_value and str(hashrate_value) != '0':
            total_hashrate += hasher.convert_hashrate(hashrate_value)

    # Render template with miner statistics
    return render_template(
        'web_monitor.html',
        result=nmminer_list,
        totalHash=hasher.format_hashrate(total_hashrate),
        latest_version=latest_version,
        reward_value=btcinfo_thread.block_reward_value,
        block_reward=btcinfo_thread.block_reward,
        btc_price=btcinfo_thread.btc_price,
        btc_price_source=btcinfo_thread.btc_price_source,
    )


@app.route('/config/<device_ip>')
def device_config(device_ip):
    """
    Configuration page for a specific device.
    """
    # Get device info
    device = network_manager.get_device_by_ip(device_ip)
    config = network_manager.get_device_config(device_ip)
    
    if not device:
        return redirect(url_for('web_monitor'))
    
    return render_template(
        'device_config.html',
        device=device,
        config=config or {},
        device_ip=device_ip
    )


@app.route('/api/config/<device_ip>', methods=['GET', 'POST'])
def api_device_config(device_ip):
    """
    API endpoint for device configuration.
    """
    if request.method == 'GET':
        # Get current configuration
        config = network_manager.get_device_config(device_ip)
        if config:
            return jsonify(config)
        else:
            # Try to request config from device
            config = network_manager.request_config_from_device(device_ip)
            return jsonify(config or {})
    
    elif request.method == 'POST':
        # Update device configuration
        try:
            config = request.get_json()
            if not config:
                return jsonify({'error': 'No configuration data provided'}), 400
            
            # Send configuration to device
            success = network_manager.send_config_to_device(device_ip, config)
            
            if success:
                return jsonify({'success': True, 'message': 'Configuration sent successfully'})
            else:
                return jsonify({'error': 'Failed to send configuration to device'}), 500
                
        except Exception as e:
            logging.error(f"Error updating device config: {e}")
            return jsonify({'error': str(e)}), 500


@app.route('/api/devices')
def api_devices():
    """
    API endpoint to get all devices.
    """
    devices = []
    for device in network_manager.get_devices():
        device_dict = {
            'ip': device.ip,
            'device_id': device.device_id,
            'board_type': device.board_type,
            'hash_rate': device.hash_rate,
            'temp': device.temp,
            'rssi': device.rssi,
            'version': device.version,
            'uptime': device.uptime,
            'is_online': device.is_online,
            'update_time': device.update_time
        }
        devices.append(device_dict)
    
    return jsonify(devices)


def get_local_ip():
    """
    Retrieve the local IP address of the machine.

    :return: Local IP address as a string.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception as e:
        logging.error(f"Failed to retrieve local IP: {e}")
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


def logo_print():
    """Prints ASCII logo for the NMTech monitor."""
    print("""
            ___          ___         
           /\\__\\        /\\__\\    
          /::|  |      /::|  |       
         /:|:|  |     /:|:|  |       
        /:/|:|  |__  /:/|:|__|__     
       /:/ |:| /\\__\\/:/ |::::\\__\\
       \\/__|:|/:/  /\\/__/~~/:/  /  
           |:/:/  /       /:/  /     
           |::/  /       /:/  /      
           /:/  /       /:/  /       
           \\/__/        \\/__/      
    """)


if __name__ == "__main__":
    local_ip = get_local_ip()
    port = 7877

    logo_print()
    logging.info("NM Centralized Monitor Server running...")
    logging.info("NMMiner firmware version v0.3.01 or later is required.")

    # Retrieve latest firmware version
    latest_version = firmware_utils.get_latest_version()
    logging.info(f"The latest version of NMMiner is {latest_version}.")

    # Start monitoring threads
    btcinfo_thread = BtcInfoThread(name="BTC_Info", update_seconds=1800)
    udp_thread = UdpThread(name="NMMiner_Info")
    
    # Network device manager disabled to avoid port conflict with UdpThread
    # network_manager.start_listening()

    time.sleep(2)  # Allow threads to initialize

    logging.info(f"Access the web monitor at http://{local_ip}:{port} or http://localhost:{port}")

    # Open browser automatically on macOS
    cwd = os.getcwd()
    if '.app/Contents/Resources' in cwd:
        logging.info("Running on macOS")
        os.system('open "http://127.0.0.1:7877"')

    try:
        # Start the Flask server with Waitress
        waitress.serve(app, host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        logging.info("Shutting down server...")

    # Ensure proper shutdown of threads
    logging.info("Stopping threads...")
    udp_thread.stop()
    btcinfo_thread.stop()
    network_manager.stop_listening()

    logging.info("NM Centralized Monitor Server closed.")
