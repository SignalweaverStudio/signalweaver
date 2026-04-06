-- Migration: 001_add_user_data_version.sql
-- Purpose: Add version column for optimistic concurrency (Stage 14)
-- Applies: vNext.9 → vNext.10
-- Note: Idempotency handled in application layer

ALTER TABLE user_data ADD COLUMN version INTEGER DEFAULT 1;