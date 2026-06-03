-- Migration 004: drop the amount-entry requirement + shop rename + ₹50 loop-1.
-- Idempotent.

-- Sales are now logged without an amount (operators just approve the stamp).
ALTER TABLE transactions ALTER COLUMN sale_amount DROP NOT NULL;

-- Rename the tenant.
UPDATE shops SET name = 'Singh and Sons', sub_name = NULL WHERE shop_id = 1;

-- First-loop reward is ₹50 off per item.
INSERT INTO shop_rewards (shop_id, loop_number, description)
VALUES (1, 1, '₹50 OFF PER ITEM')
ON CONFLICT (shop_id, loop_number) DO UPDATE SET description = EXCLUDED.description;
