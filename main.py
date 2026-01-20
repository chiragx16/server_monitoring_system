import time
from datetime import datetime
from flask import Flask, render_template, jsonify, send_from_directory, abort
from flask_cors import CORS
import threading
import json
import subprocess
import platform
import os
import sys
import yaml
import ssl
from datetime import datetime, timedelta
from notifications import send_notification

def get_base_dir():
    """
    Returns directory where the executable is located.
    Works for both normal Python and PyInstaller exe.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
BUNDLE_DIR = os.path.join(BASE_DIR, "bundle")



# --- Configuration ---

# Load configuration from YAML file
CONFIG_FILE = os.path.join(BUNDLE_DIR,'config.yaml')

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            try:
                config = yaml.safe_load(f)
                return config
            except yaml.YAMLError as e:
                print(f"Error reading {CONFIG_FILE}: {e}")
                return {}
    else:
        print(f"{CONFIG_FILE} not found. Using default configuration.")
        return {
            "run": {
                "host": "0.0.0.0",
                "port": 9898
            },
            "ssl": {
                "cert": "",
                "key": ""
            },
            "ping_config": {  # Default ping configuration
                "interval": 1800,
                "recheck_delay": 120,
                "ping_count": 4,
                "timeout": 1,
                "fail_threshold": 2
            }
        }

# Load the configuration from YAML
config = load_config()

# Extracting values from the loaded configuration
host = config.get("run", {}).get("host", "0.0.0.0")
port = config.get("run", {}).get("port", 9898)
ssl_cert = config.get("ssl", {}).get("cert", "")
ssl_key = config.get("ssl", {}).get("key", "")

# Extract ping-related configuration
ping_interval = config.get("ping_config", {}).get("interval", 1800)
recheck_delay = config.get("ping_config", {}).get("recheck_delay", 120)
ping_count = config.get("ping_config", {}).get("ping_count", 4)
ping_timeout = config.get("ping_config", {}).get("timeout", 1)
fail_threshold = config.get("ping_config", {}).get("fail_threshold", 2)


# Load servers from JSON file
SERVERS_FILE = os.path.join(BUNDLE_DIR,'servers.json')
def load_servers():
    if os.path.exists(SERVERS_FILE):
        with open(SERVERS_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error reading {SERVERS_FILE}: {e}")
                return []
    else:
        print(f"{SERVERS_FILE} not found. No servers loaded.")
        return []


INTERVAL = ping_interval
RECHECK_DELAY = recheck_delay
PING_COUNT = ping_count
TIMEOUT = ping_timeout
FAIL_THRESHOLD = fail_threshold
LOG_FILE = os.path.join(BUNDLE_DIR,'server_monitoring.log')

# Global dictionary to store status for all servers
# Key: host:port, Value: status dictionary
all_servers_status = {}

# Initialize Flask app
app = Flask(
    __name__,
    template_folder=os.path.join(BUNDLE_DIR, "templates"),
    static_folder=os.path.join(BUNDLE_DIR, "static")
)

CORS(app)

# --- Logging Function ---
def log_status(server_key, status, message):
    """
    Logs the server status update to a file.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] | Server: {server_key} | Status: {status.upper()} | Message: {message}\n"
    
    # Write to a central log file
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(log_entry)
    except IOError as e:
        print(f"Error writing to log file {LOG_FILE}: {e}")

def ping_host_multiple(host, count=4, timeout=2):
    """
    Ping a host multiple times and return the number of successful pings.
    Returns tuple: (successful_pings, total_pings)
    """
    system = platform.system().lower()
    successful_pings = 0

    for i in range(count):
        if system == "windows":
            # -n 1 = send 1 ping
            # -w 1000 = timeout 1 second
            cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), host]
        else:
            # -c 1 = send 1 ping
            # -W 1 = timeout 1 second
            cmd = ["ping", "-c", "1", "-W", str(timeout), host]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if result.returncode == 0:
                successful_pings += 1
        except Exception as e:
            print(f"Ping {i+1} failed for {host}: {e}")
    
    return successful_pings, count

def check_server_status(host):
    """
    Check server status with recheck logic:
    1. Send 4 pings
    2. If 2+ fail, wait 2 minutes and recheck
    3. If still 2+ fail after recheck, mark as down
    
    Returns: (is_up, detail_message)
    """
    # First check
    success_count, total_count = ping_host_multiple(host, PING_COUNT, TIMEOUT)
    fail_count = total_count - success_count

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"Server {host}: 1st check: {success_count}/{total_count} pings."
    )

    # Trigger recheck
    if fail_count >= FAIL_THRESHOLD:
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Server {host}: Rechecking in {RECHECK_DELAY} seconds..."
        )

        time.sleep(RECHECK_DELAY)

        # Second check
        success_recheck, total_recheck = ping_host_multiple(host, PING_COUNT, TIMEOUT)
        fail_recheck = total_recheck - success_recheck

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"Server {host}: 2nd check: {success_recheck}/{total_recheck} pings."
        )

        if fail_recheck >= FAIL_THRESHOLD:
            return False, (
                f"1st check: {success_count}/{total_count}. "
                f"2nd check: {success_recheck}/{total_recheck}."
            )
        else:
            return True, (
                f"1st check: {success_count}/{total_count}. "
                f"2nd check: {success_recheck}/{total_recheck}. Server recovered."
            )

    # No recheck needed
    return True, f"1st check: {success_count}/{total_count}."

def check_single_server(server):
    host = server['host']
    name = server['name']
    server_key = host

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking server: {name} ({host})")

    is_up, detail_message = check_server_status(host)

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if server_key not in all_servers_status:
        all_servers_status[server_key] = {
            'name': name,
            'host': host,
            'status': 'unknown',
            'last_check': None,
            'check_count': 0,
            'up_count': 0,
            'down_count': 0,
            'uptime_percentage': 0,
            'history': []
        }

    status_data = all_servers_status[server_key]
    new_status = 'up' if is_up else 'down'

    if new_status != status_data['status']:
        log_status(
            server_key,
            new_status,
            f"Status changed from {status_data['status']} to {new_status}. {detail_message}"
        )

        send_notification(
            server_name=name,
            host=host,
            status=new_status,
            message=detail_message
        )
    elif new_status == 'down':
        log_status(server_key, new_status, f"Server remains DOWN. {detail_message}")

    status_data['last_check'] = current_time
    status_data['check_count'] += 1
    status_data['status'] = new_status

    if is_up:
        status_data['up_count'] += 1
    else:
        status_data['down_count'] += 1

    status_data['uptime_percentage'] = (
        status_data['up_count'] / status_data['check_count']
    ) * 100

    now = datetime.now()
    status_data['history'].append({'time': now, 'status': new_status})

    cutoff = now - timedelta(hours=48)
    status_data['history'] = [
        h for h in status_data['history'] if h['time'] >= cutoff
    ]

def update_status():
    global all_servers_status

    while True:
        SERVERS = load_servers()
        active_hosts = set()
        threads = []

        for server in SERVERS:
            active_hosts.add(server['host'])

            t = threading.Thread(
                target=check_single_server,
                args=(server,)
            )
            t.start()
            threads.append(t)

        # Wait for all server checks to finish
        for t in threads:
            t.join()

        # Remove deleted servers
        for key in list(all_servers_status.keys()):
            if key not in active_hosts:
                del all_servers_status[key]

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Check cycle completed. Next check in 30 minutes.")
        time.sleep(INTERVAL)



@app.route('/')
def index():
    """Render the dashboard page."""
    SERVERS = load_servers()
    return render_template('test2.html', servers=SERVERS)

@app.route('/api/status')
def get_status():
    serialized = {}
    SERVERS = load_servers()

    for key, server in all_servers_status.items():
        # Get the server name for the given key
        server_info = next((s for s in SERVERS if s['host'] == key), {'name': 'Unknown Server'})
        
        serialized[key] = {
            **server,
            'name': server_info['name'], # Ensure the name is included
            'history': [
                {
                    # Use ISO format for better parsing in JS
                    'time': h['time'].isoformat(),
                    'status': h['status']
                }
                for h in server['history']
            ]
        }

    return jsonify(serialized)

@app.route('/logs/<server_key>')
def log_details_page(server_key):
    """Render the log details page."""
    SERVERS = load_servers()
    server = next((s for s in SERVERS if s['host'] == server_key), None)
    if not server:
        abort(404)
        
    return render_template('log_details.html', server_key=server_key, server_name=server['name'])

@app.route('/api/logs/<server_key>')
def get_server_logs(server_key):
    """
    Retrieves ALL log entries for a specific server (no time limit).
    """
    log_entries = []

    try:
        with open(LOG_FILE, 'r') as f:
            # Read all lines and reverse to process from newest to oldest
            for line in reversed(f.readlines()):
                # Check if the line contains the server key
                if f"Server: {server_key}" in line:
                    log_entries.append(line.strip())
                    
    except FileNotFoundError:
        return jsonify({"logs": [], "error": "Log file not found."})
    except Exception as e:
        return jsonify({"logs": [], "error": f"An error occurred reading the log file: {e}"})

    # Reverse back to chronological order (oldest to newest) for display
    return jsonify({
        "logs": log_entries[::-1], 
        "server_name": all_servers_status.get(server_key, {}).get('name', 'Unknown'),
        "total_logs": len(log_entries)
    })


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    SERVERS = load_servers()
    ssl_context = None  # Default is no SSL

    # Start the status update thread
    status_thread = threading.Thread(target=update_status)
    status_thread.daemon = True
    status_thread.start()
    
    # Initialize log file if it doesn't exist
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] | Monitoring started.\n")

    print("Starting server dashboard...")
    print(f"Monitoring {len(SERVERS)} servers.")
    print(f"Check interval: {INTERVAL} seconds.")
    print(f"Ping packets per check: {PING_COUNT}")
    print(f"Fail threshold for recheck: {FAIL_THRESHOLD} packets")
    print(f"Recheck delay: {RECHECK_DELAY} seconds")
    

    # Check if SSL cert and key are provided (not empty strings)
    if ssl_cert and ssl_key:
        # Check if the SSL certificate and key files exist before starting Flask
        if os.path.exists(ssl_cert) and os.path.exists(ssl_key):
            print("Starting the app with SSL...")
            ssl_context = (ssl_cert, ssl_key)
        else:
            print("SSL certificate or key file not found. Running without SSL.")
    else:
        print("No SSL configuration provided. Running without SSL.")

    # Run the Flask app
    app.run(
        debug=False,
        host=host,  # Use the host defined in the config.yaml
        port=port,  # Use the port defined in the config.yaml
        ssl_context=ssl_context  # Pass None if SSL is not enabled
    )