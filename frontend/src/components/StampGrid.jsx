const TOTAL = 4;

export default function StampGrid({ filled }) {
  return (
    <div className="stamps">
      {Array.from({ length: TOTAL }, (_, i) => (
        <div key={i} className={`stamp ${i < filled ? 'filled' : ''}`}>
          {i < filled ? '★' : i + 1}
        </div>
      ))}
    </div>
  );
}
