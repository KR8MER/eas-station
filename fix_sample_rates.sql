-- Fix for audio squeal issue: Correct sample rate mismatches
--
-- The issue: After containerization, the RadioReceiver.sample_rate field
-- (which should be the SDR's IQ sample rate, ~2-3 MHz) was accidentally
-- set to an audio sample rate (~44 kHz), causing the demodulator to
-- interpret IQ data at the wrong rate and producing a high-pitched squeal.
--
-- This script fixes the IQ sample rates for all radio receivers.

BEGIN;

-- Display current configuration BEFORE fix
SELECT
    '=== BEFORE FIX: Radio Receivers ===' as status,
    identifier,
    driver,
    frequency_hz / 1000000.0 as frequency_mhz,
    sample_rate as iq_sample_rate,
    modulation_type,
    audio_output,
    stereo_enabled
FROM radio_receivers
WHERE enabled = true
ORDER BY identifier;

SELECT
    '=== BEFORE FIX: Audio Sources ===' as status,
    name,
    source_type,
    config->>'sample_rate' as audio_sample_rate,
    config->>'channels' as channels
FROM audio_source_configs
WHERE enabled = true AND source_type = 'sdr'
ORDER BY name;

-- Fix: Update IQ sample rates for receivers with suspiciously low rates
-- Any sample_rate < 100000 (100 kHz) is likely an audio rate, not an IQ rate
UPDATE radio_receivers
SET
    sample_rate = 2400000  -- 2.4 MHz is a common SDR IQ rate
WHERE
    enabled = true
    AND sample_rate < 100000
    AND driver IN ('rtlsdr', 'airspy', 'hackrf', 'sdrplay', 'soapysdr');

-- Display results AFTER fix
SELECT
    '=== AFTER FIX: Radio Receivers ===' as status,
    identifier,
    driver,
    frequency_hz / 1000000.0 as frequency_mhz,
    sample_rate as iq_sample_rate,
    modulation_type,
    audio_output,
    stereo_enabled
FROM radio_receivers
WHERE enabled = true
ORDER BY identifier;

-- Show which receivers were fixed
SELECT
    '=== SUMMARY: Receivers Fixed ===' as status,
    COUNT(*) as receivers_fixed
FROM radio_receivers
WHERE
    enabled = true
    AND sample_rate = 2400000
    AND driver IN ('rtlsdr', 'airspy', 'hackrf', 'sdrplay', 'soapysdr');

COMMIT;

-- Instructions:
-- After running this script, you MUST restart the audio service:
--   docker-compose restart sdr-service
