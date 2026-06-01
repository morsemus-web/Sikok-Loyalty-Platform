-- Migration 003: named operators + per-transaction handler audit.
-- Idempotent — safe to re-run.

-- Operators who can act on the bot as owner. The shop owner (shops.telegram_chat_id)
-- and the env tech chat are always operators too, but registering them here gives
-- them display names that show up in approvals and the activity feed.
CREATE TABLE IF NOT EXISTS operators (
    chat_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'owner',
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed the two known operators with friendly names.
INSERT INTO operators (chat_id, name, role) VALUES
    ('8014075143', 'Owner', 'owner'),
    ('8567025747', 'Tech', 'tech')
ON CONFLICT (chat_id) DO NOTHING;

-- Record which operator logged each sale (display name at time of sale).
ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS handled_by VARCHAR(100);
