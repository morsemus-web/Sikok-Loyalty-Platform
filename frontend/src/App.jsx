import { useEffect, useState } from 'react';
import { api } from './api';
import { auth, logout } from './store';
import ShopHeader from './components/ShopHeader.jsx';
import AuthCard from './components/AuthCard.jsx';
import Dashboard from './components/Dashboard.jsx';
import ShopMap from './components/ShopMap.jsx';

const SHOP_ID = Number(new URLSearchParams(location.search).get('shop') || 1);

export default function App() {
  const [shop, setShop] = useState(null);
  const [user, setUser] = useState(auth.user);

  useEffect(() => {
    api(`/api/shops/${SHOP_ID}`)
      .then(setShop)
      .catch(() => setShop({ name: 'Sikok' }));
  }, []);

  function handleAuthed(data) {
    auth.token = data.token;
    auth.user = { user_id: data.user_id, name: data.name, mobile_number: data.mobile_number };
    setUser(auth.user);
  }

  function handleLogout() {
    logout();
    setUser(null);
  }

  return (
    <main className="app">
      <ShopHeader shop={shop} />
      {user
        ? <Dashboard shopId={SHOP_ID} user={user} onLogout={handleLogout} />
        : <AuthCard onAuthed={handleAuthed} />}
      <ShopMap shop={shop} />
    </main>
  );
}
