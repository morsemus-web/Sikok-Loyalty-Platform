const KEY_TOKEN = 'sikok.token';
const KEY_USER = 'sikok.user';

export const auth = {
  get token() { return localStorage.getItem(KEY_TOKEN); },
  set token(v) { v ? localStorage.setItem(KEY_TOKEN, v) : localStorage.removeItem(KEY_TOKEN); },
  get user() {
    try { return JSON.parse(localStorage.getItem(KEY_USER) || 'null'); }
    catch { return null; }
  },
  set user(v) { v ? localStorage.setItem(KEY_USER, JSON.stringify(v)) : localStorage.removeItem(KEY_USER); },
};

export function logout() {
  auth.token = null;
  auth.user = null;
}
