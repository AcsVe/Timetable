// Shared state + memoised reference lists (invalidated after writes).
import * as api from './api.js';

export const state = {
  me: null,
  timetables: [],
  ttId: null,          // currently selected timetable
  school: null,
};

const memo = new Map();

export function list(res, query = '') {
  const key = `/api/${res}${query}`;
  if (!memo.has(key)) {
    const p = api.get(key).then(r => r.items);
    p.catch(() => memo.delete(key));
    memo.set(key, p);
  }
  return memo.get(key);
}

export function invalidate(...prefixes) {
  for (const k of [...memo.keys()]) {
    if (!prefixes.length || prefixes.some(p => k.startsWith(`/api/${p}`))) memo.delete(k);
  }
}

export const byId = arr => Object.fromEntries(arr.map(o => [o.id, o]));

export function currentTimetable() {
  return state.timetables.find(t => t.id === state.ttId) || null;
}

export function isAdmin() { return state.me && state.me.role === 'admin'; }
export function canEdit() { return state.me && state.me.role !== 'viewer'; }
