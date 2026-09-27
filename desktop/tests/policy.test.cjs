const {test}=require('node:test');
const assert=require('node:assert/strict');
const {isLocalOrigin,isBackendOrigin,injectToken}=require('../electron/policy.cjs');
test('only the chosen loopback origin receives the desktop token',()=>{
 const origin='http://127.0.0.1:32123';
 assert.equal(isBackendOrigin(origin),true);
 for(const bad of ['https://example.org','http://localhost:8000','http://127.0.0.1:32123/path','http://a:b@127.0.0.1:32123']) assert.equal(isBackendOrigin(bad),false);
 assert.equal(isLocalOrigin(origin+'/api/backup',origin),true);
 for(const bad of ['http://127.0.0.1:32124','http://127.0.0.1.evil.example:32123','file:///etc/passwd','javascript:alert(1)']){
  assert.equal(isLocalOrigin(bad,origin),false);
  assert.deepEqual(injectToken({'x-English-Match-Desktop':'old',Accept:'text/html'},bad,origin,'secret'),{Accept:'text/html'});
 }
 assert.deepEqual(injectToken({},origin+'/api/stats',origin,'secret'),{'X-English-Match-Desktop':'secret'});
});
