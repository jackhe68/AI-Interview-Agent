(function () {
  'use strict';
  var nav = document.querySelector('.nav__links');
  if (nav) {
    nav.id = 'siteNavigation';
    var toggle = document.createElement('button');
    toggle.type = 'button'; toggle.className = 'nav-toggle'; toggle.textContent = '菜单';
    toggle.setAttribute('aria-controls', nav.id); toggle.setAttribute('aria-expanded', 'false');
    nav.parentNode.insertBefore(toggle, nav);
    function close() { nav.classList.remove('is-open'); toggle.setAttribute('aria-expanded', 'false'); }
    toggle.addEventListener('click', function () {
      var open = toggle.getAttribute('aria-expanded') !== 'true';
      nav.classList.toggle('is-open', open); toggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', function (event) {
      if (!nav.contains(event.target) && event.target !== toggle || event.target.closest('.nav__link')) close();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') { close(); toggle.focus(); }
    });
    nav.addEventListener('focusout', function () { setTimeout(function () { if (!nav.contains(document.activeElement) && document.activeElement !== toggle) close(); }, 0); });
  }

  document.addEventListener('click', function (event) {
    var button = event.target.closest('.resume-interview');
    if (!button || button.disabled) return;
    var sid = button.getAttribute('data-session');
    if (!sid) return;
    button.disabled = true;
    var original = button.textContent;
    button.textContent = '正在恢复…';
    var controller = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) controller.abort(); }, 10000);
    fetch('/api/interview/' + encodeURIComponent(sid) + '/state', controller ? {cache:'no-store',signal:controller.signal} : {cache:'no-store'})
      .then(function (res) { return res.json().then(function (data) { if (!res.ok) throw new Error(data.error || '暂时无法恢复，请稍后重试'); return data; }); })
      .then(function (data) {
        if (data.finished) { location.href = '/report?id=' + encodeURIComponent(sid); return; }
        var old;
        try { old = JSON.parse(localStorage.getItem('iv-session') || 'null'); } catch (e) { old = null; }
        if(window.Account && !Account.ownsPage())throw new Error("账户已切换，请刷新页面");
        var cached = {session_id:sid, job:data.job, level:data.level, selection:data.selection || {},
          question:data.question, question_sequence:data.question_sequence, progress:data.progress,
          answered_count:data.answered_count, background_active:!!data.background_active,
          elapsed_seconds:data.elapsed_seconds || (old && old.session_id===sid ? old.elapsed_seconds : 0)};
        try { localStorage.setItem('iv-session', JSON.stringify(cached)); }
        catch (error) { throw new Error('浏览器暂不能保存恢复信息，请允许本机存储后重试。'); }
        location.href = '/interview';
      })
      .catch(function (error) {
        var status = button.parentNode.querySelector('.resume-error');
        if (!status) { status = document.createElement('p'); status.className = 'resume-error'; status.setAttribute('role','status'); button.parentNode.appendChild(status); }
        status.textContent = error.name === 'AbortError' ? '恢复等待超时，原面试和草稿仍保留，请重试。' : error.message || '网络暂时中断，请重试。';
      })
      .finally(function () { clearTimeout(timer); button.disabled = false; button.textContent = original; });
  });

  var banner = document.getElementById('resumeBanner');
  if (banner) {
    fetch('/api/interviews', {cache:'no-store'})
      .then(function (res) { if (!res.ok) throw new Error(); return res.json(); })
      .then(function (data) {
        var item = (data.items || []).find(function (row) { return row.status === 'active'; });
        if (!item) return;
        document.getElementById('resumeSummary').textContent = '你有一场未完成的面试：' + item.job + ' · ' + item.difficulty;
        document.getElementById('resumeLatest').setAttribute('data-session', item.id);
        banner.hidden = false;
      }).catch(function () { /* The history page remains available if this optional hint fails. */ });
  }
})();
