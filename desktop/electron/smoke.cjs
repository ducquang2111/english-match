'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
exports.run = async ({win,origin,token,dataDir,quit}) => {
  const wc=win.webContents, stage=process.env.EM_SMOKE_STAGE || 'create';
  for(let i=0;i<100;i++){
    if(await wc.executeJavaScript(`Boolean(window.EnglishMatchDesktop && document.querySelectorAll('#board .card').length)`)) break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.equal(await wc.executeJavaScript('typeof require'), 'undefined');
  assert.equal(await wc.executeJavaScript('typeof process'), 'undefined');
  assert.equal((await fetch(origin+'/api/stats')).status,403);
  const stats=await wc.executeJavaScript(`fetch('/api/stats').then(r=>r.json())`);
  if(stage==='create') {
    assert.equal(stats.total_vocabulary,16);
    await wc.executeJavaScript(`(async()=>{
      const first=document.querySelector('#board .card.english');
      first.click();document.querySelector('[data-key="'+first.dataset.pairId+'-vi"]').click();
      await window.EnglishMatchDesktop.flush();
      const r=await fetch('/api/vocabulary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({english:'desktop persistence test',vietnamese:'kiểm tra lưu dữ liệu',list_id:1})});
      if(r.status!==201)throw new Error('Cannot create word');
    })()`);
  } else {
    assert.equal(stats.total_vocabulary,17);
    const p=await wc.executeJavaScript(`fetch('/api/progress').then(r=>r.json())`);
    assert.equal(p.item.pageStates.reduce((n,p)=>n+p.matched.length,0),1);
  }
  const backup=await wc.executeJavaScript(`fetch('/api/backup').then(r=>r.json())`);
  assert.equal(backup.vocabulary.length,17);
  assert.equal((await fetch(origin+'/server.py',{headers:{'X-English-Match-Desktop':token}})).status,404);
  const image=await wc.capturePage();
  const out=process.env.EM_SMOKE_OUTPUT;
  if(out){fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,stage+'.png'),image.toPNG());fs.writeFileSync(path.join(out,stage+'.json'),JSON.stringify({ok:true,platform:process.platform,arch:process.arch,stage,words:17,matched:1,dataDir},null,2));}
  console.log('NATIVE_DESKTOP_SMOKE_OK '+process.platform+' '+process.arch+' '+stage);
  await quit();
};
