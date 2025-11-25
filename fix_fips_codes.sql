-- Fix empty FIPS codes in location_settings for Putnam County, OH
-- This allows CAP alerts to be accepted and processed

UPDATE location_settings
SET fips_codes = '["039137"]'::jsonb
WHERE location_name = 'Putnam County, OH'
  AND (fips_codes IS NULL OR fips_codes = '[]'::jsonb);

-- Verify the fix
SELECT
    location_name,
    county,
    fips_codes,
    zone_codes
FROM location_settings
WHERE location_name = 'Putnam County, OH';
