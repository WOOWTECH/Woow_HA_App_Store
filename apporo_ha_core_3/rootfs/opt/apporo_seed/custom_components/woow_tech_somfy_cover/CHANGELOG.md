# Changelog

All notable changes to the WoowTech Somfy Cover integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3] - 2025-11-22

### Added
- **Comprehensive Documentation Suite**: Complete technical and user documentation
  - `ARCHITECTURE.md`: System architecture and design patterns (~23,000 words)
  - `API_REFERENCE.md`: Complete API documentation with examples (~17,000 words)
  - `CONFIGURATION.md`: User configuration guide for both Config Flow and YAML (~14,000 words)
  - `TESTING.md`: Testing procedures and test script documentation (~12,000 words)
  - `DOCUMENTATION_INDEX.md`: Central documentation hub

### Changed
- **Documentation Updates**: All documentation now reflects actual v1.0.2 implementation
  - Updated CHANGELOG.md with proper Keep a Changelog format
  - Enhanced WAKEUP_IMPLEMENTATION.md with implementation details
  - Updated README.md to reference comprehensive documentation

### Removed
- **Cleanup**: Removed old planning and outdated files
  - Removed `IMPLEMENTATION_PLAN.md` (theoretical planning document)
  - Removed `IMPLEMENTATION_ANALYSIS.md` (testing journey document)
  - Removed old `custom_components/somfy_poe/` folder (renamed integration)

### Documentation Highlights
- **Architecture**: Complete layer-by-layer breakdown (Client → Protocol → Transport → Encryption)
- **API Reference**: All methods documented with parameters, returns, exceptions, and examples
- **Configuration**: Step-by-step guides for both UI and YAML setup methods
- **Testing**: Documentation for all 4 test scripts in working_tests/
- **Error Handling**: Complete error code reference (30+ codes)
- **Wake-up Mechanism**: Implementation details and performance characteristics
- **Security**: Encryption details (AES-128-CBC, zero-padding, IV handling)

### Technical Details
- All documentation validated against actual implementation code
- 66,000+ words of new technical documentation
- 50+ code examples from actual codebase
- 5 text-based architecture diagrams
- 100+ cross-references between documents

### Backward Compatibility
- Fully backward compatible with v1.0.2, v1.0.1, and v1.0.0
- No code changes - documentation only
- No breaking changes

## [1.0.2] - 2025-11-22

### Changed
- **YAML Parsing Improvement**: `target_id` and `key` now use `vol.Coerce(str)` for more flexible input validation
  - Allows unquoted hex values in YAML (e.g., `target_id: 160326` instead of requiring `target_id: "160326"`)
  - Backward compatible with quoted values
  - Simplifies YAML configuration while maintaining type safety

### Technical Details
- Modified `PLATFORM_SCHEMA` in `cover.py` to use `vol.Coerce(str)` for `target_id` and `key` fields
- No changes to Config Flow (UI) configuration
- No changes to core functionality or API layer

### Backward Compatibility
- Fully backward compatible with v1.0.1 and v1.0.0
- Existing YAML configurations with quoted values continue to work
- Existing Config Flow entries unaffected
- No breaking changes

### Documentation
- Updated README.md with examples of both quoted and unquoted YAML configurations
- Added clarification about v1.0.2 flexibility in CONFIGURATION.md

## [1.0.1] - 2025-11-22

### Added
- **YAML Configuration Support**: Full support for configuring motors via `configuration.yaml`
  - `async_setup()` function in `__init__.py` for YAML discovery
  - `async_setup_platform()` function in `cover.py` for YAML platform setup
  - `PLATFORM_SCHEMA` validation for YAML configuration
  - `SomfyYAMLCover` class for YAML-configured entities
  - Example YAML configuration file (`example_configuration.yaml`)
  - Comprehensive documentation for YAML configuration in README.md

### Changed
- Version bumped to 1.0.1 in `manifest.json`
- README.md updated with YAML configuration examples and instructions
- Version badge updated to 1.0.1

### Technical Details
- **Dual Configuration**: YAML and Config Flow configurations can coexist independently
- **Independent Coordinators**: Each YAML cover creates its own coordinator and client instance
- **Unique ID Formats**:
  - YAML covers: `yaml_<target_id>_<sanitized_name>`
  - Config Flow covers: `<entry_id>_cover`
- No conflicts between YAML and Config Flow entities

### Backward Compatibility
- Fully backward compatible with v1.0.0
- Existing Config Flow entries continue to work unchanged
- No breaking changes

## [1.0.0] - 2025-11-22

### Initial Release

#### Features
- **Config Flow UI Setup**: User-friendly integration setup via Settings → Integrations
  - Input validation for target_id (6 hex chars) and key (32 hex chars)
  - Connection testing before creating entry
  - Unique ID enforcement (one entry per motor)

- **Encrypted Communication**: Secure AES-128-CBC encryption
  - Zero-padding (100% success rate in testing)
  - Random IV per message
  - Port 55055 UDP binding with SO_REUSEADDR

- **Motor Control**: Full position and movement control
  - Open/Close/Stop commands
  - Set position (0-100 with 0.001% precision)
  - Position tracking with live updates
  - Position inversion (Somfy 0=open → HA 0=closed)

- **Automatic Motor Wake-up**: Transparent handling of sleeping motors
  - Sends harmless wake-up command before first request
  - ~1 second overhead only when needed
  - Self-healing after timeouts

- **Adaptive Polling**: Efficient state updates
  - Fast polling during movement (2 seconds)
  - Normal polling when stopped (30 seconds)
  - Automatic transition between modes

- **Error Handling**: Comprehensive error management
  - 30+ motor error codes mapped
  - Automatic retry on timeout
  - Graceful connection loss handling
  - Detailed logging for debugging

- **Platform Support**:
  - Docker/macOS compatibility
  - Home Assistant 2023.1+
  - Python 3.11+

#### Architecture
- **DataUpdateCoordinator Pattern**: Efficient state management
- **Layered Design**: Clear separation of concerns (Client → Protocol → Transport → Encryption)
- **Thread-safe**: asyncio.Lock for request serialization
- **Resource Efficient**: Sockets created/closed per request, minimal memory footprint

#### Device Integration
- Device registry integration with proper identifiers
- Firmware and hardware version reporting
- MAC address tracking
- Model and manufacturer information
