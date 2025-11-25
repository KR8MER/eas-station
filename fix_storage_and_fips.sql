-- Fix storage_zone_codes and FIPS codes for existing installation
-- Run this to update your current database

-- 1. Fix storage_zone_codes to include all zone codes (not just 2)
UPDATE location_settings
SET storage_zone_codes = zone_codes
WHERE storage_zone_codes IS NOT NULL;

-- 2. Add FIPS codes for Putnam County
UPDATE location_settings
SET fips_codes = '["039137"]'::jsonb
WHERE (fips_codes IS NULL OR fips_codes = '[]'::jsonb);

-- 3. Verify the fix
SELECT
    location_name,
    county,
    jsonb_array_length(zone_codes) as zone_count,
    jsonb_array_length(storage_zone_codes) as storage_zone_count,
    fips_codes
FROM location_settings;
