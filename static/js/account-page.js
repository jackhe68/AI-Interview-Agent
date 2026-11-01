(function(){
 'use strict';
 var status=document.getElementById('accountStatus');
 function message(text,error){status.textContent=text;status.classList.toggle('is-error',!!error);}
 function formData(form){var data=Object.fromEntries(new FormData(form));if(form.id==='passwordForm')data.revoke_others=form.elements.revoke_others.checked;return data;}
 function fillCatalog(form,data){
  var major=form.elements.major_id,grade=form.elements.grade;
  if(!major)return;
  major.innerHTML='';grade.innerHTML='';
  [{id:'',name:'请选择专业'}].concat(data.majors,[{id:'other',name:'其他'}]).forEach(function(m){var option=new Option(m.name,m.id);major.add(option);});
  grade.add(new Option('请选择学习阶段',''));Object.keys(data.grades).forEach(function(key){grade.add(new Option(data.grades[key],key));});
  function other(){var visible=major.value==='other';form.querySelector('.other-major').hidden=!visible;form.elements.other_major.required=visible;}
  major.addEventListener('change',other);other();form.updateOther=other;
 }
 function render(data){
  document.getElementById('anonymousAccount').hidden=!!data.user;document.getElementById('signedAccount').hidden=!data.user;
  if(!data.user)return;
  var form=document.getElementById('profileForm');
  ['nickname','major_id','other_major','grade'].forEach(function(key){form.elements[key].value=data.user[key]||'';});form.updateOther();
  document.getElementById('profileUsername').textContent='登录用户名：'+data.user.username;
  document.getElementById('welcomeUser').textContent=data.user.nickname+'的个人资料';
  document.getElementById('claimSection').hidden=!data.guest_count;
  document.getElementById('claimCount').textContent='本浏览器有 '+data.guest_count+' 场未绑定账户的游客练习。';
 }
 function submit(id,path,method,success){
  var form=document.getElementById(id);
  var localStatus=document.createElement('p');localStatus.setAttribute('role','status');localStatus.className='account-status';form.appendChild(localStatus);
  form.addEventListener('submit',function(event){
   event.preventDefault();if(!form.reportValidity())return;
   var data=formData(form),button=form.querySelector('button'),original=button.textContent;
   form.querySelectorAll('[data-error]').forEach(function(node){node.textContent='';});form.querySelectorAll('[aria-invalid]').forEach(function(node){node.removeAttribute('aria-invalid');});
   if(data.confirm_password!==undefined&&data.password!==data.confirm_password){form.querySelector('[data-error="confirm_password"]').textContent='两次输入的密码不一致';message('请检查确认密码',true);return;}
   button.disabled=true;button.textContent='正在提交…';message('正在保存，请稍候…');localStatus.textContent='正在保存，请稍候…';
   fetch(path,{method:method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
    .then(function(res){return res.json().then(function(body){if(!res.ok){Object.keys(body.fields||{}).forEach(function(key){var node=form.querySelector('[data-error="'+key+'"]');if(node){node.textContent=body.fields[key];var input=form.elements[key];if(input){input.setAttribute('aria-invalid','true');node.id=id+'-'+key+'-error';input.setAttribute('aria-describedby',node.id);}}});throw new Error(body.error||'暂时无法提交，请重试');}return body;});})
    .then(function(body){return Promise.resolve(success(body)).then(function(){localStatus.textContent='提交成功。';});}).catch(function(error){localStatus.textContent=error.message==='Failed to fetch'?'网络暂时中断，请重试。':error.message;message(error.message==='Failed to fetch'?'网络暂时中断，请重试。':error.message,true);})
    .finally(function(){button.disabled=false;button.textContent=original;});
  });
 }
 Account.ready.then(function(data){
  fillCatalog(document.getElementById('registerForm'),data);fillCatalog(document.getElementById('profileForm'),data);render(data);
  submit('registerForm','/api/account/register','POST',function(){document.getElementById('registerForm').reset();return Account.changed().then(function(fresh){render(fresh);message('注册成功，已登录。游客记录需要另行确认迁移。');});});
  submit('loginForm','/api/account/login','POST',function(){document.getElementById('loginForm').reset();return Account.changed().then(function(fresh){render(fresh);message('登录成功。');});});
  submit('profileForm','/api/account/profile','PATCH',function(){return Account.refresh().then(function(fresh){render(fresh);message('资料已保存；历史报告不会随资料修改而改变。');});});
  submit('passwordForm','/api/account/password','POST',function(){return Account.refresh().then(function(){document.getElementById('passwordForm').reset();message('密码已更新，当前登录会话已轮换。');});});
  submit('deleteForm','/api/account','DELETE',function(){return Account.changed().then(function(){location.replace('/account');});});
 }).catch(function(){message('账户状态无法加载，请刷新页面重试。',true);});
 document.getElementById('showLogin').onclick=function(){document.getElementById('loginForm').hidden=false;document.getElementById('registerForm').hidden=true;};
 document.getElementById('showRegister').onclick=function(){document.getElementById('loginForm').hidden=true;document.getElementById('registerForm').hidden=false;};
 document.getElementById('logoutButton').onclick=function(){var button=this;button.disabled=true;fetch('/api/account/logout',{method:'POST'}).then(function(res){if(!res.ok)throw new Error('退出未确认，请重试');return Account.changed();}).then(function(){location.replace('/');}).catch(function(error){message(error.message,true);button.disabled=false;});};
 document.getElementById('claimButton').onclick=function(){
  if(!document.getElementById('claimConfirm').checked){message('请先确认将本浏览器游客记录保存到当前账户。',true);return;}
  var button=this;button.disabled=true;
  fetch('/api/account/claim-guests',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(function(res){return res.json().then(function(data){if(!res.ok)throw new Error(data.error);return data;});}).then(function(data){return Account.refresh().then(function(fresh){render(fresh);message('已保存 '+data.migrated+' 场游客练习，可在我的练习与报告中查看。');});}).catch(function(error){message(error.message,true);}).finally(function(){button.disabled=false;});
 };
})();
