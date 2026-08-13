# WoowTech Somfy Cover Integration

[![version](https://img.shields.io/badge/version-1.0.3-blue.svg)](https://github.com/woowtech/somfy-cover)
[![hacs](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Home Assistant custom integration for Somfy PoE motors with encrypted UDP communication.

## Features

- **Encrypted Communication**: AES-128-CBC encryption with zero-padding
- **Local Control**: Direct UDP communication (no cloud dependency)
- **Full Position Control**: Open, close, stop, and set to any position
- **Automatic Wake-up**: Handles motor hibernation automatically
- **Real-time Updates**: Position polling with configurable intervals
- **Config Flow**: Easy setup through the Home Assistant UI

## Supported Devices

- Somfy Sonesse 30 PoE motors
- Somfy PoE motors with JSON-RPC API support

## Installation

### HACS (Recommended)

1. Add this repository to HACS as a custom repository
2. Search for "WoowTech Somfy Cover" in HACS
3. Click "Install"
4. Restart Home Assistant

### Manual Installation

1. Copy the `woow_tech_somfy_cover` folder to your `custom_components` directory
2. Restart Home Assistant

## Configuration

This integration supports two configuration methods that can coexist:

### Method 1: Via UI (Config Flow)

1. Go to **Settings** → **Devices & Services**
2. Click **+ ADD INTEGRATION**
3. Search for "WoowTech Somfy Cover"
4. Enter your motor details:
   - **Name**: Friendly name for the cover
   - **IP Address**: Motor's IP address on your network
   - **Target ID**: 6-digit hexadecimal ID (found on motor label)
   - **Encryption Key**: 32-digit hexadecimal key (found on motor label)

### Method 2: Via YAML (configuration.yaml)

Add the following to your `configuration.yaml`:

```yaml
cover:
  - platform: woow_tech_somfy_cover
    name: Living Room Shade
    host: 192.168.1.77
    target_id: 160326
    key: FBE90399BA25B4B67DC1B23BE0D9C084
```

**Note**: Since v1.0.2, you can use values with or without quotes:
- `target_id: 160326` or `target_id: "160326"` (both work)
- `key: FBE90399BA25B4B67DC1B23BE0D9C084` or `key: "FBE90399BA25B4B67DC1B23BE0D9C084"` (both work)

**Multiple covers:**

```yaml
cover:
  - platform: woow_tech_somfy_cover
    name: Living Room Shade
    host: 192.168.1.77
    target_id: 160326
    key: FBE90399BA25B4B67DC1B23BE0D9C084

  - platform: woow_tech_somfy_cover
    name: Bedroom Shade
    host: 192.168.1.78
    target_id: 160327
    key: ABC90399BA25B4B67DC1B23BE0D9C085
```

**Configuration Variables:**

- `platform` (Required): Must be `woow_tech_somfy_cover`
- `name` (Optional): Friendly name for the cover. Default: `Somfy Cover`
- `host` (Required): IP address of the Somfy motor
- `target_id` (Required): 6-digit hexadecimal target ID (quotes optional since v1.0.2)
- `key` (Required): 32-digit hexadecimal encryption key (quotes optional since v1.0.2)

After adding YAML configuration, restart Home Assistant to apply changes.

### Coexistence

You can use both configuration methods simultaneously:
- Some covers configured via UI (Config Flow)
- Other covers configured via YAML
- No conflicts between the two methods
- Each cover operates independently with its own coordinator

## Finding Your Motor Credentials

The Target ID and Encryption Key can be found:
- On the motor's label (QR code sticker)
- In the Somfy mobile app
- In the motor's web interface (if available)

**Example values**:
- Target ID: `160326`
- Encryption Key: `FBE90399BA25B4B67DC1B23BE0D9C084`

## Usage

Once configured, the motor will appear as a cover entity in Home Assistant:

### Services

The cover entity supports all standard Home Assistant cover services:

- `cover.open_cover` - Fully open the cover
- `cover.close_cover` - Fully close the cover
- `cover.stop_cover` - Stop movement
- `cover.set_cover_position` - Set to specific position (0-100%)

### Position

- **0%** = Fully closed (down)
- **100%** = Fully open (up)

## Architecture

The integration uses a layered architecture:

```
┌─────────────────────┐
│   Cover Platform    │  Home Assistant Cover Entity
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│   Coordinator       │  DataUpdateCoordinator (polling)
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│   Somfy Client      │  High-level API client
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│   Protocol Layer    │  JSON-RPC message building
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│   Transport Layer   │  UDP communication + wake-up
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│ Encryption Layer    │  AES-128-CBC (zero-padding)
└─────────────────────┘
```

### Key Components

- **Client** (`api/client.py`): High-level interface for motor control
- **Protocol** (`api/protocol.py`): JSON-RPC message construction and parsing
- **Transport** (`api/transport.py`): UDP socket management with wake-up mechanism
- **Encryption** (`api/encryption.py`): AES-128-CBC encryption/decryption
- **Coordinator** (`coordinator.py`): Position polling and state management
- **Cover** (`cover.py`): Home Assistant cover entity implementation

## Wake-up Mechanism

Somfy PoE motors enter hibernation mode after periods of inactivity. This integration implements an automatic wake-up mechanism:

1. **Detection**: Tracks when motor might be sleeping (first command after connection or after timeout)
2. **Wake-up**: Sends harmless `move.stop` command with short timeout
3. **Execution**: Proceeds with actual command after motor is awake
4. **Efficiency**: Only adds ~1s overhead when needed, zero overhead for subsequent commands

## Troubleshooting

### Motor Not Responding

1. **Check Network**: Ensure motor is on the same network as Home Assistant
2. **Check IP**: Verify the IP address is correct and motor is reachable (`ping <ip>`)
3. **Check Credentials**: Verify Target ID and Encryption Key are correct
4. **Check Port**: Ensure UDP port 55055 is not blocked by firewall

### Timeout Errors

The integration handles timeouts automatically with:
- Automatic retries (up to 2 attempts)
- Wake-up mechanism for sleeping motors
- Detailed logging for troubleshooting

Enable debug logging in `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.woow_tech_somfy_cover: debug
```

### Docker/Container Deployments

For Docker Desktop on macOS, ensure UDP port mapping in your container configuration:
```json
"appPort": ["8123:8123", "55055:55055/udp"]
```

## Technical Details

### Encryption

- **Algorithm**: AES-128-CBC
- **Padding**: Zero-padding (not PKCS7)
- **IV**: 16 random bytes prepended to each message
- **Key**: 128-bit (32 hex characters)

### Communication Protocol

- **Transport**: UDP on port 55055
- **Protocol**: JSON-RPC 2.0
- **Message Format**: IV (16 bytes) + Encrypted JSON payload

### Performance

- **First command**: ~250ms (includes wake-up)
- **Subsequent commands**: ~10-50ms
- **Position polling**: Every 30 seconds (configurable)
- **Fast polling**: Every 2 seconds during movement

## Error Codes

The integration handles all Somfy API error codes:

- `1` - Data out of range
- `16` - Unknown method
- `32` - Device locked
- `34` - End limits not set
- `36` - Target out of range
- `38` - Motor in motion
- `48` - Thermal protection
- `49` - Obstacle detected
- `255` - Motor busy

See `const.py` for complete error code list.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This integration is provided as-is under the MIT License.

## Credits

- Developed by WoowTech
- Tested with Somfy Sonesse 30 PoE motors
- Based on Somfy PoE Motor API documentation

## Support

For issues and feature requests, please use the [GitHub issue tracker](https://github.com/woowtech/somfy-cover/issues).

## Version History

### 1.0.3 (2025-11-22)
- Comprehensive documentation suite added (66,000+ words)
- Architecture, API reference, configuration, and testing guides
- Removed old planning documents and renamed integration folder
- Documentation only - no code changes
- Backward compatible with all previous versions

### 1.0.2 (2025-11-22)
- Improved YAML configuration UX
- `target_id` and `key` values can now be specified with or without quotes
- Automatic type coercion for better user experience
- Backward compatible with v1.0.0 and v1.0.1

### 1.0.1 (2025-11-22)
- Added YAML configuration support
- YAML and Config Flow can coexist
- Each YAML cover gets its own coordinator
- Backward compatible with v1.0.0

### 1.0.0 (2025-11-22)
- Initial release
- Config Flow support
- Automatic wake-up mechanism
- Full position control
- Comprehensive error handling
- Docker/macOS support
