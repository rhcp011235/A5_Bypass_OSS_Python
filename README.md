# A5_Bypass_OSS

A5_Bypass_OSS is an open-source research project focused on analyzing and experimenting with legacy iOS devices based on the Apple A5 SoC.

## Disclaimer

This project is intended strictly for research and educational purposes.  
It is not designed for, and must not be used in, production environments or for unlawful activities.  
The authors and contributors take no responsibility for misuse or for any damage caused to devices, data, or systems.

## System Requirements

### All Platforms
- Python 3.6.1 or later
- PyQt6 **OR** PyQt5 (automatic fallback support)
- pymobiledevice3

### Platform-Specific Requirements

**macOS:**
- macOS 12.0 (Monterey) or later
- No additional software required

**Windows:**
- Windows 10 or later
- **iTunes or Apple Devices app** (required for Local Mode)
  - Download: https://www.apple.com/itunes/download/
  - Includes Bonjour service for mDNS

**Linux:**
- Required packages: `usbmuxd`, `libimobiledevice-tools`, `avahi-daemon`
- Install on Debian/Ubuntu: `sudo apt install usbmuxd libimobiledevice-tools avahi-daemon`
- Install on Fedora/RHEL: `sudo yum install usbmuxd libimobiledevice avahi`

**📖 See [CROSS_PLATFORM_COMPATIBILITY.md](CROSS_PLATFORM_COMPATIBILITY.md) for detailed platform-specific instructions.**

## Activation Requirements

### Remote Mode (Wi-Fi Required)
- The target device must be connected to Wi-Fi at all times during operation.
- Network connectivity is mandatory for the remote backend server to function correctly.
- Works on all platforms without additional software (except Python dependencies).

### Local Mode (USB Network)
- No Wi-Fi connection required.
- Device communicates with your computer via USB network interface.
- Uses mDNS/Bonjour (hostname.local) for device-to-computer communication.
- Completely offline activation over USB.
- **Platform requirements:**
  - macOS: Works out of the box
  - Windows: Requires iTunes/Apple Devices app
  - Linux: Requires avahi-daemon and usbmuxd

## Compatibility

The tool is compatible with all A5 devices running **iOS 9.3.6** and **iOS 9.3.5**

Support for **iOS 8.4.1** was introduced in [v1.0.1](https://github.com/overcast302/A5_Bypass_OSS/releases/tag/v1.0.1). However, it is currently broken on cellular devices (see [#7](https://github.com/overcast302/A5_Bypass_OSS/issues/7)). Wi-Fi models are fully supported.

No support for other iOS versions is planned yet.

## Backend Modes

The application supports two backend modes for device activation:

### 1. Remote Mode (Wi-Fi Required)
- Uses a remote backend server to serve device-specific configuration files.
- Requires the device to be connected to Wi-Fi.
- The backend URL is stored inside the payload SQLite database.

### 2. Local Mode (USB Network) - NEW in v1.0.3
- Runs a local HTTP server on your Mac (port 8080).
- Serves device-specific plist files directly over USB network interface.
- No Wi-Fi connection required - completely offline activation.
- Automatically patches the payload database to point to your Mac's local server.
- Uses mDNS/Bonjour (hostname.local:8080) for device communication.
- Server automatically starts before activation and stops after completion.

**To switch modes:**
- Use the "Backend Mode" dropdown in the application interface.
- Select "Remote (Wi-Fi Required)" for internet-based activation.
- Select "Local (USB Network)" for offline USB-based activation (recommended).

## Backend Configuration (Advanced)

For manual backend URL modification in Remote Mode:
- Open the payload SQLite database.
- Locate the table named `asset`.
- Edit the `url` field containing the backend URL.
- Write database changes before running the application.

Note: Local Mode automatically handles this configuration.

## Credits
- [pkkf5673](https://github.com/bablaerrr)
- [bl_sbx](https://github.com/hanakim3945/bl_sbx)
- [pymobiledevice3](https://github.com/doronz88/pymobiledevice3)

## License

Refer to the repository license file for licensing details.
