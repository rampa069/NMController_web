"""
Network device discovery and management utilities.
Based on the NMController_martianoids network functionality.
"""

import json
import socket
import threading
import time
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional


@dataclass
class NetworkDevice:
    """Represents a network-connected NM device."""
    ip: str
    port: int = 12345
    device_id: str = ""
    is_online: bool = True
    hash_rate: str = "0"
    share: str = "0/0"
    net_diff: str = "0"
    pool_diff: str = "0"
    last_diff: str = "0"
    best_diff: str = "0"
    valid: int = 0
    progress: float = 0.0
    temp: float = 0.0
    rssi: float = 0.0
    free_heap: float = 0.0
    uptime: str = "0"
    version: str = ""
    board_type: str = ""
    pool_in_use: str = ""
    update_time: str = ""
    config: Optional[Dict] = None


class NetworkDeviceManager:
    """Manages network device discovery and configuration."""
    
    STATUS_PORT = 12345  # Port for device status updates
    CONFIG_PORT = 12346  # Port for device configuration updates  
    COMMAND_PORT = 12347  # Port for sending commands to devices
    
    def __init__(self):
        self.devices: Dict[str, NetworkDevice] = {}
        self.device_configs: Dict[str, Dict] = {}
        self._listening = False
        self._status_thread = None
        self._config_thread = None
        self.logger = logging.getLogger(__name__)
        
    def start_listening(self):
        """Start listening for device updates."""
        if self._listening:
            return
            
        self._listening = True
        self._status_thread = threading.Thread(target=self._listen_status_updates, daemon=True)
        self._config_thread = threading.Thread(target=self._listen_config_updates, daemon=True)
        
        self._status_thread.start()
        self._config_thread.start()
        
        self.logger.info("Network device manager started listening")
        
    def stop_listening(self):
        """Stop listening for device updates."""
        self._listening = False
        if self._status_thread:
            self._status_thread.join(timeout=1)
        if self._config_thread:
            self._config_thread.join(timeout=1)
            
        self.logger.info("Network device manager stopped listening")
        
    def _listen_status_updates(self):
        """Listen for device status updates on STATUS_PORT."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(('0.0.0.0', self.STATUS_PORT))
            sock.settimeout(0.1)
            self.logger.info(f"Listening for status updates on port {self.STATUS_PORT}")
            
            while self._listening:
                try:
                    data, addr = sock.recvfrom(4096)
                    self._handle_status_update(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    self.logger.error(f"Error receiving status update: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error setting up status listener: {e}")
        finally:
            sock.close()
            
    def _listen_config_updates(self):
        """Listen for device configuration updates on CONFIG_PORT."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(('0.0.0.0', self.CONFIG_PORT))
            sock.settimeout(0.1)
            self.logger.info(f"Listening for config updates on port {self.CONFIG_PORT}")
            
            while self._listening:
                try:
                    data, addr = sock.recvfrom(4096)
                    self._handle_config_update(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    self.logger.error(f"Error receiving config update: {e}")
                    
        except Exception as e:
            self.logger.error(f"Error setting up config listener: {e}")
        finally:
            sock.close()
            
    def _handle_status_update(self, data: bytes, addr: tuple):
        """Handle incoming status update from a device."""
        try:
            status = json.loads(data.decode('utf-8'))
            ip = addr[0]
            
            # Update existing device or create new one
            if ip in self.devices:
                device = self.devices[ip]
            else:
                device = NetworkDevice(ip=ip)
                self.devices[ip] = device
                
            # Update device status
            device.hash_rate = status.get('HashRate', device.hash_rate)
            device.share = status.get('Share', device.share)
            device.net_diff = status.get('NetDiff', device.net_diff)
            device.pool_diff = status.get('PoolDiff', device.pool_diff)
            device.last_diff = status.get('LastDiff', device.last_diff)
            device.best_diff = status.get('BestDiff', device.best_diff)
            device.valid = status.get('Valid', device.valid)
            device.progress = status.get('Progress', device.progress)
            device.temp = status.get('Temp', device.temp)
            device.rssi = status.get('RSSI', device.rssi)
            device.free_heap = status.get('FreeHeap', device.free_heap)
            device.uptime = status.get('Uptime', device.uptime)
            device.version = status.get('Version', device.version)
            device.board_type = status.get('BoardType', device.board_type)
            device.pool_in_use = status.get('PoolInUse', device.pool_in_use)
            device.update_time = time.strftime("%Y-%m-%d %H:%M:%S")
            device.is_online = True
            
            if not device.device_id and device.board_type:
                device.device_id = device.board_type
                
            self.logger.debug(f"Status update from {ip}: {device.board_type}")
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in status update from {addr[0]}: {e}")
        except Exception as e:
            self.logger.error(f"Error handling status update from {addr[0]}: {e}")
            
    def _handle_config_update(self, data: bytes, addr: tuple):
        """Handle incoming configuration update from a device."""
        try:
            config = json.loads(data.decode('utf-8'))
            ip = addr[0]
            
            # Store device configuration
            self.device_configs[ip] = config
            
            # Update device info if we have it
            if ip in self.devices:
                device = self.devices[ip]
                device.config = config
                if 'BoardType' in config and not device.device_id:
                    device.device_id = config['BoardType']
                if 'Version' in config:
                    device.version = config['Version']
                    
            self.logger.info(f"Configuration update from {ip}")
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in config update from {addr[0]}: {e}")
        except Exception as e:
            self.logger.error(f"Error handling config update from {addr[0]}: {e}")
            
    def get_devices(self) -> List[NetworkDevice]:
        """Get list of all discovered devices."""
        return list(self.devices.values())
        
    def get_device_by_ip(self, ip: str) -> Optional[NetworkDevice]:
        """Get device by IP address."""
        return self.devices.get(ip)
        
    def get_device_config(self, ip: str) -> Optional[Dict]:
        """Get device configuration by IP address."""
        return self.device_configs.get(ip)
        
    def send_config_to_device(self, ip: str, config: Dict) -> bool:
        """Send configuration to a specific device."""
        try:
            json_data = json.dumps(config)
            data = json_data.encode('utf-8')
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1.0)
            
            # Send configuration multiple times to ensure delivery
            for _ in range(3):
                sock.sendto(data, (ip, self.COMMAND_PORT))
                time.sleep(0.1)
                
            sock.close()
            self.logger.info(f"Configuration sent to {ip}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending config to {ip}: {e}")
            return False
            
    def request_config_from_device(self, ip: str) -> Optional[Dict]:
        """Request current configuration from a device."""
        try:
            request = json.dumps({"command": "get_config"})
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            
            sock.sendto(request.encode('utf-8'), (ip, self.COMMAND_PORT))
            
            # Wait for response
            data, addr = sock.recvfrom(4096)
            config = json.loads(data.decode('utf-8'))
            
            sock.close()
            self.logger.info(f"Configuration received from {ip}")
            return config
            
        except socket.timeout:
            self.logger.warning(f"Timeout requesting config from {ip}")
        except Exception as e:
            self.logger.error(f"Error requesting config from {ip}: {e}")
            
        return None
        
    def get_miner_map(self) -> Dict[str, Dict]:
        """Get miner map compatible with the original application format."""
        miner_map = {}
        
        for ip, device in self.devices.items():
            miner_map[ip] = {
                'ip': device.ip,
                'BoardType': device.board_type,
                'HashRate': device.hash_rate,
                'Share': device.share,
                'NetDiff': device.net_diff,
                'BestDiff': device.best_diff,
                'Valid': device.valid,
                'Temp': device.temp,
                'RSSI': device.rssi,
                'FreeHeap': device.free_heap,
                'Version': device.version,
                'Uptime': device.uptime,
                'UpdateTime': device.update_time,
                'LastDiff': device.last_diff,
            }
            
        return miner_map
        
    def cleanup_offline_devices(self, timeout_seconds: int = 300):
        """Remove devices that haven't been seen for a while."""
        current_time = time.time()
        to_remove = []
        
        for ip, device in self.devices.items():
            if device.update_time:
                try:
                    device_time = time.mktime(time.strptime(device.update_time, "%Y-%m-%d %H:%M:%S"))
                    if current_time - device_time > timeout_seconds:
                        to_remove.append(ip)
                except ValueError:
                    pass  # Invalid time format, keep device
                    
        for ip in to_remove:
            del self.devices[ip]
            if ip in self.device_configs:
                del self.device_configs[ip]
            self.logger.info(f"Removed offline device {ip}")