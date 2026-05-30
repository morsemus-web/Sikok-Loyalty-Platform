-- Sikok initial schema (PostgreSQL)

CREATE TABLE IF NOT EXISTS shops (
    shop_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    sub_name VARCHAR(255),
    address TEXT,
    whatsapp_number VARCHAR(20),
    whatsapp_url TEXT,
    maps_url TEXT,
    telegram_chat_id VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    mobile_number VARCHAR(15) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loyalty_cards (
    card_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    shop_id INT NOT NULL REFERENCES shops(shop_id) ON DELETE CASCADE,
    current_stamps INT NOT NULL DEFAULT 0 CHECK (current_stamps >= 0 AND current_stamps <= 4),
    last_visit TIMESTAMP,
    UNIQUE(user_id, shop_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id SERIAL PRIMARY KEY,
    card_id INT NOT NULL REFERENCES loyalty_cards(card_id) ON DELETE CASCADE,
    sale_amount DECIMAL(10, 2) NOT NULL,
    discount_applied BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_loyalty_user_shop ON loyalty_cards(user_id, shop_id);
CREATE INDEX IF NOT EXISTS idx_tx_card ON transactions(card_id);

-- Seed the initial tenant: Dhamaka Sale
INSERT INTO shops (shop_id, name, sub_name, address, whatsapp_number, whatsapp_url, maps_url, telegram_chat_id)
VALUES (
    1,
    'Dhamaka Sale',
    'C/o Singh & sons',
    'Sewa nagar, Meerut road, Pillar no 520, Near Pragati hospital, Ghaziabad',
    '+91 8744071569',
    'https://wa.me/918744071569',
    'https://www.google.com/maps?q=28.676417,77.419389',
    'REPLACE_WITH_OWNER_TELEGRAM_CHAT_ID'
)
ON CONFLICT (shop_id) DO NOTHING;
