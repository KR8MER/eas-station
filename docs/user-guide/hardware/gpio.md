# GPIO Relay Control

Configure Raspberry Pi GPIO for transmitter keying and relay control.

## Overview

GPIO control enables:
- Transmitter PTT (push-to-talk) keying
- Multi-relay sequencing
- LED indicators
- General-purpose switching

## Hardware Requirements

- Raspberry Pi (any model with GPIO)
- Relay board (5V compatible)
- Optional: Opto-isolator for safety

## Wiring

**Simple relay connection:**

```
RPi GPIO 17 → Relay IN
RPi 5V      → Relay VCC
RPi GND     → Relay GND
```

**With opto-isolator (recommended):**

```
RPi GPIO 17 → Opto Input +
RPi GND     → Opto Input -
Relay IN    → Opto Output +
External 5V → Opto Output - (common with relay VCC)
```

## Configuration

In `.env`:

```bash
EAS_GPIO_PIN=17
EAS_GPIO_ACTIVE_STATE=HIGH
EAS_GPIO_HOLD_SECONDS=5
```

## Testing

Test GPIO control:

```python
import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BCM)
GPIO.setup(17, GPIO.OUT)

# Key transmitter
GPIO.output(17, GPIO.HIGH)
time.sleep(5)
GPIO.output(17, GPIO.LOW)

GPIO.cleanup()
```

## Pin Reference

**Common GPIO pins (BCM numbering):**

| Pin | Notes |
|-----|-------|
| 17  | Default EAS Station |
| 27  | Alternative |
| 22  | Alternative |
| 23  | Alternative |

Avoid: 2, 3, 14, 15 (reserved functions)

## Safety

!!! danger "Electrical Isolation"
    - **Always use opto-isolators** for transmitter keying
    - Never connect GPIO directly to RF equipment
    - Use appropriate relay ratings
    - Proper grounding essential

## Troubleshooting

**GPIO not working:**

1. Check RPi.GPIO installed
2. Verify pin numbering mode
3. Test with LED first
4. Check permissions

See [Troubleshooting Guide](../troubleshooting.md).
