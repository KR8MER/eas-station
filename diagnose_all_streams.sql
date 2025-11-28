-- Comprehensive diagnostic for ALL stream types (SDR, HTTP, etc.)

\echo '================================================================================'
\echo 'DIAGNOSTIC: Audio Squeal Issue - ALL Stream Types'
\echo '================================================================================'

\echo ''
\echo '1. RADIO RECEIVERS (SDR-based streams):'
\echo '--------------------------------------------------------------------------------'
SELECT
    identifier,
    display_name,
    driver,
    frequency_hz / 1000000.0 as frequency_mhz,
    sample_rate as iq_sample_rate,
    modulation_type,
    audio_output,
    stereo_enabled,
    CASE
        WHEN sample_rate < 100000 THEN '❌ TOO LOW - Should be ~2.4MHz for IQ!'
        ELSE '✅ Looks OK'
    END as diagnosis
FROM radio_receivers
WHERE enabled = true
ORDER BY identifier;

\echo ''
\echo '2. AUDIO SOURCE CONFIGURATIONS (All stream types including HTTP/iHeart):'
\echo '--------------------------------------------------------------------------------'
SELECT
    name,
    source_type,
    enabled,
    auto_start,
    (config->>'sample_rate')::int as audio_sample_rate,
    (config->>'channels')::int as channels,
    config->>'device_params' as device_params,
    CASE
        WHEN source_type = 'stream' AND (config->>'sample_rate')::int < 32000 THEN
            '❌ TOO LOW - HTTP streams should be 44.1kHz+'
        WHEN source_type = 'sdr' AND (config->>'sample_rate')::int < 20000 THEN
            '❌ TOO LOW - SDR audio should be 24-48kHz'
        ELSE '✅ Looks OK'
    END as diagnosis
FROM audio_source_configs
WHERE enabled = true
ORDER BY source_type, name;

\echo ''
\echo '3. DETAILED HTTP/STREAM SOURCE INFO:'
\echo '--------------------------------------------------------------------------------'
SELECT
    name,
    source_type,
    (config->>'sample_rate')::int as configured_rate,
    (config->>'channels')::int as channels,
    config->'device_params'->>'stream_url' as stream_url,
    CASE
        WHEN config->'device_params'->>'stream_url' LIKE '%iheart%' THEN 'iHeart Stream'
        WHEN config->'device_params'->>'stream_url' LIKE '%%.m3u%' THEN 'M3U Playlist'
        WHEN config->'device_params'->>'stream_url' LIKE '%%.mp3%' THEN 'MP3 Stream'
        ELSE 'Other HTTP Stream'
    END as stream_type
FROM audio_source_configs
WHERE source_type = 'stream' AND enabled = true
ORDER BY name;

\echo ''
\echo '================================================================================'
\echo 'DIAGNOSIS COMPLETE'
\echo '================================================================================'
\echo ''
\echo 'Look for ❌ markers indicating misconfigured sample rates.'
\echo ''
\echo 'Common issues:'
\echo '  - SDR IQ sample rates < 100kHz (should be ~2.4MHz)'
\echo '  - HTTP stream audio rates < 32kHz (should match stream native rate, typically 44.1kHz or 48kHz)'
\echo '  - Sample rate mismatches between source config and actual stream format'
\echo ''
