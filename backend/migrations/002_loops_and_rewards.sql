-- Migration 002: per-customer loop tracking + per-shop, per-loop rewards.
-- All statements idempotent — safe to re-run.

ALTER TABLE loyalty_cards
    ADD COLUMN IF NOT EXISTS current_loop INT NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS shop_rewards (
    shop_id INT NOT NULL REFERENCES shops(shop_id) ON DELETE CASCADE,
    loop_number INT NOT NULL CHECK (loop_number >= 1),
    description TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (shop_id, loop_number)
);

-- Seed default reward for loop 1 of Dhamaka Sale if not already set.
INSERT INTO shop_rewards (shop_id, loop_number, description)
VALUES (1, 1, '₹50 OFF PER ITEM')
ON CONFLICT (shop_id, loop_number) DO NOTHING;
