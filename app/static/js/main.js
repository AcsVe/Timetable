// Entry point. The page loads this file with a version query (?v=…) for cache busting, and it
// imports app.js by its plain URL — the same URL the views use — so the app module (and its
// boot sequence, router and listeners) exists exactly once.
import './app.js';
