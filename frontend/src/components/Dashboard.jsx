import { useEffect, useRef, useState } from 'react';
import { io } from 'socket.io-client';
import { api } from '../api';
import { auth } from '../store';
import StampGrid from './StampGrid.jsx';

const TOTAL = 4;

export default function Dashboard({ shopId, user, onLogout }) {
  const [card, setCard] = useState(null);
  const [status, setStatus] = useState({ text: '', kind: '' });
  const [busy, setBusy] = useState(false);
  const sockRef = useRef(null);

  async function loadCard() {
    const c = await api(`/api/me/card?shop_id=${shopId}`, { withAuth: true });
    setCard(c);
    if (c.stamped_today) {
      setStatus({ text: "Today's stamp is already collected. See you tomorrow!", kind: 'ok' });
    } else {
      setStatus({ text: '', kind: '' });
    }
    return c;
  }

  useEffect(() => {
    loadCard().catch((e) => {
      if (e.status === 401) onLogout();
    });
    return () => {
      try { sockRef.current?.disconnect(); } catch {}
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function teardownSocket() {
    try { sockRef.current?.disconnect(); } catch {}
    sockRef.current = null;
  }

  function openSocket(pendingId) {
    teardownSocket();
    const s = io({
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      auth: { token: auth.token, pending_id: pendingId },
    });
    sockRef.current = s;

    s.on('connect_error', () => {
      setStatus({ text: 'Connection lost. Try again.', kind: 'err' });
      teardownSocket();
      setBusy(false);
    });

    s.on('stamp_approved', async (payload) => {
      await loadCard();
      setStatus({
        text: payload?.discount_applied
          ? '🎉 Reward unlocked! Your card has reset for the next loop.'
          : '✅ Stamp added! See you next visit.',
        kind: 'ok',
      });
      teardownSocket();
      // Leave `busy` true — loadCard() set stamped_today, button stays disabled.
    });

    s.on('stamp_declined', (payload) => {
      setStatus({ text: payload?.reason || 'Declined by Counter', kind: 'err' });
      teardownSocket();
      setBusy(false);
    });
  }

  async function requestStamp() {
    if (card?.stamped_today) return;
    setBusy(true);
    setStatus({ text: 'Sending request to the counter…', kind: 'wait' });
    try {
      const res = await api('/api/stamps/request', {
        method: 'POST',
        body: { shop_id: shopId },
        withAuth: true,
      });
      setStatus({ text: 'Waiting for Counter Approval…', kind: 'wait' });
      openSocket(res.pending_id);
    } catch (e) {
      if (e.status === 409) {
        setStatus({ text: e.detail || "Today's stamp is already collected.", kind: 'ok' });
        await loadCard();
      } else {
        setStatus({ text: e.detail || 'Request failed.', kind: 'err' });
      }
      setBusy(false);
    }
  }

  const filled = card?.current_stamps ?? 0;
  const loop = card?.current_loop ?? 1;
  const nextReward = card?.next_reward;
  const remaining = Math.max(0, TOTAL - filled);
  const disabled = busy || (card?.stamped_today ?? false);

  return (
    <section className="card">
      <p className="welcome">Welcome, {user.name}</p>
      <p className="last-visit">
        {card?.last_visit_ist
          ? `Last visit: ${card.last_visit_ist}`
          : 'No visits yet — scan your first stamp today.'}
      </p>
      <h2>Your loyalty card · Loop {loop}</h2>
      <StampGrid filled={filled} />
      <p className="progress">
        {filled >= TOTAL - 1
          ? `Your next visit unlocks your Loop ${loop} reward!`
          : `${remaining} more visit${remaining === 1 ? '' : 's'} to unlock your Loop ${loop} reward.`}
      </p>
      {nextReward && (
        <div className="reward-callout">
          <span className="reward-label">🎁 You'll unlock</span>
          <span className="reward-text">{nextReward}</span>
        </div>
      )}
      <button className="btn primary big" disabled={disabled} onClick={requestStamp}>
        Request Stamp
      </button>
      <p className={`status ${status.kind}`} aria-live="polite">{status.text}</p>
      <button className="link" onClick={onLogout}>Sign out</button>
    </section>
  );
}
