"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""
Optimized parsing utilities with fallback to standard libraries.

This module provides high-performance parsing functions for JSON, XML, and datetime
operations with graceful fallback to standard library implementations.

Performance improvements:
- JSON: 2-3x faster with orjson vs. standard json module
- XML: 5-10x faster with lxml vs. xml.etree.ElementTree
- Datetime: More robust parsing with python-dateutil
"""

from typing import Any, Dict, Optional, Union
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# JSON Parsing - Fast JSON with fallback
# =============================================================================

try:
    import orjson
    _HAS_ORJSON = True
    logger.debug("Using orjson for optimized JSON parsing")
except ImportError:
    _HAS_ORJSON = False
    try:
        import ujson
        _HAS_UJSON = True
        logger.debug("Using ujson for optimized JSON parsing")
    except ImportError:
        _HAS_UJSON = False
        logger.debug("Using standard json library (consider installing orjson for better performance)")

import json as _stdlib_json

# Export JSONDecodeError from stdlib for compatibility
JSONDecodeError = _stdlib_json.JSONDecodeError


def json_loads(data: Union[str, bytes]) -> Any:
    """
    Parse JSON data using the fastest available library.
    
    Performance hierarchy:
    1. orjson (fastest, 2-3x faster than stdlib)
    2. ujson (fast, 1.5-2x faster than stdlib)
    3. standard json library (fallback)
    
    Args:
        data: JSON string or bytes to parse
        
    Returns:
        Parsed JSON data
        
    Raises:
        JSONDecodeError: If the data is not valid JSON
    """
    try:
        if _HAS_ORJSON:
            if isinstance(data, str):
                data = data.encode('utf-8')
            return orjson.loads(data)
        elif _HAS_UJSON:
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            return ujson.loads(data)
        else:
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            return _stdlib_json.loads(data)
    except (ValueError, TypeError) as e:
        # Convert any JSON parsing error to JSONDecodeError for consistency
        raise JSONDecodeError(str(e), str(data)[:100], 0) from e


def json_dumps(obj: Any, indent: Optional[int] = None, ensure_ascii: bool = True, 
               sort_keys: bool = False, default=None) -> str:
    """
    Serialize object to JSON string using the fastest available library.
    
    Performance hierarchy:
    1. orjson (fastest, 2-3x faster than stdlib)
    2. ujson (fast, 1.5-2x faster than stdlib)
    3. standard json library (fallback)
    
    Args:
        obj: Object to serialize
        indent: Optional indentation level for pretty-printing
        ensure_ascii: If False, allow non-ASCII characters (orjson always False)
        sort_keys: If True, sort dictionary keys
        default: Function to serialize objects not supported by default
        
    Returns:
        JSON string
        
    Raises:
        TypeError: If the object is not JSON serializable
    """
    if _HAS_ORJSON:
        # orjson returns bytes, we need to decode to str
        # Build options based on parameters
        option = 0
        if indent:
            option |= orjson.OPT_INDENT_2
        if sort_keys:
            option |= orjson.OPT_SORT_KEYS
        # orjson doesn't support ensure_ascii=True (always outputs UTF-8)
        # and doesn't support default parameter, so fallback for those cases
        if ensure_ascii and not all(ord(c) < 128 for c in str(obj)):
            # Fallback to stdlib for ASCII-only requirement
            return _stdlib_json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii, 
                                    sort_keys=sort_keys, default=default)
        try:
            return orjson.dumps(obj, option=option, default=default).decode('utf-8')
        except TypeError:
            # orjson failed, try stdlib
            return _stdlib_json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii,
                                    sort_keys=sort_keys, default=default)
    elif _HAS_UJSON:
        return ujson.dumps(obj, indent=indent or 0, ensure_ascii=ensure_ascii, 
                          sort_keys=sort_keys)
    else:
        return _stdlib_json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii,
                                sort_keys=sort_keys, default=default)


def json_dump(obj: Any, fp, indent: Optional[int] = None, ensure_ascii: bool = True,
              sort_keys: bool = False, default=None) -> None:
    """
    Serialize object to JSON and write to file.
    
    Args:
        obj: Object to serialize
        fp: File-like object to write to
        indent: Optional indentation level for pretty-printing
        ensure_ascii: If False, allow non-ASCII characters
        sort_keys: If True, sort dictionary keys
        default: Function to serialize objects not supported by default
    """
    json_str = json_dumps(obj, indent=indent, ensure_ascii=ensure_ascii,
                         sort_keys=sort_keys, default=default)
    fp.write(json_str)


# =============================================================================
# XML Parsing - Fast XML with fallback
# =============================================================================

try:
    from lxml import etree as _lxml_etree
    _HAS_LXML = True
    logger.debug("Using lxml for optimized XML parsing")
except ImportError:
    _HAS_LXML = False
    logger.debug("Using xml.etree.ElementTree (consider installing lxml for better performance)")

import xml.etree.ElementTree as _stdlib_ET


def parse_xml_string(xml_string: Union[str, bytes]):
    """
    Parse XML from string using the fastest available library.
    
    Performance hierarchy:
    1. lxml (5-10x faster than ElementTree, better memory efficiency)
    2. xml.etree.ElementTree (fallback)
    
    Args:
        xml_string: XML string or bytes to parse
        
    Returns:
        Element tree root element
        
    Raises:
        ParseError: If the XML is malformed
    """
    if _HAS_LXML:
        if isinstance(xml_string, str):
            xml_string = xml_string.encode('utf-8')
        return _lxml_etree.fromstring(xml_string)
    else:
        if isinstance(xml_string, bytes):
            xml_string = xml_string.decode('utf-8')
        return _stdlib_ET.fromstring(xml_string)


def parse_xml_file(filename: str):
    """
    Parse XML from file using the fastest available library.
    
    Args:
        filename: Path to XML file
        
    Returns:
        Element tree root element
        
    Raises:
        ParseError: If the XML is malformed
        IOError: If the file cannot be read
    """
    if _HAS_LXML:
        tree = _lxml_etree.parse(filename)
        return tree.getroot()
    else:
        tree = _stdlib_ET.parse(filename)
        return tree.getroot()


def get_element_tree_module():
    """
    Get the ElementTree module being used (for compatibility).
    
    Returns:
        Either lxml.etree or xml.etree.ElementTree
    """
    if _HAS_LXML:
        return _lxml_etree
    else:
        return _stdlib_ET


# =============================================================================
# Datetime Parsing - Robust datetime handling
# =============================================================================

try:
    from dateutil import parser as _dateutil_parser
    _HAS_DATEUTIL = True
    logger.debug("Using python-dateutil for robust datetime parsing")
except ImportError:
    _HAS_DATEUTIL = False
    logger.debug("Using standard datetime parsing (consider installing python-dateutil for better robustness)")

from datetime import datetime as _datetime


def parse_datetime(date_string: str, default: Optional[_datetime] = None) -> Optional[_datetime]:
    """
    Parse datetime string using python-dateutil if available.
    
    This provides more robust parsing than strptime, handling various formats
    automatically including ISO 8601, RFC 3339, and many common formats.
    
    Args:
        date_string: Date/time string to parse
        default: Default datetime to use for missing components
        
    Returns:
        Parsed datetime object or None if parsing fails
    """
    if not date_string:
        return None
        
    try:
        if _HAS_DATEUTIL:
            return _dateutil_parser.parse(date_string, default=default)
        else:
            # Fallback to basic ISO format parsing
            # Try common formats
            for fmt in [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ]:
                try:
                    return _datetime.strptime(date_string, fmt)
                except ValueError:
                    continue
            return None
    except (ValueError, TypeError) as e:
        logger.debug(f"Failed to parse datetime string '{date_string}': {e}")
        return None


# =============================================================================
# Performance Information
# =============================================================================

def get_parser_info() -> Dict[str, Any]:
    """
    Get information about which parsers are being used.
    
    Returns:
        Dictionary with parser information and performance notes
    """
    return {
        "json": {
            "library": "orjson" if _HAS_ORJSON else ("ujson" if _HAS_UJSON else "json"),
            "optimized": _HAS_ORJSON or _HAS_UJSON,
            "performance_improvement": "2-3x faster" if _HAS_ORJSON else ("1.5-2x faster" if _HAS_UJSON else "baseline"),
        },
        "xml": {
            "library": "lxml" if _HAS_LXML else "xml.etree.ElementTree",
            "optimized": _HAS_LXML,
            "performance_improvement": "5-10x faster" if _HAS_LXML else "baseline",
        },
        "datetime": {
            "library": "python-dateutil" if _HAS_DATEUTIL else "datetime",
            "optimized": _HAS_DATEUTIL,
            "performance_improvement": "more robust" if _HAS_DATEUTIL else "baseline",
        },
    }
