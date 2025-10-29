-- Migration: Add 'source' column to cap_alerts table
-- Created: 2025-10-29
-- Purpose: Track alert source (NOAA, IPAWS, SDR) for multi-source polling

-- Check if column already exists before adding
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'cap_alerts'
          AND column_name = 'source'
    ) THEN
        -- Add source column with default 'noaa' for existing records
        ALTER TABLE cap_alerts
        ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'noaa';

        -- Create index for faster filtering by source
        CREATE INDEX idx_cap_alerts_source ON cap_alerts(source);

        RAISE NOTICE 'Added source column to cap_alerts table';
    ELSE
        RAISE NOTICE 'Source column already exists, skipping migration';
    END IF;
END $$;

-- Verify the migration
SELECT column_name, data_type, column_default, is_nullable
FROM information_schema.columns
WHERE table_name = 'cap_alerts' AND column_name = 'source';
