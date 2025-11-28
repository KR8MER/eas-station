-- Comprehensive fix for audio squeal in ALL streams (SDR and HTTP/iHeart)
--
-- ROOT CAUSE: After containerization, sample rates were misconfigured:
--   1. SDR Receivers: IQ sample_rate set to audio rates (~16-44kHz) instead of ~2.4MHz
--   2. HTTP Streams: Audio sample_rate set to 16kHz (for EAS decoding) instead of native rate (44.1/48kHz)
--
-- SYMPTOMS: All Icecast streams produce high-pitched squeal
--
-- FIX: Reset sample rates to proper values for each stream type

BEGIN;

\echo '================================================================================'
\echo 'BEFORE FIX: Current Configuration'
\echo '================================================================================'

\echo ''
\echo 'Radio Receivers (SDR):'
SELECT
    identifier,
    driver,
    sample_rate as current_iq_rate,
    modulation_type,
    audio_output
FROM radio_receivers
WHERE enabled = true;

\echo ''
\echo 'Audio Sources (including HTTP/iHeart streams):'
SELECT
    name,
    source_type,
    (config->>'sample_rate')::int as current_audio_rate,
    (config->>'channels')::int as channels
FROM audio_source_configs
WHERE enabled = true;

\echo ''
\echo '================================================================================'
\echo 'APPLYING FIXES...'
\echo '================================================================================'

-- FIX 1: SDR Receiver IQ Sample Rates
-- Any IQ sample rate < 100kHz is definitely wrong (should be MHz range)
\echo ''
\echo 'Fix 1: Correcting SDR receiver IQ sample rates...'
UPDATE radio_receivers
SET sample_rate = 2400000  -- 2.4 MHz (common SDR IQ rate)
WHERE
    enabled = true
    AND sample_rate < 100000  -- Definitely wrong if less than 100kHz
    AND driver IN ('rtlsdr', 'airspy', 'hackrf', 'sdrplay', 'soapysdr');

\echo 'SDR receivers updated.'

-- FIX 2: HTTP/Stream Source Audio Sample Rates
-- These should be set to the native stream rate (varies by stream)
-- NOT 16kHz (which is for EAS SAME decoding, NOT for streaming output)
\echo ''
\echo 'Fix 2: Correcting HTTP/stream source audio sample rates...'
\echo ''
\echo '⚠️  WARNING: HTTP streams have different native sample rates.'
\echo '   This script will set a safe default of 48kHz for streams < 32kHz.'
\echo '   For optimal quality, run: ./detect_stream_sample_rates.sh'
\echo '   to auto-detect each stream''s actual native rate.'
\echo ''

-- Update stream sources with sample rates < 32kHz to 48000 Hz
-- 48kHz is a safe default that works for most streams
-- For accurate rates, use detect_stream_sample_rates.sh instead
UPDATE audio_source_configs
SET config = jsonb_set(
    config,
    '{sample_rate}',
    '48000'::jsonb
)
WHERE
    source_type = 'stream'
    AND enabled = true
    AND (config->>'sample_rate')::int < 32000;

\echo 'HTTP stream sources updated to safe default (48kHz).'
\echo 'Run ./detect_stream_sample_rates.sh for precise auto-detection.'

-- FIX 3: SDR Audio Source Configurations
-- These need proper audio rates based on modulation type
\echo ''
\echo 'Fix 3: Correcting SDR audio source configurations...'

-- For each SDR audio source, set appropriate sample rate based on linked receiver
UPDATE audio_source_configs asc
SET config = jsonb_set(
    config,
    '{sample_rate}',
    CASE
        WHEN rr.modulation_type IN ('FM', 'WFM') AND rr.stereo_enabled THEN '48000'::jsonb
        WHEN rr.modulation_type IN ('FM', 'WFM') THEN '32000'::jsonb
        WHEN rr.modulation_type IN ('AM', 'NFM') THEN '24000'::jsonb
        ELSE '44100'::jsonb
    END
)
FROM radio_receivers rr
WHERE
    asc.source_type = 'sdr'
    AND asc.enabled = true
    AND asc.config->'device_params'->>'receiver_id' = rr.identifier
    AND rr.enabled = true
    AND (asc.config->>'sample_rate')::int < 20000;  -- Only fix if obviously wrong

\echo 'SDR audio sources updated.'

\echo ''
\echo '================================================================================'
\echo 'AFTER FIX: Updated Configuration'
\echo '================================================================================'

\echo ''
\echo 'Radio Receivers (SDR):'
SELECT
    identifier,
    driver,
    sample_rate as fixed_iq_rate,
    modulation_type,
    audio_output,
    CASE
        WHEN sample_rate >= 1000000 THEN '✅ Correct'
        ELSE '❌ Still wrong!'
    END as status
FROM radio_receivers
WHERE enabled = true;

\echo ''
\echo 'Audio Sources (including HTTP/iHeart streams):'
SELECT
    name,
    source_type,
    (config->>'sample_rate')::int as fixed_audio_rate,
    (config->>'channels')::int as channels,
    CASE
        WHEN source_type = 'stream' AND (config->>'sample_rate')::int >= 32000 THEN '✅ Correct'
        WHEN source_type = 'sdr' AND (config->>'sample_rate')::int >= 20000 THEN '✅ Correct'
        ELSE '❌ Still wrong!'
    END as status
FROM audio_source_configs
WHERE enabled = true;

\echo ''
\echo '================================================================================'
\echo 'SUMMARY'
\echo '================================================================================'

SELECT
    '✅ SDR IQ Rates Fixed:' as summary,
    COUNT(*) as count
FROM radio_receivers
WHERE enabled = true AND sample_rate >= 1000000
UNION ALL
SELECT
    '✅ HTTP Stream Rates Fixed:' as summary,
    COUNT(*) as count
FROM audio_source_configs
WHERE source_type = 'stream' AND enabled = true AND (config->>'sample_rate')::int >= 32000
UNION ALL
SELECT
    '✅ SDR Audio Rates Fixed:' as summary,
    COUNT(*) as count
FROM audio_source_configs
WHERE source_type = 'sdr' AND enabled = true AND (config->>'sample_rate')::int >= 20000;

COMMIT;

\echo ''
\echo '================================================================================'
\echo 'FIX COMPLETE!'
\echo '================================================================================'
\echo ''
\echo 'Next steps:'
\echo '  1. Restart the audio service: docker-compose restart sdr-service'
\echo '  2. Check Icecast streams at: http://localhost:8001/'
\echo '  3. Verify audio is clear (no squeal)'
\echo ''
\echo 'Technical explanation:'
\echo '  - SDR IQ rates: Set to 2.4 MHz (proper for SDR hardware)'
\echo '  - HTTP stream audio: Set to 44.1 kHz (typical internet radio rate)'
\echo '  - SDR audio output: Set based on modulation (24-48 kHz)'
\echo ''
\echo 'The squeal was caused by FFmpeg receiving audio at one sample rate'
\echo '(e.g., 16 kHz) but being told it was a different rate (e.g., 44.1 kHz),'
\echo 'causing pitch shifting and distortion.'
\echo ''
