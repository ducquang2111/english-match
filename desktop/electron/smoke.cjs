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
      document.querySelector('[data-view="vocab"]').click();
      document.getElementById('englishInput').value='order';
      document.getElementById('vietnameseInput').value='đặt hàng';
      document.getElementById('partOfSpeechInput').value='n/v';
      document.getElementById('phoneticInput').value='/ˈɔːdə/';
      document.getElementById('addForm').requestSubmit();
    })()`);
    await wait(`document.getElementById('formMsg').textContent.startsWith('Đã lưu từ.')`);
    const added=(await api('/api/vocabulary?search=order')).items[0];
    assert.equal(added.english,'order');assert.equal(added.part_of_speech,'n/v');assert.equal(added.phonetic,'/ˈɔːdə/');
    await evaluate(`(()=>{
      const row=document.querySelector('.vocab-row[data-id="${added.id}"]');
      if(row.querySelector('.word-pos').textContent!=='n/v'||row.querySelector('.word-phonetic').textContent!=='/ˈɔːdə/')throw new Error('Missing management columns');
      [...row.querySelectorAll('button')].find(b=>b.textContent==='Sửa').click();
      document.getElementById('editPartOfSpeech').value='v/n';
      document.getElementById('editPhonetic').value='/ˈɔːrdər/';
      document.getElementById('editForm').requestSubmit();
    })()`);
    await wait(`!document.getElementById('editDialog').open && document.querySelector('.vocab-row[data-id="${added.id}"] .word-phonetic').textContent==='/ˈɔːrdər/'`);
    await flush();
    assert.equal((await api('/api/progress')).item.pageStates.reduce((n,p)=>n+p.matched.length,0),1);
    await evaluate(`document.querySelector('[data-view="review"]').click();document.getElementById('reviewMode').value='flashcard';document.getElementById('startReviewBtn').click()`);
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
    assert.equal(stats.total_vocabulary,19);
    const saved=(await api('/api/vocabulary?search=order')).items[0];
    assert.equal(saved.english,'order');assert.equal(saved.part_of_speech,'v/n');assert.equal(saved.phonetic,'/ˈɔːrdər/');
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
  if(stage==='create'){
    await evaluate(`(()=>{
      document.querySelector('[data-view="data"]').click();
      const input=document.getElementById('importText');
      input.value='broken | n | thiếu nghĩa';input.dispatchEvent(new Event('input'));
      document.getElementById('previewImportBtn').click();
    })()`);
    await wait(`document.getElementById('importMessage').textContent.includes('1 dòng lỗi')`);
    assert.equal(await evaluate(`document.getElementById('applyImportBtn').disabled`),true);
    await evaluate(`(()=>{
      const input=document.getElementById('importText');
      input.value=${JSON.stringify('provide | v | /prəˈvaɪd/ | cung cấp\nafternoon | buổi chiều\norder | n | /unused/ | đặt hàng')};
      input.dispatchEvent(new Event('input'));
      document.getElementById('previewImportBtn').click();
    })()`);
    await wait(`!document.getElementById('applyImportBtn').disabled`);
    assert.equal(await evaluate(`document.querySelectorAll('#importPreview th').length`),6);
    assert.equal(await evaluate(`document.querySelector('#importPreview tbody tr').cells[2].textContent`),'v');
    assert.equal(await evaluate(`document.querySelector('#importPreview tbody tr').cells[3].textContent`),'/prəˈvaɪd/');
    await evaluate(`document.getElementById('applyImportBtn').click()`);
    await wait(`document.getElementById('importMessage').textContent.startsWith('Đã nhập 2 từ; bỏ qua 1 cặp trùng.')`);
  }
  const imported=(await api('/api/vocabulary?search=provide')).items[0];
  assert.equal(imported.english,'provide');assert.equal(imported.part_of_speech,'v');assert.equal(imported.phonetic,'/prəˈvaɪd/');
  const simple=(await api('/api/vocabulary?search=afternoon')).items[0];
  assert.equal(simple.part_of_speech,'');assert.equal(simple.phonetic,'');
  const backup=await api('/api/backup');
  assert.equal(backup.version,4);assert.equal(backup.vocabulary.length,19);
  assert.equal(backup.vocabulary.find(w=>w.english==='provide').phonetic,'/prəˈvaɪd/');
  assert.ok(backup.learning.sessions.some(s=>s.mode==='flashcard'));
  assert.ok(backup.learning.sessions.some(s=>s.mode==='typing'));
  const savedWord=backup.vocabulary.find(w=>w.english==='order');
  assert.equal(savedWord.part_of_speech,'v/n');assert.equal(savedWord.phonetic,'/ˈɔːrdər/');
  const vocabulary=(await api('/api/vocabulary')).items;
  const cards=await evaluate(`[...document.querySelectorAll('#board .card.english')].map(c=>({id:Number(c.dataset.pairId),text:c.textContent}))`);
  for(const card of cards){const w=vocabulary.find(w=>w.id===card.id);const pos=(w.part_of_speech||'').trim().replace(/^\((.*)\)$/u,'$1').trim();assert.equal(card.text,w.english+(pos?' ('+pos+')':''));}
  assert.equal(await evaluate(`document.getElementById('reviewView').textContent.includes('/ˈɔːrdər/') || document.getElementById('historyView').textContent.includes('/ˈɔːrdər/')`),false);
  await evaluate(`document.querySelector('[data-view="vocab"]').click()`);
  assert.equal(await evaluate(`document.querySelector('.vocab-row[data-id="${savedWord.id}"] .word-pos').textContent`),'v/n');
  assert.equal(await evaluate(`document.querySelector('.vocab-row[data-id="${savedWord.id}"] .word-phonetic').textContent`),'/ˈɔːrdər/');
  assert.equal((await fetch(origin+'/server.py',{headers:{'X-English-Match-Desktop':token}})).status,404);
  const speech=await evaluate(`({supported:'speechSynthesis' in window,englishVoices:window.speechSynthesis?.getVoices().filter(v=>/^en(?:-|_|$)/i.test(v.lang)).length||0})`);
  assert.equal(speech.supported,true);
  // Verify the new assets inside the real native bundle and across app restarts.
  await evaluate(`document.querySelector('[data-view="grammar"]').click()`);
  await wait(`document.querySelectorAll('.grammar-chapter').length===26`);
  const catalog=await api('/api/grammar/catalog');
  assert.equal(catalog.chapters.reduce((n,c)=>n+c.sections.length,0),295);
  if(stage==='create'){
    await evaluate(`document.getElementById('grammarComplete').click();document.getElementById('grammarBookmark').click()`);
    await flush();
  }
  const grammar=(await api('/api/grammar/progress')).item;
  assert.ok(grammar.completed.includes('1.1'));assert.ok(grammar.bookmarks.includes('1.1'));
  assert.equal(await evaluate(`document.getElementById('grammarComplete').getAttribute('aria-pressed')`),'true');
  if(stage!=='create'){
    const selected=await evaluate(`(async()=>{
      const request=async(url,data,method='POST')=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!r.ok)throw new Error(await r.text());return r.json()};
      const a=(await request('/api/lists',{name:'Native list A'})).item.id;
      const b=(await request('/api/lists',{name:'Native list B'})).item.id;
      await request('/api/vocabulary/${savedWord.id}',{list_id:a},'PUT');
      await request('/api/vocabulary/${imported.id}',{list_id:b},'PUT');
      return [a,b].join(',');
    })()`);
    // Reload fetches changed vocabulary and proves the selector works with packaged JS.
    await new Promise(resolve=>{wc.once('did-finish-load',resolve);wc.reload();});
    await wait(`window.Study && document.querySelectorAll('#board .card').length && !document.getElementById('startReviewBtn').disabled`);
    await evaluate(`window.confirm=()=>true;ListScope.set('gameListSelect',${JSON.stringify(selected)});document.getElementById('gameListSelect').dispatchEvent(new Event('change'))`);
    await flush();
    const round=(await api('/api/progress')).item;assert.equal(round.scope,selected);assert.equal(round.words.length,2);
    const labels=await evaluate(`[...document.querySelectorAll('#board .card.english')].map(c=>c.textContent).sort()`);
    assert.deepEqual(labels,['order (v/n)','provide (v)']);
    await evaluate(`document.querySelector('[data-view="review"]').click();ListScope.set('reviewScope',${JSON.stringify(selected)});document.getElementById('reviewWrongOnly').checked=false;document.getElementById('reviewMode').value='flashcard';document.getElementById('startReviewBtn').click()`);
    await wait(`document.querySelector('#flashCard .study-pos')`);await flush();
    assert.equal((await api('/api/review/progress')).item.words.length,2);
    await evaluate(`document.querySelector('[data-view="vocab"]').click();ListScope.set('manageListFilter',${JSON.stringify(selected)});document.getElementById('manageListFilter').dispatchEvent(new Event('change'))`);
    assert.equal(await evaluate(`document.querySelectorAll('#vocabList .vocab-row').length`),2);
  }
  const image=await wc.capturePage(),out=process.env.EM_SMOKE_OUTPUT;
  if(out){fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,stage+'.png'),image.toPNG());fs.writeFileSync(path.join(out,stage+'.json'),JSON.stringify({ok:true,version:'1.4.0',platform:process.platform,arch:process.arch,stage,words:19,matched:1,wordDetails:true,flexibleImport:true,matchingPartOfSpeech:true,flashcard:true,typing:true,wrongReview:true,history:true,speech,dataDir},null,2));}
  console.log('NATIVE_DESKTOP_SMOKE_OK '+process.platform+' '+process.arch+' '+stage+' flashcard typing wrong-review history');
  await quit();
};
