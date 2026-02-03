import sys
import os
import time
import re
import socket
import sqlite3
import shutil
import tempfile
import platform
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

# Try PyQt6 first, fallback to PyQt5 for compatibility
try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget,
        QVBoxLayout, QPushButton, QLabel, QMessageBox, QComboBox
    )
    from PyQt6.QtCore import QThread, pyqtSignal, QTimer
    PYQT_VERSION = 6
except ImportError:
    try:
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QWidget,
            QVBoxLayout, QPushButton, QLabel, QMessageBox, QComboBox
        )
        from PyQt5.QtCore import QThread, pyqtSignal, QTimer
        PYQT_VERSION = 5
    except ImportError:
        print("Error: Neither PyQt6 nor PyQt5 is installed.")
        print("Please install one of them: pip install PyQt6  OR  pip install PyQt5")
        sys.exit(1)

from pymobiledevice3.lockdown import create_using_usbmux, NoDeviceConnectedError
from pymobiledevice3.services.afc import AfcService
from pymobiledevice3.services.diagnostics import DiagnosticsService


SUPPORTED_DEVICES = {
    'iPhone4,1',
    'iPad2,1', 'iPad2,2', 'iPad2,3', 'iPad2,4',
    'iPad2,5', 'iPad2,6', 'iPad2,7',
    'iPad3,1', 'iPad3,2', 'iPad3,3',
    'iPod5,1'
}

SUPPORTED_VERSIONS = {'8.4.1', '9.3.5', '9.3.6'}

# pyinstaller resource path fix
def resource_path(name):
    base = getattr(sys, '_MEIPASS', os.path.abspath('.'))
    return os.path.join(base, name)


def get_local_server_url(port=8080):
    """
    Get the URL that an iOS device can use to reach this host's local server.
    Tries multiple methods for cross-platform compatibility.

    Returns:
        tuple: (url, method_used, warnings)
    """
    hostname = socket.gethostname()
    system = platform.system()
    warnings = []

    # Method 1: hostname.local (works on macOS, Windows with Bonjour, Linux with Avahi)
    url = f'http://{hostname}.local:{port}'
    method = f'{hostname}.local (mDNS/Bonjour)'

    # Platform-specific checks and warnings
    if system == 'Windows':
        # Check if Bonjour service might be available
        warnings.append(
            'Windows: Requires iTunes or Apple Devices app installed for Bonjour service.\n'
            'If activation fails, install iTunes from apple.com/itunes'
        )
    elif system == 'Linux':
        # Check if avahi-daemon might be available
        try:
            result = os.system('systemctl is-active --quiet avahi-daemon')
            if result != 0:
                warnings.append(
                    'Linux: Avahi daemon may not be running. Install with:\n'
                    'sudo apt install avahi-daemon  OR  sudo yum install avahi'
                )
        except Exception:
            warnings.append(
                'Linux: Install avahi-daemon for mDNS support:\n'
                'sudo apt install avahi-daemon  OR  sudo yum install avahi'
            )

    # Method 2: Try to find USB network interface IP (fallback)
    try:
        # Get all network interfaces
        import netifaces

        for interface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(interface)
            if netifaces.AF_INET in addrs:
                for addr_info in addrs[netifaces.AF_INET]:
                    ip = addr_info.get('addr', '')
                    # Check for USB tethering subnet (172.20.10.x)
                    if ip.startswith('172.20.10.'):
                        fallback_url = f'http://{ip}:{port}'
                        warnings.append(
                            f'Alternative: If .local fails, the device may be able to reach:\n'
                            f'{fallback_url}'
                        )
                        break
    except ImportError:
        # netifaces not available, that's okay
        pass
    except Exception:
        # Any error in network interface detection, ignore
        pass

    return url, method, warnings


def patch_payload_for_local_server(original_payload_path, local_url):
    """
    Creates a patched copy of the payload database with local server URL.
    Returns the path to the patched payload.
    """
    # Create a temporary file for the patched payload
    temp_fd, temp_path = tempfile.mkstemp(suffix='.sqlitedb')
    os.close(temp_fd)

    # Copy original payload to temp location
    shutil.copy2(original_payload_path, temp_path)

    try:
        # Open the database and patch the URL
        conn = sqlite3.connect(temp_path)
        cursor = conn.cursor()

        # Find tables that might contain URLs
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()

        # Try to find and replace URLs in the database
        for (table_name,) in tables:
            try:
                # Get table info
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()

                # Look for columns that might contain URLs
                for col in columns:
                    col_name = col[1]
                    col_type = col[2]

                    if 'TEXT' in col_type or 'VARCHAR' in col_type or 'BLOB' in col_type:
                        # Try to find and replace URLs
                        cursor.execute(f"SELECT rowid, {col_name} FROM {table_name}")
                        rows = cursor.fetchall()

                        for row in rows:
                            rowid, value = row
                            if value and isinstance(value, (str, bytes)):
                                if isinstance(value, bytes):
                                    value_str = value.decode('utf-8', errors='ignore')
                                else:
                                    value_str = value

                                # Check if this looks like a URL
                                if 'http://' in value_str or 'https://' in value_str:
                                    # Replace with local URL
                                    new_value = re.sub(
                                        r'https?://[^/\s]+',
                                        local_url,
                                        value_str
                                    )

                                    if isinstance(value, bytes):
                                        new_value = new_value.encode('utf-8')

                                    cursor.execute(
                                        f"UPDATE {table_name} SET {col_name} = ? WHERE rowid = ?",
                                        (new_value, rowid)
                                    )
            except Exception:
                # Skip tables that cause errors
                continue

        conn.commit()
        conn.close()

        return temp_path

    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise e


class PlistRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for serving device-specific plist files"""

    def log_message(self, format, *args):
        # Suppress default logging
        pass

    def do_GET(self):
        user_agent = self.headers.get('User-Agent', '')

        # Parse model and build from User-Agent
        # Format: model/iPad2,1 build/13G36
        model_match = re.search(r'model/([a-zA-Z0-9,]+)', user_agent)
        build_match = re.search(r'build/([a-zA-Z0-9]+)', user_agent)

        if not model_match or not build_match:
            self.send_error(403, 'Forbidden')
            return

        model = model_match.group(1)
        build = build_match.group(1)

        # Path traversal protection
        if '..' in model or '..' in build:
            self.send_error(403, 'Forbidden')
            return

        # Construct file path
        base_dir = resource_path('backend/plists')
        file_path = os.path.join(base_dir, model, build, 'patched.plist')

        if not os.path.exists(file_path):
            self.send_error(404, 'Not Found')
            return

        # Serve the file
        try:
            with open(file_path, 'rb') as f:
                content = f.read()

            self.send_response(200)
            self.send_header('Content-Type', 'application/xml')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Content-Disposition', 'attachment; filename="patched.plist"')
            self.send_header('Cache-Control', 'must-revalidate')
            self.send_header('Pragma', 'public')
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f'Internal Server Error: {str(e)}')


class LocalBackendServer:
    """Local HTTP server for serving activation plists over USB network"""

    def __init__(self, port=8080):
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        if self.server is not None:
            return

        # Bind to all interfaces so device can reach us via USB network
        self.server = HTTPServer(('0.0.0.0', self.port), PlistRequestHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.server = None
            self.thread = None

    def is_running(self):
        return self.server is not None


class ActivationThread(QThread):
    status = pyqtSignal(str)
    success = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, use_local_server=False):
        super().__init__()
        self.use_local_server = use_local_server
        self.server = None
        self.patched_payload = None

    def wait_for_device(self, timeout=120):
        start = time.monotonic()

        while time.monotonic() - start < timeout:
            try:
                lockdown = create_using_usbmux()
                DiagnosticsService(lockdown=lockdown).mobilegestalt(
                    keys=['ProductType']
                )
                return lockdown
            except Exception:
                time.sleep(2)

        raise TimeoutError()


    def push_payload(self, lockdown, payload):
        with AfcService(lockdown=lockdown) as afc, open(payload, 'rb') as f:
            afc.set_file_contents(
                'Downloads/downloads.28.sqlitedb',
                f.read()
            )

        DiagnosticsService(lockdown=lockdown).restart()
        time.sleep(10)
        return self.wait_for_device()

    def should_hactivate(self, lockdown):
        diag = DiagnosticsService(lockdown=lockdown)
        return diag.mobilegestalt(
            keys=['ShouldHactivate']
        ).get('ShouldHactivate')

    def run(self):
        try:
            # Start local server if using local backend
            if self.use_local_server:
                self.server = LocalBackendServer(port=8080)
                self.server.start()

                # Get platform-appropriate server URL
                local_url, method, warnings = get_local_server_url(port=8080)
                self.status.emit(f'Started local server\n{method}')

                # Show platform-specific warnings if any
                if warnings:
                    warning_msg = '\n\n'.join(warnings)
                    self.status.emit(f'Platform note:\n{warnings[0][:100]}...')

                time.sleep(1)

                # Patch payload to use local server
                original_payload = resource_path('payload')
                self.status.emit('Patching payload for local server...')
                self.patched_payload = patch_payload_for_local_server(original_payload, local_url)
                payload = self.patched_payload
            else:
                payload = resource_path('payload')

            lockdown = create_using_usbmux()

            if lockdown.get_value(key='ActivationState') == 'Activated':
                self.success.emit('Device is already activated')
                return

            if self.use_local_server:
                self.status.emit('Activating device with local server...')
            else:
                self.status.emit('Activating device...')

            for attempt in range(5):
                lockdown = self.push_payload(lockdown, payload)

                if self.should_hactivate(lockdown) is not False:
                    DiagnosticsService(lockdown=lockdown).restart()
                    self.success.emit('Done!')
                    return

                self.status.emit(f'Retrying activation\nAttempt {attempt + 1}/5')
                time.sleep(5)

            error_msg = 'Activation failed after multiple attempts.'
            if not self.use_local_server:
                error_msg += ' Make sure the device is connected to the Wi-Fi.'
            else:
                error_msg += ' Make sure the device can reach the local server via USB network.'
            self.error.emit(error_msg)

        except TimeoutError:
            self.error.emit(
                'Device did not reconnect in time. Please ensure it is connected and try again.'
            )
        except Exception as e:
            self.error.emit(str(e))
        finally:
            # Stop local server if it was started
            if self.server is not None:
                self.server.stop()
                self.server = None

            # Clean up patched payload
            if self.patched_payload and os.path.exists(self.patched_payload):
                try:
                    os.remove(self.patched_payload)
                except Exception:
                    pass
                self.patched_payload = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # Include PyQt version in title for debugging
        title = f'A5 Bypass OSS v1.0.3 (Qt{PYQT_VERSION})'
        self.setWindowTitle(title)
        self.setFixedSize(300, 250)

        self.warning_shown = False

        self.status = QLabel('No device connected')

        # Backend selection dropdown
        self.backend_label = QLabel('Backend Mode:')
        self.backend_selector = QComboBox()
        self.backend_selector.addItem('Remote (Wi-Fi Required)')
        self.backend_selector.addItem('Local (USB Network)')
        self.backend_selector.setCurrentIndex(1)  # Default to local

        self.activate = QPushButton('Activate Device')
        self.activate.setEnabled(False)

        layout = QVBoxLayout()
        layout.addWidget(self.status)
        layout.addWidget(self.backend_label)
        layout.addWidget(self.backend_selector)
        layout.addWidget(self.activate)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.activate.clicked.connect(self.start_activation)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_device)
        self.timer.start(1000)

    def poll_device(self):
        try:
            lockdown = create_using_usbmux()
            info = lockdown.get_value()

            product = info.get('ProductType')
            version = info.get('ProductVersion')

            if product not in SUPPORTED_DEVICES:
                self._set_state(f'Unsupported Device: {product}', False)
                return

            if version not in SUPPORTED_VERSIONS:
                self._set_state(f'Unsupported iOS: {version}', False)
                return

            # https://github.com/overcast302/A5_Bypass_OSS/issues/7
            if (
                version == '8.4.1'
                and info.get('TelephonyCapability')
                and not self.warning_shown
            ):
                QMessageBox.information(
                    self,
                    'Warning',
                    'Cellular iOS 8.4.1 devices activation is partially broken. Proceed with caution.'
                )
                self.warning_shown = True

            self._set_state(f'Connected: {product} ({version})', True)

        except NoDeviceConnectedError:
            self.warning_shown = False
            self._set_state('No device connected', False)

    def _set_state(self, text, enabled):
        self.status.setText(text)
        self.activate.setEnabled(enabled)

    def start_activation(self):
        use_local = self.backend_selector.currentIndex() == 1

        if use_local:
            info_text = 'Your device will now be activated using the local server over USB network.'

            # Add platform-specific requirements
            system = platform.system()
            if system == 'Windows':
                info_text += '\n\nWindows: iTunes or Apple Devices app must be installed.'
            elif system == 'Linux':
                info_text += '\n\nLinux: Ensure avahi-daemon is running for mDNS support.'
        else:
            info_text = 'Your device will now be activated. Please ensure it is connected to Wi-Fi.'

        QMessageBox.information(self, 'Info', info_text)

        self.timer.stop()
        self.activate.setEnabled(False)
        self.backend_selector.setEnabled(False)

        self.worker = ActivationThread(use_local_server=use_local)
        self.worker.status.connect(self.status.setText)
        self.worker.success.connect(self.on_success)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_success(self, msg):
        self.status.setText(msg)
        QMessageBox.information(self, 'Success', msg)
        self.activate.setEnabled(True)
        self.backend_selector.setEnabled(True)
        self.timer.start(1000)

    def on_error(self, msg):
        QMessageBox.critical(self, 'Error', msg)
        self.status.setText('Error occurred')
        self.activate.setEnabled(True)
        self.backend_selector.setEnabled(True)
        self.timer.start(1000)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())