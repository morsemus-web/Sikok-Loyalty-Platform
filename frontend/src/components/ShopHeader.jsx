export default function ShopHeader({ shop }) {
  if (!shop) {
    return (
      <header className="shop">
        <h1>Loading…</h1>
      </header>
    );
  }
  return (
    <header className="shop">
      <h1>{shop.name}</h1>
      {shop.sub_name && <p className="sub">{shop.sub_name}</p>}
      <p className="tagline">🎁 QR SCAN KARE OR DISCOUNT UNLOCK KARE 🎉</p>
      {shop.address && <p className="addr">{shop.address}</p>}
      <div className="actions">
        <a className="btn" href={shop.whatsapp_url || '#'} target="_blank" rel="noopener noreferrer">
          💬 WhatsApp Us
        </a>
        <a className="btn" href={shop.maps_url || '#'} target="_blank" rel="noopener noreferrer">
          🗺️ Directions
        </a>
      </div>
    </header>
  );
}
