'use strict';
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
exports.run=async({win,origin,token,dataDir,quit})=>{
  const wc=win.webContents,stage=process.env.EM_SMOKE_STAGE||'create';
  const evaluate=code=>wc.executeJavaScript(code);
  const wait=async condition=>{
    for(let i=0;i<200;i++){
      if(await evaluate(condition))return;
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    throw new Error('UI timeout: '+condition);
  };
  const flush=()=>evaluate('window.EnglishMatchDesktop.flush()');
  const api=route=>evaluate(`fetch(${JSON.stringify(route)}).then(r=>r.json())`);
  await wait(`Boolean(window.EnglishMatchDesktop && window.Study && document.querySelectorAll('#board .card').length && !document.getElementById('startReviewBtn').disabled)`);
  assert.equal(await evaluate('typeof require'),'undefined');
  assert.equal(await evaluate('typeof process'),'undefined');
  assert.equal((await fetch(origin+'/api/stats')).status,403);
  const stats=await api('/api/stats');
  if(stage==='create'){
    assert.equal(stats.total_vocabulary,16);
    await evaluate(`(async()=>{
      const first=document.querySelector('#board .card.english');
      first.click();document.querySelector('[data-key="'+first.dataset.pairId+'-vi"]').click();
      await window.EnglishMatchDesktop.flush();
      const r=await fetch('/api/vocabulary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({english:'desktop persistence test',vietnamese:'kiểm tra lưu dữ liệu',list_id:1})});
      if(r.status!==201)throw new Error('Cannot create word');
      document.querySelector('[data-view="review"]').click();
      document.getElementById('reviewMode').value='flashcard';
      document.getElementById('startReviewBtn').click();
    })()`);
    await wait(`Boolean(document.getElementById('flashCard') && !document.getElementById('startReviewBtn').disabled)`);
    await flush();
    assert.equal((await api('/api/review/progress')).item.words.length,17);
    for(let i=0;i<17;i++){
      await evaluate(`document.getElementById('flashCard').click();document.getElementById(${JSON.stringify(i===0?'flashForgot':'flashRemembered')}).click()`);
      await flush();
    }
    const learning=(await api('/api/learning/stats')).totals;
    assert.equal(learning.forgotten,1);assert.equal(learning.remembered,16);assert.equal(learning.needs_review,1);
    await evaluate(`document.querySelector('[data-view="history"]').click()`);
    await wait(`document.getElementById('historyMessage').textContent==='Đã cập nhật kết quả đã lưu.'`);
    assert.equal(await evaluate(`document.getElementById('wrongMetric').textContent`),'1');
    await evaluate(`document.getElementById('reviewMistakesBtn').click()`);
    await wait(`Boolean(document.getElementById('typingAnswer') && !document.getElementById('startReviewBtn').disabled)`);
    await flush();
    const review=(await api('/api/review/progress')).item;
    assert.equal(review.mode,'typing');assert.equal(review.wrongOnly,true);assert.equal(review.words.length,1);
    await evaluate(`document.getElementById('typingAnswer').value='deliberately incorrect answer';document.getElementById('typingForm').requestSubmit()`);
    await flush();
    assert.equal((await api('/api/learning/stats')).totals.wrong,1);
  }else{
    assert.equal(stats.total_vocabulary,17);
    const p=await api('/api/progress');
    assert.equal(p.item.pageStates.reduce((n,p)=>n+p.matched.length,0),1);
    const review=(await api('/api/review/progress')).item;
    assert.equal(review.mode,'typing');assert.equal(review.results.length,1);assert.equal(review.results[0].correct,false);
    await evaluate(`document.querySelector('[data-view="review"]').click();document.getElementById('typingNext').click()`);
    await flush();
    await evaluate(`[...document.querySelectorAll('#studyArea button')].find(b=>b.textContent==='Ôn từ sai').click()`);
    await wait(`Boolean(document.getElementById('typingAnswer') && !document.getElementById('typingAnswer').readOnly && !document.getElementById('startReviewBtn').disabled)`);
    await flush();
    const answer=(await api('/api/review/progress')).item.words[0].english;
    await evaluate(`document.getElementById('typingAnswer').value=${JSON.stringify(answer)};document.getElementById('typingForm').requestSubmit()`);
    await flush();
    assert.equal(await evaluate(`document.getElementById('typingFeedback').classList.contains('good')`),true);
    await evaluate(`document.getElementById('typingNext').click()`);
    await flush();
    assert.equal((await api('/api/learning/stats')).totals.needs_review,0);
    await evaluate(`document.querySelector('[data-view="history"]').click()`);
    await wait(`document.getElementById('historyMessage').textContent==='Đã cập nhật kết quả đã lưu.'`);
    assert.equal(await evaluate(`document.getElementById('wrongMetric').textContent`),'0');
  }
  const backup=await api('/api/backup');
  assert.equal(backup.version,2);assert.equal(backup.vocabulary.length,17);
  assert.ok(backup.learning.sessions.some(s=>s.mode==='flashcard'));
  assert.ok(backup.learning.sessions.some(s=>s.mode==='typing'));
  assert.equal((await fetch(origin+'/server.py',{headers:{'X-English-Match-Desktop':token}})).status,404);
  const speech=await evaluate(`({supported:'speechSynthesis' in window,englishVoices:window.speechSynthesis?.getVoices().filter(v=>/^en(?:-|_|$)/i.test(v.lang)).length||0})`);
  assert.equal(speech.supported,true);
  const image=await wc.capturePage(),out=process.env.EM_SMOKE_OUTPUT;
  if(out){fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,stage+'.png'),image.toPNG());fs.writeFileSync(path.join(out,stage+'.json'),JSON.stringify({ok:true,version:'1.1.0',platform:process.platform,arch:process.arch,stage,words:17,matched:1,flashcard:true,typing:true,wrongReview:true,history:true,speech,dataDir},null,2));}
  console.log('NATIVE_DESKTOP_SMOKE_OK '+process.platform+' '+process.arch+' '+stage+' flashcard typing wrong-review history');
  await quit();
};
