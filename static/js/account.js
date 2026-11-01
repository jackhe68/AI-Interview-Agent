(function () {
 'use strict';
 var originalFetch=window.fetch.bind(window),state=null,scope=null;
 var Account=window.Account={csrf:'',scope:null,state:null};
 function clearPrivate() {
  try { Object.keys(localStorage).filter(function(k){return /^iv-(session|config|answer-draft)/.test(k);}).forEach(function(k){localStorage.removeItem(k);}); } catch(e){}
 }
 function accept(data) {
  state=Account.state=data;Account.csrf=data.csrf_token;Account.scope=data.scope;
  try {
   var old=localStorage.getItem('iv-identity');
   if (data.scope!=='legacy') localStorage.setItem('iv-identity',data.scope);
   if (data.scope!=='legacy' && old && old!==data.scope) clearPrivate();
  } catch(e){}
  scope=data.scope;
  document.dispatchEvent(new CustomEvent('account-ready',{detail:data}));
  return data;
 }
 Account.refresh=function(){return originalFetch('/api/account/session',{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('账户状态暂不可用，请刷新页面');return r.json();}).then(accept);};
 Account.ready=Account.refresh();
 // No mutation is dispatched before the identity and synchronizer token are known.
 window.fetch=function(input,options){
  return Account.ready.then(function(){
   var req=new Request(input,options),url=new URL(req.url,location.href);
   if(url.origin===location.origin && url.pathname.startsWith('/api/')){
    var headers=new Headers(req.headers);headers.set('X-CSRF-Token',Account.csrf);
    req=new Request(req,{headers:headers});
   }
   return originalFetch(req);
  });
 };
 Account.ownsPage=function(){try{return !Account.transitioning && (Account.scope==='legacy'||localStorage.getItem('iv-identity')===Account.scope);}catch(e){return false;}};
 Account.clearPrivate=clearPrivate;
 Account.changed=function(){Account.transitioning=true;clearPrivate();try{localStorage.setItem('iv-identity','switching:'+Date.now());}catch(e){}return Account.refresh().finally(function(){Account.transitioning=false;});};
 window.addEventListener('storage',function(event){if(event.key==='iv-identity'&&event.newValue!==scope&&scope!=='legacy'&&!Account.transitioning){document.body.style.visibility='hidden';location.replace('/');}});
 window.addEventListener('pageshow',function(event){if(event.persisted){document.body.style.visibility='hidden';Account.refresh().then(function(){location.reload();}).catch(function(){location.replace('/');});}});
 document.addEventListener('account-ready',function(event){
  var nav=document.querySelector('.nav__links');if(!nav)return;
  var link=document.getElementById('accountNavLink');if(!link){link=document.createElement('a');link.id='accountNavLink';link.className='nav__link';link.href='/account';nav.appendChild(link);}
  link.classList.toggle('is-active',location.pathname==='/account');
  link.textContent=event.detail.user ? event.detail.user.nickname+' · 个人中心':'登录 / 注册';
 });
 Account.ready.then(function(data){
  var banner=document.createElement('p');banner.className='identity-note';
  banner.textContent=data.user ? '练习记录保存在你的账户中。':'游客试用：记录仅能用原浏览器和当前网址访问。注册或登录后，可确认保存到个人账户。';
  if(['/','/history'].includes(location.pathname)){var main=document.querySelector('main');if(main)main.insertBefore(banner,main.firstChild);}
  var start=document.getElementById('startBtn');
  if(start && data.scope!=='legacy'){
   var dialog=document.createElement('dialog');dialog.className='account-dialog';dialog.innerHTML='<form method="dialog"><h2>确认本场练习</h2><p id="practiceConfirmation"></p><p id="profilePreview"></p><label id="profileConsentLabel"><input type="checkbox" id="profileConsent"> 本场允许使用账户专业、年级辅助出题（不发送称呼，不用于直接评分）</label><p>本场填写的背景另行征求同意，可清空并跳过。</p><div class="account-actions"><button value="cancel" class="btn btn--ghost">返回修改</button><button value="confirm" class="btn btn--primary">确认开始</button></div></form>';document.body.appendChild(dialog);
   var accepted=false;
   start.addEventListener('click',function(event){
    if(accepted){accepted=false;return;}
    event.preventDefault();event.stopImmediatePropagation();
    start.disabled=true;
    Account.refresh().then(function(fresh){
     data=fresh;document.getElementById('profileConsent').checked=false;
    document.getElementById('practiceConfirmation').textContent=document.getElementById('summaryText').textContent;
    document.getElementById('profilePreview').textContent=data.user ? '账户资料（默认不用于本场出题）：专业 '+data.user.major+'；学习阶段：'+data.user.grade_label:'未使用账户资料，按所选岗位和难度进行标准练习。';
    document.getElementById('profileConsentLabel').hidden=!data.user;
    dialog.showModal();
    }).catch(function(){var error=document.getElementById('startConfirmationError');if(!error){error=document.createElement('p');error.id='startConfirmationError';error.setAttribute('role','alert');start.parentNode.appendChild(error);}error.textContent='暂时无法核对本场资料，请联网后重试。';}).finally(function(){start.disabled=false;});
   },true);
   dialog.addEventListener('close',function(){if(dialog.returnValue==='confirm'){accepted=true;start.click();}});
   Account.profileConsent=function(){return !!data.user&&document.getElementById('profileConsent').checked;};
  }
 }).catch(function(){var box=document.createElement('p');box.className='resume-error';box.setAttribute('role','alert');box.textContent='无法核对账户状态，请刷新页面后继续。';document.body.prepend(box);});
})();
