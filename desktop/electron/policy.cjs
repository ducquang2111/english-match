'use strict';
function isLocalOrigin(url, origin) {
  try { const u = new URL(url); return u.origin === origin && !u.username && !u.password; }
  catch { return false; }
}
function isBackendOrigin(origin) {
  try {
    const u = new URL(origin);
    return u.protocol === 'http:' && u.hostname === '127.0.0.1' && Number(u.port) > 0 &&
      !u.username && !u.password && u.pathname === '/' && !u.search && !u.hash;
  } catch { return false; }
}
function injectToken(headers, url, origin, token) {
  const result = {...headers};
  for (const name of Object.keys(result)) if (name.toLowerCase() === 'x-english-match-desktop') delete result[name];
  if (isLocalOrigin(url, origin)) result['X-English-Match-Desktop'] = token;
  return result;
}
module.exports = {isLocalOrigin, isBackendOrigin, injectToken};
