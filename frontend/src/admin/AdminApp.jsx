import { useEffect, useState } from 'react';

// Telegram Mini App global (injected by telegram-web-app.js).
const tg = window.Telegram?.WebApp;

let TOKEN = null;

async function adminApi(path, { method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (TOKEN) headers.Authorization = `Bearer ${TOKEN}`;
  const res = await fetch(`/api/admin${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const txt = await res.text();
  const data = txt ? JSON.parse(txt) : null;
  if (!res.ok) {
    const err = new Error(data?.detail || res.statusText);
    err.status = res.status;
    throw err;
  }
  return data;
}

export default function AdminApp() {
  const [phase, setPhase] = useState('auth'); // auth | ready | error
  const [me, setMe] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('stats');

  useEffect(() => {
    try { tg?.ready(); tg?.expand(); } catch {}
    const initData = tg?.initData || '';
    if (!initData) {
      setError('Open this from the Sikok bot inside Telegram.');
      setPhase('error');
      return;
    }
    adminApi('/auth', { method: 'POST', body: { init_data: initData } })
      .then((res) => {
        TOKEN = res.token;
        setMe(res);
        setPhase('ready');
      })
      .catch((e) => {
        setError(e.status === 403 ? "You're not a Sikok operator." : (e.message || 'Sign-in failed.'));
        setPhase('error');
      });
  }, []);

  if (phase === 'auth') return <div className="center">Signing you in…</div>;
  if (phase === 'error') return <div className="center err">{error}</div>;

  return (
    <div className="admin">
      <header className="topbar">
        <strong>Sikok</strong>
        <span className="who">{me?.name}</span>
      </header>

      <nav className="tabs">
        <button className={tab === 'stats' ? 'on' : ''} onClick={() => setTab('stats')}>Stats</button>
        <button className={tab === 'customers' ? 'on' : ''} onClick={() => setTab('customers')}>Customers</button>
        <button className={tab === 'rewards' ? 'on' : ''} onClick={() => setTab('rewards')}>Rewards</button>
      </nav>

      <main>
        {tab === 'stats' && <StatsTab />}
        {tab === 'customers' && <CustomersTab />}
        {tab === 'rewards' && <RewardsTab />}
      </main>
    </div>
  );
}

function useAsync(fn, deps = []) {
  const [state, setState] = useState({ loading: true, data: null, error: '' });
  useEffect(() => {
    let alive = true;
    setState({ loading: true, data: null, error: '' });
    fn()
      .then((d) => alive && setState({ loading: false, data: d, error: '' }))
      .catch((e) => alive && setState({ loading: false, data: null, error: e.message || 'Failed' }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

function StatsTab() {
  const { loading, data, error } = useAsync(() => adminApi('/stats'));
  if (loading) return <div className="center">Loading…</div>;
  if (error) return <div className="center err">{error}</div>;
  return (
    <div className="cards">
      <Stat label="Customers" value={data.customers} />
      <Stat label="Sales logged" value={data.sales} />
      <Stat label="Revenue" value={`₹${data.revenue.toLocaleString('en-IN')}`} />
      <Stat label="Rewards redeemed" value={data.rewards_redeemed} />
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function CustomersTab() {
  const { loading, data, error } = useAsync(() => adminApi('/customers'));
  const [q, setQ] = useState('');
  if (loading) return <div className="center">Loading…</div>;
  if (error) return <div className="center err">{error}</div>;
  const list = data.customers.filter(
    (c) => c.name.toLowerCase().includes(q.toLowerCase()) || c.mobile_number.includes(q)
  );
  return (
    <div>
      <input className="search" placeholder="Search name or mobile…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="rows">
        {list.map((c) => (
          <div className="row" key={c.user_id}>
            <div className="row-main">
              <span className="name">{c.name}</span>
              <span className="mobile">{c.mobile_number}</span>
            </div>
            <div className="row-meta">
              <span className="chip">Loop {c.current_loop}</span>
              <span className="chip">{c.current_stamps}/4</span>
              <span className="muted">{c.visits} visits · ₹{c.ltv.toLocaleString('en-IN')}</span>
            </div>
          </div>
        ))}
        {list.length === 0 && <div className="center muted">No matches.</div>}
      </div>
    </div>
  );
}

function RewardsTab() {
  const [version, setVersion] = useState(0);
  const { loading, data, error } = useAsync(() => adminApi('/rewards'), [version]);
  const [loop, setLoop] = useState('');
  const [desc, setDesc] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  async function save(e) {
    e.preventDefault();
    setMsg('');
    if (!loop || !desc.trim()) { setMsg('Enter a loop number and reward text.'); return; }
    setSaving(true);
    try {
      await adminApi('/rewards', { method: 'POST', body: { loop: Number(loop), description: desc.trim() } });
      setLoop(''); setDesc('');
      setMsg('Saved.');
      setVersion((v) => v + 1);
    } catch (e2) {
      setMsg(e2.message || 'Save failed.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="rows">
        {loading ? <div className="center">Loading…</div>
          : error ? <div className="center err">{error}</div>
          : data.rewards.length === 0 ? <div className="center muted">No rewards set yet.</div>
          : data.rewards.map((r) => (
            <div className="row" key={r.loop}>
              <span className="chip">Loop {r.loop}</span>
              <span className="reward">{r.description}</span>
            </div>
          ))}
      </div>

      <form className="reward-form" onSubmit={save}>
        <h3>Set / update a reward</h3>
        <div className="form-row">
          <input className="loop-input" type="number" min="1" placeholder="Loop" value={loop} onChange={(e) => setLoop(e.target.value)} />
          <input className="desc-input" placeholder="e.g. ₹150 off per item" value={desc} onChange={(e) => setDesc(e.target.value)} />
        </div>
        <button className="save-btn" disabled={saving}>{saving ? 'Saving…' : 'Save reward'}</button>
        {msg && <p className="msg">{msg}</p>}
      </form>
    </div>
  );
}
