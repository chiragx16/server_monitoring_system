import os
import sys
import yaml
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

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


# --- Configuration Loading ---

CONFIG_FILE = os.path.join(BUNDLE_DIR,'config.yaml')

def load_notification_config():
    """Load notification configuration from YAML file."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            try:
                config = yaml.safe_load(f)
                return config
            except yaml.YAMLError as e:
                print(f"Error reading {CONFIG_FILE}: {e}")
                return get_default_config()
    else:
        print(f"{CONFIG_FILE} not found. Creating default configuration file.")
        default_config = get_default_config()
        save_default_config(default_config)
        return default_config

def get_default_config():
    """Return default configuration structure."""
    return {
        "notifications": {
            "enabled": True,
            "notify_on_down": True,
            "notify_on_recovery": True,
            "cooldown_minutes": 30  # Prevent notification spam
        },
        "twilio": {
            "account_sid": "YOUR_TWILIO_ACCOUNT_SID",
            "auth_token": "YOUR_TWILIO_AUTH_TOKEN",
            "from_number": "+1234567890",
            "to_numbers": ["+1234567890"]  # List of phone numbers to notify
        },
        "email": {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "username": "your_email@gmail.com",
            "password": "your_app_password",
            "from_email": "your_email@gmail.com",
            "to_emails": ["recipient@example.com"]  # List of email addresses
        }
    }

def save_default_config(config):
    """Save default configuration to file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        print(f"Default configuration saved to {CONFIG_FILE}. Please update with your credentials.")
    except Exception as e:
        print(f"Error saving default config: {e}")

# Load configuration
notification_config = load_notification_config()

# Track last notification time to prevent spam
last_notification_times = {}

# --- SMS Notification via Twilio ---

def send_sms_notification(server_name, host, status, message):
    """
    Send SMS notification via Twilio.
    Returns: (success: bool, error_message: str or None)
    """
    try:
        twilio_config = notification_config.get('twilio', {})
        account_sid = twilio_config.get('account_sid')
        auth_token = twilio_config.get('auth_token')
        from_number = twilio_config.get('from_number')
        to_numbers = twilio_config.get('to_numbers', [])

        # Validate configuration
        if not all([account_sid, auth_token, from_number, to_numbers]):
            return False, "Twilio configuration incomplete"

        # Skip if using default placeholder values
        if account_sid == "YOUR_TWILIO_ACCOUNT_SID":
            return False, "Twilio credentials not configured"

        # Initialize Twilio client
        client = Client(account_sid, auth_token)

        # Prepare message
        sms_body = f"🚨 Server Alert 🚨\n\n"
        sms_body += f"Server: {server_name}\n"
        sms_body += f"Host: {host}\n"
        sms_body += f"Status: {status.upper()}\n"
        sms_body += f"Details: {message}\n"
        sms_body += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        # Send to all configured numbers
        success_count = 0
        errors = []

        for to_number in to_numbers:
            try:
                message_obj = client.messages.create(
                    body=sms_body,
                    from_=from_number,
                    to=to_number
                )
                success_count += 1
                print(f"SMS sent successfully to {to_number}. SID: {message_obj.sid}")
            except TwilioRestException as e:
                error_msg = f"Failed to send to {to_number}: {e.msg}"
                errors.append(error_msg)
                print(error_msg)

        if success_count > 0:
            return True, None
        else:
            return False, "; ".join(errors)

    except Exception as e:
        error_msg = f"SMS notification failed: {str(e)}"
        print(error_msg)
        return False, error_msg

# --- Email Notification via SMTP ---

def send_email_notification(server_name, host, status, message):
    """
    Send email notification via SMTP.
    Returns: (success: bool, error_message: str or None)
    """
    try:
        email_config = notification_config.get('email', {})
        smtp_server = email_config.get('smtp_server')
        smtp_port = email_config.get('smtp_port', 587)
        username = email_config.get('username')
        password = email_config.get('password')
        from_email = email_config.get('from_email')
        to_emails = email_config.get('to_emails', [])

        # Validate configuration
        if not all([smtp_server, username, password, from_email, to_emails]):
            return False, "Email configuration incomplete"

        # Skip if using default placeholder values
        if username == "your_email@gmail.com":
            return False, "Email credentials not configured"

        # Create message
        msg = MIMEMultipart('alternative')
        
        # Set subject based on status
        if status.lower() == 'down':
            msg['Subject'] = f"🚨 Server DOWN Alert: {server_name}"
        else:
            msg['Subject'] = f"✅ Server Recovered: {server_name}"
        
        msg['From'] = from_email
        msg['To'] = ', '.join(to_emails)

        # Create HTML email body
        html_body = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; }}
                    .alert-box {{ 
                        padding: 20px; 
                        border-radius: 5px; 
                        margin: 20px 0;
                        {'background-color: #fee;' if status.lower() == 'down' else 'background-color: #efe;'}
                    }}
                    .server-info {{ margin: 10px 0; }}
                    .label {{ font-weight: bold; }}
                    .status {{ 
                        font-size: 18px; 
                        font-weight: bold;
                        {'color: #d00;' if status.lower() == 'down' else 'color: #0a0;'}
                    }}
                </style>
            </head>
            <body>
                <h2>{'🚨 Server Status Alert' if status.lower() == 'down' else '✅ Server Recovery Notice'}</h2>
                <div class="alert-box">
                    <div class="server-info">
                        <span class="label">Server Name:</span> {server_name}
                    </div>
                    <div class="server-info">
                        <span class="label">Host:</span> {host}
                    </div>
                    <div class="server-info">
                        <span class="label">Status:</span> <span class="status">{status.upper()}</span>
                    </div>
                    <div class="server-info">
                        <span class="label">Details:</span> {message}
                    </div>
                    <div class="server-info">
                        <span class="label">Time:</span> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                    </div>
                </div>
                <p><small>This is an automated notification from your server monitoring system.</small></p>
            </body>
        </html>
        """

        # Create plain text version as fallback
        text_body = f"""
Server Status Alert

Server Name: {server_name}
Host: {host}
Status: {status.upper()}
Details: {message}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---
This is an automated notification from your server monitoring system.
        """

        # Attach both versions
        part1 = MIMEText(text_body, 'plain')
        part2 = MIMEText(html_body, 'html')
        msg.attach(part1)
        msg.attach(part2)

        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Enable TLS encryption
            server.login(username, password)
            server.send_message(msg)

        print(f"Email sent successfully to {', '.join(to_emails)}")
        return True, None

    except Exception as e:
        error_msg = f"Email notification failed: {str(e)}"
        print(error_msg)
        return False, error_msg

# --- Main Notification Handler ---

def should_send_notification(server_key, status):
    """
    Check if notification should be sent based on cooldown period.
    Prevents notification spam.
    """
    notif_config = notification_config.get('notifications', {})
    cooldown_minutes = notif_config.get('cooldown_minutes', 30)
    
    current_time = datetime.now()
    
    if server_key in last_notification_times:
        last_time = last_notification_times[server_key]
        time_diff = (current_time - last_time).total_seconds() / 60
        
        if time_diff < cooldown_minutes:
            print(f"Notification cooldown active for {server_key}. {cooldown_minutes - time_diff:.1f} minutes remaining.")
            return False
    
    return True

def send_notification(server_name, host, status, message):
    """
    Main notification function that tries SMS first, then falls back to email.
    
    Args:
        server_name: Name of the server
        host: Host address
        status: 'up' or 'down'
        message: Detailed message about the status
    
    Returns:
        bool: True if notification was sent successfully (via either method)
    """
    notif_config = notification_config.get('notifications', {})
    
    # Check if notifications are enabled
    if not notif_config.get('enabled', True):
        print("Notifications are disabled in configuration.")
        return False
    
    # Check if we should notify for this status
    if status.lower() == 'down' and not notif_config.get('notify_on_down', True):
        print("Down notifications are disabled.")
        return False
    
    if status.lower() == 'up' and not notif_config.get('notify_on_recovery', True):
        print("Recovery notifications are disabled.")
        return False
    
    # Check cooldown period
    server_key = host
    if not should_send_notification(server_key, status):
        return False
    
    print(f"\n{'='*60}")
    print(f"Sending notification for {server_name} ({host}) - Status: {status.upper()}")
    print(f"{'='*60}")
    
    # Try SMS first
    print("Attempting SMS notification via Twilio...")
    sms_success, sms_error = send_sms_notification(server_name, host, status, message)
    
    if sms_success:
        print("✓ SMS notification sent successfully!")
        last_notification_times[server_key] = datetime.now()
        return True
    else:
        print(f"✗ SMS notification failed: {sms_error}")
        print("Falling back to email notification...")
        
        # Fallback to email
        email_success, email_error = send_email_notification(server_name, host, status, message)
        
        if email_success:
            print("✓ Email notification sent successfully!")
            last_notification_times[server_key] = datetime.now()
            return True
        else:
            print(f"✗ Email notification also failed: {email_error}")
            print("⚠ All notification methods failed!")
            return False

# --- Test Function ---

def test_notifications():
    """Test function to verify notification setup."""
    print("\n" + "="*60)
    print("Testing Notification System")
    print("="*60 + "\n")
    
    test_server_name = "Test Server"
    test_host = "192.168.1.100"
    test_status = "down"
    test_message = "1st check: 0/4 pings. Recheck: 0/4 pings."
    
    result = send_notification(test_server_name, test_host, test_status, test_message)
    
    if result:
        print("\n✓ Notification test completed successfully!")
    else:
        print("\n✗ Notification test failed. Please check your configuration.")
        print(f"Configuration file: {CONFIG_FILE}")

if __name__ == "__main__":
    # When run directly, perform a test notification
    print("Running notification system test...")
    test_notifications()