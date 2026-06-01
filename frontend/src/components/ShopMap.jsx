// Embeds the shop's Google Maps location as an iframe.
// Uses the no-API-key embed form: ...?q=LAT,LNG&output=embed
// Falls back gracefully if the shop has no maps_url configured.

export default function ShopMap({ shop }) {
  if (!shop?.maps_url) return null;

  // Convert "https://www.google.com/maps?q=28.676417,77.419389" → embed.
  const src = shop.maps_url.includes('output=embed')
    ? shop.maps_url
    : `${shop.maps_url}${shop.maps_url.includes('?') ? '&' : '?'}output=embed`;

  return (
    <section className="card map-card">
      <h2>Find us</h2>
      <p className="addr-small">{shop.address}</p>
      <div className="map-frame">
        <iframe
          title="Shop location on Google Maps"
          src={src}
          width="100%"
          height="220"
          loading="lazy"
          referrerPolicy="no-referrer-when-downgrade"
          allowFullScreen
        />
      </div>
      <a className="btn" href={shop.maps_url} target="_blank" rel="noopener noreferrer">
        🗺️ Open in Maps
      </a>
    </section>
  );
}
