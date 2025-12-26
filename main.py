# server_dashboard.py
import socket
import time
from datetime import datetime
from flask import Flask, render_template, jsonify, send_from_directory, abort
from flask_cors import CORS
import threading
import json
import subprocess
import platform
import os
from datetime import datetime, timedelta


# --- Configuration ---
# Load servers from JSON file
CONFIG_FILE = 'servers.json'
def load_servers():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                print(f"Error reading {CONFIG_FILE}: {e}")
                return []
    else:
        print(f"{CONFIG_FILE} not found. No servers loaded.")
        return []


INTERVAL = 30       # Check interval in seconds
TIMEOUT = 5         # Connection timeout in seconds
LOG_FILE = 'server_monitoring.log'

# Global dictionary to store status for all servers
# Key: host:port, Value: status dictionary
all_servers_status = {}

# Initialize Flask app
app = Flask(__name__)
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

def ping_host(host, timeout=2):
    """
    Ping a host to check network connectivity.
    Returns True if host responds, False otherwise.
    """
    system = platform.system().lower()

    if system == "windows":
        # -n 1 = send 1 ping
        # -w timeout in milliseconds
        cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), host]
    else:
        # -c 1 = send 1 ping
        # -W timeout in seconds
        cmd = ["ping", "-c", "1", "-W", str(timeout), host]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Ping failed for {host}: {e}")
        return False

def update_status():
    global all_servers_status

    while True:
        # Load servers on every check to pick up new/removed servers
        SERVERS = load_servers()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Keep track of active hosts to remove deleted servers later
        active_hosts = set()

        for server in SERVERS:
            host = server['host']
            active_hosts.add(host)
            server_key = host
            
            is_up = ping_host(host, TIMEOUT)

            if server_key not in all_servers_status:
                all_servers_status[server_key] = {
                    'name': server['name'],
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
                log_status(server_key, new_status, f"Status changed from {status_data['status']} to {new_status}")
            if new_status == 'down':
                log_status(server_key, new_status, "Server is currently unreachable.")

            status_data['last_check'] = current_time
            status_data['check_count'] += 1
            status_data['status'] = new_status

            if is_up:
                status_data['up_count'] += 1
            else:
                status_data['down_count'] += 1

            if status_data['check_count'] > 0:
                status_data['uptime_percentage'] = (status_data['up_count'] / status_data['check_count']) * 100

            now = datetime.now()
            status_data['history'].append({'time': now, 'status': new_status})
            cutoff = now - timedelta(hours=48)
            status_data['history'] = [h for h in status_data['history'] if h['time'] >= cutoff]

        # Remove servers that are no longer in servers.json
        for key in list(all_servers_status.keys()):
            if key not in active_hosts:
                del all_servers_status[key]

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
    Filters the log file for entries of a specific server within the last 48 hours.
    """
    cutoff_time = datetime.now() - timedelta(hours=48)
    log_entries = []

    try:
        with open(LOG_FILE, 'r') as f:
            # Read all lines and reverse to process from newest to oldest
            for line in reversed(f.readlines()):
                # Extract timestamp and server key from the log line format: 
                # [YYYY-MM-DD HH:MM:SS] | Server: <key> | ...
                
                try:
                    # Check if the line contains the server key
                    if f"Server: {server_key}" in line:
                        timestamp_str = line[1:20] # [YYYY-MM-DD HH:MM:SS]
                        log_timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                        
                        if log_timestamp >= cutoff_time:
                            log_entries.append(line.strip())
                        else:
                            # Since we are reading in reverse chronological order, 
                            # we can stop once we hit the cutoff time
                            break 
                except ValueError:
                    # Ignore lines with malformed timestamps
                    continue
    except FileNotFoundError:
        return jsonify({"logs": [], "error": "Log file not found."})
    except Exception as e:
        return jsonify({"logs": [], "error": f"An error occurred reading the log file: {e}"})

    # Reverse back to chronological order (oldest to newest) for display
    return jsonify({"logs": log_entries[::-1], "server_name": all_servers_status.get(server_key, {}).get('name', 'Unknown')})


if __name__ == "__main__":
    SERVERS = load_servers()

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
    print("Access the dashboard at http://localhost:5000")
    
    # Run the Flask app
    app.run(debug=True, host='0.0.0.0', port=9898)