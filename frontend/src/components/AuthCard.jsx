import { useState } from 'react';
import { api } from '../api';

export default function AuthCard({ onAuthed }) {
  const [mobile, setMobile] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [needsName, setNeedsName] = useState(false);
  const [err, setErr] = useState('');
  const [resetMsg, setResetMsg] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setErr('');
    setResetMsg('');
    setBusy(true);
    try {
      const payload = { mobile_number: mobile.trim(), password };
      if (needsName && name.trim()) payload.name = name.trim();
      const res = await api('/api/auth/login', { method: 'POST', body: payload });
      onAuthed(res);
    } catch (e) {
      if (e.detail === 'NEW_USER_NAME_REQUIRED') {
        setNeedsName(true);
        setErr('New here — please tell us your name.');
      } else {
        setErr(e.detail || e.message || 'Something went wrong.');
      }
    } finally {
      setBusy(false);
    }
  }

  async function forgot() {
    setErr('');
    setResetMsg('');
    if (!mobile.trim()) {
      setErr('Enter your mobile number first.');
      return;
    }
    try {
      await api('/api/auth/forgot-password', {
        method: 'POST',
        body: { mobile_number: mobile.trim() },
      });
      setResetMsg('Reset request sent. Ask the counter for your PIN, then sign in.');
    } catch (e) {
      setErr(e.detail || 'Could not send reset request.');
    }
  }

  return (
    <section className="card">
      <h2>Sign in</h2>
      <p className="hint">New here? We'll create your account automatically.</p>
      <form onSubmit={submit} autoComplete="on">
        <label>
          Mobile number
          <input
            type="tel"
            inputMode="tel"
            required
            minLength={7}
            maxLength={15}
            value={mobile}
            onChange={(e) => { setMobile(e.target.value); setNeedsName(false); }}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            required
            minLength={4}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {needsName && (
          <label>
            Your name
            <input
              type="text"
              autoComplete="name"
              maxLength={100}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        )}
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? 'Working…' : 'Continue'}
        </button>
        <button type="button" className="link" onClick={forgot}>
          Forgot password?
        </button>
        {err && <p className="err">{err}</p>}
        {resetMsg && <p className="status wait">{resetMsg}</p>}
      </form>
    </section>
  );
}
