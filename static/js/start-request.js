/* Request identifiers are retry metadata, never authentication credentials or background text. */
(function(){
 'use strict';
 function storageKey(){return 'iv-start-request-v1:'+encodeURIComponent(window.Account ? Account.scope : 'legacy');}
 function unavailable(message){var error=new Error(message);error.startPreparation=true;return error;}
 window.InterviewStarts={
  prepare:function(payload){
   var identity=window.Account ? Account.scope : 'legacy';
   return Promise.resolve().then(function(){
    if(window.Account && !Account.ownsPage())throw unavailable('账户状态已改变，请刷新后再开始；尚未发出AI请求。');
    if(!window.crypto || !crypto.subtle)throw unavailable('请使用安全的HTTPS网址或本机地址开始面试。');
    return crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(payload)));
   }).then(function(hash){
    if(window.Account && (!Account.ownsPage() || Account.scope!==identity))throw unavailable('账户状态已改变，请刷新后再开始；尚未发出AI请求。');
    var signature=Array.from(new Uint8Array(hash)).map(function(b){return b.toString(16).padStart(2,'0');}).join('');
    var key=storageKey(),saved;
    try{saved=JSON.parse(localStorage.getItem(key)||'null');}catch(e){saved=null;}
    if(!saved || saved.signature!==signature || !/^[0-9a-f]{32}$/.test(saved.id) || !Number.isFinite(saved.created_at) || Date.now()-saved.created_at>86400000){
     var bytes=new Uint8Array(16);crypto.getRandomValues(bytes);
     saved={id:Array.from(bytes).map(function(b){return b.toString(16).padStart(2,'0');}).join(''),signature:signature,created_at:Date.now()};
    }
    try{localStorage.setItem(key,JSON.stringify(saved));}catch(e){throw unavailable('浏览器暂不能保存进入信息，请允许本站存储后重试；尚未发出AI请求。');}
    return Object.assign({},payload,{request_id:saved.id});
   });
  },
  request:function(payload){
   var controller=window.AbortController ? new AbortController() : null;
   var timer=setTimeout(function(){if(controller)controller.abort();},90000);
   var prepared;
   return InterviewStarts.prepare(payload).then(function(value){
    prepared=value;
    return fetch('/api/interview/start',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify(prepared),signal:controller ? controller.signal : undefined});
   }).then(function(response){return response.json().then(function(data){
    if(response.ok && (!data || typeof data.session_id!=='string' || !data.session_id || typeof data.question!=='string'))
     throw unavailable('服务返回的进入信息不完整，请先从历史记录核对已保存的面试。');
    return {ok:response.ok,status:response.status,data:data,request_id:prepared.request_id};
   });}).finally(function(){clearTimeout(timer);});
  },
  finish:function(id){
   try{var key=storageKey(),saved=JSON.parse(localStorage.getItem(key)||'null');if(saved && saved.id===id)localStorage.removeItem(key);}catch(e){}
  }
 };
})();
