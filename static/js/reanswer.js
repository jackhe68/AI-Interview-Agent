(function(){
 'use strict';
 var dialog=document.createElement('dialog');dialog.className='account-dialog';
 dialog.innerHTML='<form id="reanswerForm"><h2>重答练习</h2><p>仅保存练习稿，不调用AI、不重新评分。原回答和原报告保持不变。</p><h3>原问题</h3><p id="reanswerQuestion"></p><h3>原回答</h3><blockquote id="reanswerOriginal"></blockquote><label>你的重答 *<textarea id="reanswerText" required maxlength="4000" rows="7" style="width:100%;font:inherit;padding:12px"></textarea></label><p id="reanswerVersion"></p><div id="reanswerHistory"></div><p id="reanswerStatus" role="status"></p><div class="account-actions"><button class="btn btn--primary" id="saveReanswer">保存练习稿</button><button type="button" class="btn btn--ghost" id="closeReanswer">关闭</button></div></form>';
 document.body.appendChild(dialog);
 var sid=new URLSearchParams(location.search).get('id')||new URLSearchParams(location.search).get('sid'),sequence=null,key=null;
 if(!sid){try{sid=JSON.parse(localStorage.getItem('iv-session')).session_id;}catch(e){}}
 function status(text){document.getElementById('reanswerStatus').textContent=text;}
 function load(){
  return fetch('/api/interview/'+encodeURIComponent(sid)+'/reanswers',{cache:'no-store'}).then(function(res){return res.json().then(function(data){if(!res.ok)throw new Error(data.error);return data;});}).then(function(data){
   var original=data.questions.find(function(q){return q.answer_sequence===sequence;});if(!original)throw new Error('未找到本题原回答');
   document.getElementById('reanswerQuestion').textContent=original.question;document.getElementById('reanswerOriginal').textContent=original.answer;
   var history=document.getElementById('reanswerHistory');history.textContent='';
   data.items.filter(function(item){return item.answer_sequence===sequence;}).forEach(function(item){var box=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('p');summary.textContent='已保存重答 · '+formatInterviewTime(item.created_at);text.textContent=item.answer;box.append(summary,text);history.appendChild(box);document.getElementById('reanswerVersion').textContent='原评分版本：'+item.scoring_version+'；本次重答未评分。';});
  });
 }
 document.addEventListener('click',function(event){var button=event.target.closest('.reanswer-open');if(!button)return;sequence=Number(button.dataset.sequence);key=null;document.getElementById('reanswerText').value='';status('正在读取原回答…');dialog.showModal();load().then(function(){status('可以填写并保存重答。');document.getElementById('reanswerText').focus();}).catch(function(error){status(error.message);});});
 document.getElementById('closeReanswer').onclick=function(){dialog.close();};
 document.getElementById('reanswerForm').onsubmit=function(event){
  event.preventDefault();var text=document.getElementById('reanswerText').value.trim();if(!text){status('请输入重答内容');return;}
  if(!key)key=Array.from(crypto.getRandomValues(new Uint8Array(16)),function(n){return n.toString(16).padStart(2,'0');}).join('');
  var button=document.getElementById('saveReanswer');button.disabled=true;status('正在保存…');
  fetch('/api/interview/'+encodeURIComponent(sid)+'/reanswers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answer_sequence:sequence,answer:text,request_id:key})})
   .then(function(res){return res.json().then(function(data){if(!res.ok)throw new Error(data.error);return data;});}).then(function(){key=null;return load();}).then(function(){status('重答已保存；未调用AI，未重新评分。');})
   .catch(function(error){status(error.message==='Failed to fetch'?'保存结果暂未确认，请勿修改内容，点击保存可核对同一次提交。':error.message);}).finally(function(){button.disabled=false;});
 };
})();
