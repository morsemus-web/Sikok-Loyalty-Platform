import { useEffect, useRef, useState } from 'react';

const TOTAL = 4;

export default function StampGrid({ filled }) {
  // Track which index was *just* filled so we can play a one-shot pop animation
  // only on the new stamp, not on every render.
  const prevRef = useRef(filled);
  const [justFilled, setJustFilled] = useState(null);

  useEffect(() => {
    if (filled > prevRef.current) {
      setJustFilled(filled - 1);  // index of the newly-filled slot
      const t = setTimeout(() => setJustFilled(null), 900);
      prevRef.current = filled;
      return () => clearTimeout(t);
    }
    prevRef.current = filled;
  }, [filled]);

  return (
    <div className="stamps" aria-label={`${filled} of ${TOTAL} stamps collected`}>
      {Array.from({ length: TOTAL }, (_, i) => {
        const isFilled = i < filled;
        const isJust = i === justFilled;
        return (
          <div
            key={i}
            className={[
              'stamp',
              isFilled ? 'filled' : '',
              isJust ? 'just-filled' : '',
            ].filter(Boolean).join(' ')}
          >
            {isFilled ? '★' : i + 1}
          </div>
        );
      })}
    </div>
  );
}
