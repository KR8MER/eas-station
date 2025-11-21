-- Fix for: column location_settings.storage_zone_codes does not exist
-- This script safely drops the column if it exists

-- Connect to your database and run this SQL

DO $$
BEGIN
    -- Check if column exists and drop it
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'location_settings'
        AND column_name = 'storage_zone_codes'
    ) THEN
        ALTER TABLE location_settings DROP COLUMN storage_zone_codes;
        RAISE NOTICE 'Dropped storage_zone_codes column';
    ELSE
        RAISE NOTICE 'Column storage_zone_codes does not exist, nothing to do';
    END IF;
END $$;
