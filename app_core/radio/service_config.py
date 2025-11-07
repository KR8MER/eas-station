"""
Simplified SDR configuration presets and validation.

Service-based configuration that automatically sets all parameters
based on the service type (AM/FM/NOAA Weather Radio).
"""

from typing import Dict, List, Optional, Tuple
import re


# NOAA Weather Radio frequencies (MHz)
NOAA_FREQUENCIES = [
    162.400, 162.425, 162.450, 162.475, 162.500, 162.525, 162.550
]

# AM broadcast band (kHz)
AM_BAND_MIN = 530
AM_BAND_MAX = 1700
AM_BAND_STEP = 10  # 10 kHz channel spacing

# FM broadcast band (MHz)
FM_BAND_MIN = 88.1
FM_BAND_MAX = 108.0
FM_BAND_STEP = 0.2  # 200 kHz channel spacing (in US, 0.1 MHz odd increments)


def get_service_config(service_type: str, frequency_mhz: float) -> Dict:
    """
    Get complete SDR configuration based on service type and frequency.

    Args:
        service_type: 'AM', 'FM', or 'NOAA'
        frequency_mhz: Frequency in MHz

    Returns:
        Dictionary with all SDR parameters configured
    """
    if service_type == 'NOAA':
        return {
            'modulation_type': 'NFM',  # Narrowband FM
            'sample_rate': 250000,  # 250 kHz
            'audio_output': True,
            'stereo_enabled': False,  # NOAA is mono
            'deemphasis_us': 75.0,  # North America standard
            'enable_rbds': False,  # NOAA doesn't use RBDS
            'bandwidth': 25000,  # 25 kHz bandwidth
        }

    elif service_type == 'FM':
        return {
            'modulation_type': 'WFM',  # Wideband FM
            'sample_rate': 2400000,  # 2.4 MHz (for full FM multiplex)
            'audio_output': True,
            'stereo_enabled': True,  # FM broadcast is stereo
            'deemphasis_us': 75.0,  # North America (50 for Europe/Asia)
            'enable_rbds': True,  # Enable RBDS decoding
            'bandwidth': 200000,  # 200 kHz bandwidth
        }

    elif service_type == 'AM':
        return {
            'modulation_type': 'AM',
            'sample_rate': 1000000,  # 1 MHz
            'audio_output': True,
            'stereo_enabled': False,  # AM is mono
            'deemphasis_us': 0.0,  # AM doesn't use de-emphasis
            'enable_rbds': False,
            'bandwidth': 10000,  # 10 kHz bandwidth
        }

    else:
        raise ValueError(f"Unknown service type: {service_type}")


def validate_frequency(service_type: str, frequency_input: str) -> Tuple[bool, Optional[float], Optional[str]]:
    """
    Validate and convert frequency input based on service type.

    Args:
        service_type: 'AM', 'FM', or 'NOAA'
        frequency_input: User input string (e.g., "97.9", "800", "162.4")

    Returns:
        Tuple of (valid, frequency_hz, error_message)
    """
    try:
        freq_value = float(frequency_input.strip())
    except ValueError:
        return False, None, "Invalid number format"

    if service_type == 'NOAA':
        # Check if it's a valid NOAA frequency
        if freq_value not in NOAA_FREQUENCIES:
            valid_freqs = ', '.join(f"{f:.3f}" for f in NOAA_FREQUENCIES)
            return False, None, f"Invalid NOAA frequency. Valid frequencies: {valid_freqs} MHz"

        frequency_hz = freq_value * 1_000_000
        return True, frequency_hz, None

    elif service_type == 'FM':
        # FM broadcast band: 88.1 - 108.0 MHz
        if freq_value < FM_BAND_MIN or freq_value > FM_BAND_MAX:
            return False, None, f"FM frequency must be between {FM_BAND_MIN} and {FM_BAND_MAX} MHz"

        # Check odd increments (88.1, 88.3, 88.5, ..., 107.9)
        # FM stations are spaced 200 kHz apart with odd tenths
        decimal_part = round((freq_value - int(freq_value)) * 10, 1)
        if decimal_part not in [1, 3, 5, 7, 9]:
            return False, None, "FM frequencies must end in .1, .3, .5, .7, or .9 (e.g., 97.9)"

        frequency_hz = freq_value * 1_000_000
        return True, frequency_hz, None

    elif service_type == 'AM':
        # AM broadcast band: 530 - 1700 kHz
        # Input can be in kHz (530-1700) or MHz (0.53-1.7)
        if freq_value < 10:
            # Assume MHz input, convert to kHz
            freq_khz = freq_value * 1000
        else:
            # Already in kHz
            freq_khz = freq_value

        if freq_khz < AM_BAND_MIN or freq_khz > AM_BAND_MAX:
            return False, None, f"AM frequency must be between {AM_BAND_MIN} and {AM_BAND_MAX} kHz (or {AM_BAND_MIN/1000:.2f}-{AM_BAND_MAX/1000:.2f} MHz)"

        # Check 10 kHz spacing
        if freq_khz % AM_BAND_STEP != 0:
            return False, None, f"AM frequencies must be multiples of {AM_BAND_STEP} kHz (e.g., 800, 1010, 1540)"

        frequency_hz = freq_khz * 1000
        return True, frequency_hz, None

    else:
        return False, None, f"Unknown service type: {service_type}"


def format_frequency_display(service_type: str, frequency_hz: float) -> str:
    """
    Format frequency for display based on service type.

    Args:
        service_type: 'AM', 'FM', or 'NOAA'
        frequency_hz: Frequency in Hz

    Returns:
        Formatted string (e.g., "97.9 MHz", "800 kHz", "162.400 MHz")
    """
    if service_type == 'NOAA' or service_type == 'FM':
        freq_mhz = frequency_hz / 1_000_000
        return f"{freq_mhz:.3f} MHz" if service_type == 'NOAA' else f"{freq_mhz:.1f} MHz"

    elif service_type == 'AM':
        freq_khz = frequency_hz / 1000
        return f"{int(freq_khz)} kHz"

    return f"{frequency_hz / 1_000_000:.3f} MHz"


def get_frequency_placeholder(service_type: str) -> str:
    """Get placeholder text for frequency input based on service type."""
    if service_type == 'NOAA':
        return "e.g., 162.4"
    elif service_type == 'FM':
        return "e.g., 97.9"
    elif service_type == 'AM':
        return "e.g., 800"
    return "Frequency"


def get_frequency_help_text(service_type: str) -> str:
    """Get help text for frequency input based on service type."""
    if service_type == 'NOAA':
        freqs = ', '.join(f"{f:.1f}" for f in NOAA_FREQUENCIES)
        return f"Valid NOAA frequencies: {freqs}"
    elif service_type == 'FM':
        return f"FM broadcast: {FM_BAND_MIN}-{FM_BAND_MAX} MHz (odd tenths: .1, .3, .5, .7, .9)"
    elif service_type == 'AM':
        return f"AM broadcast: {AM_BAND_MIN}-{AM_BAND_MAX} kHz (10 kHz spacing)"
    return ""
