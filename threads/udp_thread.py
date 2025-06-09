import socket
import json
import time
import logging
import select
import threading
from threads.managed_thread import ManagedThread

# Configure logging for better debugging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class UdpThread(ManagedThread):
    """
    Singleton UDP listener thread for receiving and processing NMMiner data.
    This class continuously listens for UDP packets, parses JSON data,
    and maintains a mapping of miner statuses.
    """
    _instance = None
    _lock = threading.Lock()  # Lock to ensure thread safety in instance creation
    status_sock = None  # Socket for status updates (port 12345)
    config_sock = None  # Socket for config updates (port 12346)

    def __new__(cls, *args, **kwargs):
        """Ensure only one instance is created."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(UdpThread, cls).__new__(cls)
                cls._instance._initialized = False  # Flag to check initialization
            elif cls._instance._initialized:
                # Return existing initialized instance without re-initializing
                return cls._instance
        return cls._instance


    def __init__(self, name="UdpThread", ip="0.0.0.0", port=12345, update_seconds=0.5):
        """Initializes the UDP listener thread."""
        if self._initialized:
            return  # Prevent re-initialization if already initialized
        
        super().__init__(name=name, update_seconds=update_seconds)

        self.lock = threading.Lock()  # Lock for thread-safe updates
        self.nmminer_map = {}  # Dictionary to store miner data
        self.status_sock = None
        self.config_sock = None
        self.last_cleanup_time = 0  # Track last cleanup time

        # Only initialize sockets if not already done
        if UdpThread.status_sock is None:
            # Socket initialization for both status and config
            UdpThread.status_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            UdpThread.status_sock.settimeout(0.1)
            
            UdpThread.config_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            UdpThread.config_sock.settimeout(0.1)

            try:
                UdpThread.status_sock.bind((ip, port))  # Port 12345 for status
                logging.info(f"{self.get_thread_name()} Listening for status on {ip}:{port}")
                
                UdpThread.config_sock.bind((ip, port + 1))  # Port 12346 for config
                logging.info(f"{self.get_thread_name()} Listening for config on {ip}:{port + 1}")
            except socket.error as e:
                logging.error(f"{self.get_thread_name()} Error binding sockets. Error: {e}")
                if UdpThread.status_sock:
                    UdpThread.status_sock.close()
                    UdpThread.status_sock = None
                if UdpThread.config_sock:
                    UdpThread.config_sock.close()
                    UdpThread.config_sock = None
                raise
            except Exception as e:
                logging.exception(f"{self.get_thread_name()} Unexpected error while setting up sockets: {e}")
                if UdpThread.status_sock:
                    UdpThread.status_sock.close()
                    UdpThread.status_sock = None
                if UdpThread.config_sock:
                    UdpThread.config_sock.close()
                    UdpThread.config_sock = None
                raise
        
        # Use class-level sockets
        self.status_sock = UdpThread.status_sock
        self.config_sock = UdpThread.config_sock
        self._initialized = True  # Mark as initialized

    def get_miner_map(self):
        """Retrieves the current miner data map."""
        with self.lock:
            # Only cleanup periodically (every 60 seconds) instead of every request
            current_time = time.time()
            if current_time - self.last_cleanup_time > 60:
                self._cleanup_offline_devices()
                self.last_cleanup_time = current_time
            return self.nmminer_map.copy()
    
    def _cleanup_offline_devices(self, timeout_seconds=300):
        """Remove devices that haven't been seen for a while (default 5 minutes)."""
        current_time = time.time()
        to_remove = []
        
        for ip, miner_data in self.nmminer_map.items():
            update_time_str = miner_data.get('UpdateTime')
            if update_time_str:
                try:
                    device_time = time.mktime(time.strptime(update_time_str, "%Y-%m-%d %H:%M:%S"))
                    if current_time - device_time > timeout_seconds:
                        to_remove.append(ip)
                except ValueError:
                    # Invalid time format, remove old entry
                    to_remove.append(ip)
        
        if to_remove:
            for ip in to_remove:
                del self.nmminer_map[ip]
                logging.info(f"{self.get_thread_name()} Removed offline device {ip} (last seen > {timeout_seconds}s ago)")
            logging.info(f"{self.get_thread_name()} Cleanup removed {len(to_remove)} offline devices")

    def run(self):
        """Main loop of the thread. Listens for UDP messages and processes data."""
        logging.info(f"{self.get_thread_name()} Starting UDP listener...")

        while not self.should_stop():
            try:
                if self.needs_update():
                    self.receive_data()
                else:
                    time.sleep(0.1)  # Prevent excessive CPU usage
            except Exception as e:
                logging.exception(f"{self.get_thread_name()} Unexpected error in run loop: {e}")

    def receive_data(self):
        """Listens for incoming UDP data on both status and config sockets, parses JSON, and updates nmminer_map."""
        if (self.status_sock is None or self.status_sock.fileno() == -1 or 
            self.config_sock is None or self.config_sock.fileno() == -1):
            logging.debug(f"{self.get_thread_name()} UDP sockets have been closed and unable to receive data.")
            return

        # Use select to check both sockets
        ready = select.select([self.status_sock, self.config_sock], [], [], 0.1)
        if ready[0]:
            for sock in ready[0]:
                try:
                    data, addr = sock.recvfrom(4096)  # Receive up to 4096 bytes
                    if sock == self.status_sock:
                        logging.debug(f"{self.get_thread_name()} Status data received from {addr[0]}")
                    else:
                        logging.debug(f"{self.get_thread_name()} Config data received from {addr[0]}")
                    self.process_data(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    logging.error(f"{self.get_thread_name()} Error receiving data: {e}")
        else:
            logging.debug(f"{self.get_thread_name()} No data received this cycle.")

    def process_data(self, data, addr):
        """
        Parses incoming JSON data and updates the miner map.

        :param data: Raw UDP data received from the socket.
        :param addr: Address tuple (ip, port) of the sender.
        """
        try:
            # Decode data and strip any trailing null bytes or whitespace
            decoded_data = data.decode('utf-8').rstrip('\x00').strip()
            
            # Check if the JSON appears to be truncated (doesn't end with '}')
            if not decoded_data.endswith('}'):
                logging.warning(f"{self.get_thread_name()} Received truncated JSON from {addr[0]}: length={len(decoded_data)}, ends with='{decoded_data[-10:]}'")
                return
            
            json_data = json.loads(decoded_data)
            ip = json_data.get("ip") or addr[0]  # Use sender IP if not in data

            json_data["ip"] = ip  # Ensure IP is always set
            json_data["UpdateTime"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            with self.lock:
                # Determine packet type based on content
                has_config_fields = bool(json_data.get('Version') or json_data.get('BoardType') or json_data.get('WiFiSSID'))
                has_status_fields = bool(json_data.get('HashRate') or json_data.get('Temp') or json_data.get('RSSI'))
                
                if ip in self.nmminer_map:
                    # Device exists, merge data intelligently
                    existing_data = self.nmminer_map[ip].copy()
                    
                    # Always merge new data, but preserve important existing fields if not in new packet
                    for key, value in json_data.items():
                        if value and value != '' and value != 0:  # Only update with meaningful values
                            existing_data[key] = value
                    
                    # Always update timestamp
                    existing_data["UpdateTime"] = json_data["UpdateTime"]
                    
                    self.nmminer_map[ip] = existing_data
                    
                    packet_type = "config" if has_config_fields and not has_status_fields else "status" if has_status_fields and not has_config_fields else "mixed"
                    logging.info(f"{self.get_thread_name()} Merged {packet_type} packet for {ip}: V={existing_data.get('Version', 'N/A')}, BT={existing_data.get('BoardType', 'N/A')}, HR={existing_data.get('HashRate', 'N/A')}")
                else:
                    # New device
                    self.nmminer_map[ip] = json_data
                    packet_type = "config" if has_config_fields else "status" if has_status_fields else "unknown"
                    logging.info(f"{self.get_thread_name()} New device {ip} ({packet_type} packet): V={json_data.get('Version', 'N/A')}, BT={json_data.get('BoardType', 'N/A')}")

            logging.debug(f"{self.get_thread_name()} Updated miner data for IP: {ip}")

        except json.JSONDecodeError as e:
            decoded_data = data.decode('utf-8', errors='replace').rstrip('\x00').strip()
            logging.error(f"{self.get_thread_name()} Failed to decode JSON from {addr[0]}: length={len(decoded_data)}, data='{decoded_data[:100]}...{decoded_data[-50:]}', Error: {e}")
        except Exception as e:
            logging.exception(f"{self.get_thread_name()} Unexpected error in JSON processing: {e}")

    def stop(self):
        """Stops the thread and closes the sockets."""
        super().stop()  # Gracefully stop the thread
        if UdpThread.status_sock:
            UdpThread.status_sock.close()  # Close status socket to free the port
            UdpThread.status_sock = None
        if UdpThread.config_sock:
            UdpThread.config_sock.close()  # Close config socket to free the port
            UdpThread.config_sock = None
        self.status_sock = None
        self.config_sock = None
        logging.info(f"{self.get_thread_name()} Sockets closed and thread stopped.")


# Usage Example:
if __name__ == "__main__":
    udp_thread_1 = UdpThread(port=12345, update_seconds=1)
    udp_thread_2 = UdpThread()  # This should return the same instance

    print(f"Both instances are the same: {udp_thread_1 is udp_thread_2}")  # Should print True


    time.sleep(10)  # Let it run for a while
    udp_thread_1.stop()  # Stop the listener
