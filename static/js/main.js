/* ============================================================
   AI Interview Agent · 公共脚本（第二阶段：接入 Flask 后端）
   - Toast
   - 数字滚动动画（hero 统计）
   - 首页面试配置（岗位 / 难度）选择逻辑
   - 开始面试 → POST /api/interview/start → 跳转面试页
   - 面试流程固定为 3 道主问题 + 每题最多 1 次追问（由后端 Python 控制）
   TODO(phase3): 报告页接入 /api/report 数据
   ============================================================ */
(function () {
  "use strict";

  window.formatInterviewTime = function (iso) {
    if (!iso) return '时间未知';
    var text = String(iso);
    if (!/(Z|[+-]\d{2}:\d{2})$/.test(text)) text += '+09:00';
    var date = new Date(text);
    if (!Number.isFinite(date.getTime())) return '时间未知';
    return new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(date) + '（北京时间）';
  };
  window.showError = function (message) {
    var notice = document.getElementById('appNotice');
    if (!notice) {
      notice = document.createElement('div'); notice.id = 'appNotice'; notice.className = 'app-notice'; notice.setAttribute('role','alert');
      var text = document.createElement('p'); text.className = 'app-notice-text'; notice.appendChild(text);
      var close = document.createElement('button'); close.type='button'; close.textContent='关闭提示';
      close.addEventListener('click', function () { notice.hidden=true; }); notice.appendChild(close); document.body.appendChild(notice);
    }
    notice.querySelector('p').textContent = message; notice.hidden = false;
  };

  /* ---------- Toast ---------- */
  var toastEl = null;
  var toastTimer = null;
  window.showToast = function (msg) {
    if (!toastEl) {
      toastEl = document.getElementById("toast");
      if (!toastEl) {
        toastEl = document.createElement("div");
        toastEl.className = "toast";
        document.body.appendChild(toastEl);
      }
    }
    toastEl.setAttribute('role','status');
    toastEl.textContent = msg;
    toastEl.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      toastEl.classList.remove("is-visible");
    }, 2800);
  };

  /* ---------- 数字滚动 ---------- */
  function animateCount(el) {
    var target = parseFloat(el.getAttribute("data-count")) || 0;
    var suffix = el.getAttribute("data-suffix") || "";
    var decimals = parseInt(el.getAttribute("data-decimal") || "0", 10);
    var start = null;
    var dur = 1400;
    function tick(ts) {
      if (!start) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      var cur = target * eased;
      el.textContent = (decimals > 0 ? cur.toFixed(decimals) : Math.round(cur)) + suffix;
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }
  document.querySelectorAll("[data-count]").forEach(function (el) {
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            animateCount(e.target);
            io.unobserve(e.target);
          }
        });
      }, { threshold: 0.4 });
      io.observe(el);
    } else {
      animateCount(el);
    }
  });

  /* ---------- 首页配置逻辑 ---------- */
  var jobGrid = document.getElementById("jobGrid");
  var levelRow = document.getElementById("levelRow");
  var startBtn = document.getElementById("startBtn");
  var summaryText = document.getElementById("summaryText");

  if (!jobGrid || !levelRow || !startBtn) return; // 非首页直接退出

  var catalogNode = document.getElementById('interviewCatalog');
  var catalog;
  try { catalog = JSON.parse(catalogNode.textContent); }
  catch (error) { showError('专业目录暂未加载，请刷新页面后重试'); return; }
  var state = {mode:'major', discipline:null, major_id:null, job:null, level:'实习入门'};
  var disciplineGrid = document.getElementById('disciplineGrid');
  var majorPath = document.getElementById('majorPath');
  var majorSelect = document.getElementById('majorSelect');
  var majorSearch = document.getElementById('majorSearch');
  var renderedRoleKey = null;
  function findMajor(id) {
    var result = null;
    catalog.disciplines.forEach(function (d) {
      d.majors.forEach(function (m) { if (m.id === id) result = {major:m,discipline:d}; });
    });
    return result;
  }
  catalog.disciplines.forEach(function (discipline) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'discipline-option';
    button.setAttribute('data-discipline', discipline.id);
    button.setAttribute('aria-pressed', 'false');
    var title = document.createElement('div'); title.className = 'discipline-title';
    var name = document.createElement('b'); name.textContent = discipline.name;
    var count = document.createElement('small'); count.textContent = discipline.majors.length + ' 个专业';
    title.appendChild(name); title.appendChild(count);
    var description = document.createElement('p'); description.textContent = discipline.description;
    button.appendChild(title); button.appendChild(description); disciplineGrid.appendChild(button);
  });
  var starting = false;
  var defaultStartHTML = startBtn.innerHTML;
  var backgroundEnabled = document.getElementById('backgroundEnabled');
  var backgroundConsent = document.getElementById('backgroundConsent');
  var backgroundFields = document.getElementById('backgroundFields');
  var backgroundInputs = {major:'bgMajor',stage:'bgStage',skills:'bgSkills',projects:'bgProjects',
    internships:'bgInternships',focus:'bgFocus',resume_text:'bgResume'};
  function clearBackground() {
    Object.keys(backgroundInputs).forEach(function (key) { document.getElementById(backgroundInputs[key]).value = ''; });
    backgroundConsent.checked = false;
    backgroundEnabled.checked = false;
    backgroundFields.classList.add('is-hidden');
  }
  clearBackground();
  backgroundEnabled.addEventListener('change', function () {
    if (!this.checked) clearBackground();
    else backgroundFields.classList.remove('is-hidden');
  });
  document.getElementById('clearBackgroundBtn').addEventListener('click', clearBackground);
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) {
      clearBackground();
      starting = false;
      startBtn.innerHTML = defaultStartHTML;
      syncUI();
    }
  });

  // Only non-identifying practice choices are restored; optional background remains transient.
  try {
    var saved = JSON.parse(localStorage.getItem('iv-config') || 'null');
    if (saved && saved.job && saved.level) {
      var restored = findMajor(saved.major_id);
      if (restored && restored.major.roles.indexOf(saved.job) !== -1) {
        state.mode = 'major'; state.major_id = saved.major_id;
        state.discipline = restored.discipline.id; state.job = saved.job;
      } else if (catalog.featured_jobs.indexOf(saved.job) !== -1) {
        state.mode = 'direct'; state.job = saved.job;
      }
      if (['实习入门','校招标准','社招进阶','大厂冲刺'].indexOf(saved.level) !== -1) state.level = saved.level;
    }
  } catch (error) {}

  function renderMajorOptions() {
    var discipline = catalog.disciplines.find(function (d) { return d.id === state.discipline; });
    majorSelect.textContent = '';
    var placeholder = document.createElement('option'); placeholder.value = '';
    placeholder.textContent = discipline ? '请选择一个专业' : '请先选择学科';
    majorSelect.appendChild(placeholder);
    majorSelect.disabled = !discipline;
    majorSearch.disabled = !discipline;
    if (!discipline) return;
    var query = majorSearch.value.trim();
    var groups = {};
    var matches = discipline.majors.filter(function (m) { return !query || m.name.indexOf(query) !== -1 || m.college.indexOf(query) !== -1; });
    if (!matches.length) placeholder.textContent = '没有匹配的专业，请调整筛选词';
    matches.forEach(function (m) {
      if (!groups[m.college]) {
        groups[m.college] = document.createElement('optgroup');
        groups[m.college].label = m.college; majorSelect.appendChild(groups[m.college]);
      }
      var option = document.createElement('option'); option.value = m.id; option.textContent = m.name;
      groups[m.college].appendChild(option);
    });
    majorSelect.value = state.major_id || '';
  }

  function syncUI() {
    var current = findMajor(state.major_id);
    majorSelect.disabled = starting || !state.discipline;
    majorSearch.disabled = starting || !state.discipline;
    document.querySelectorAll('.entry-mode').forEach(function (button) {
      button.disabled = starting;
      var selected = button.dataset.mode === state.mode;
      button.classList.toggle('is-selected',selected); button.setAttribute('aria-pressed',String(selected));
    });
    majorPath.classList.toggle('is-hidden',state.mode !== 'major');
    disciplineGrid.querySelectorAll('.discipline-option').forEach(function (button) {
      button.disabled = starting;
      var selected = button.dataset.discipline === state.discipline;
      button.classList.toggle('is-selected',selected); button.setAttribute('aria-pressed',String(selected));
    });
    var jobs = state.mode === 'direct' ? catalog.featured_jobs : current ? current.major.roles : [];
    var roleKey = state.mode + ':' + (state.major_id || '');
    if (roleKey !== renderedRoleKey) {
      renderedRoleKey = roleKey; jobGrid.textContent = '';
      jobs.forEach(function (job) {
        var button = document.createElement('button'); button.type = 'button'; button.className = 'job-card'; button.dataset.job = job;
        var name = document.createElement('div'); name.className = 'job-name'; name.textContent = job;
        var focus = document.createElement('p'); focus.className = 'job-focus'; focus.textContent = catalog.role_focus[job] || '';
        button.appendChild(name); button.appendChild(focus); jobGrid.appendChild(button);
      });
    }
    jobGrid.querySelectorAll('.job-card').forEach(function (button) {
      button.disabled = starting;
      var selected = button.dataset.job === state.job;
      button.classList.toggle('is-selected',selected); button.setAttribute('aria-pressed',String(selected));
    });
    levelRow.querySelectorAll('.seg').forEach(function (button) {
      var selected = button.dataset.level === state.level;
      button.classList.toggle('is-selected',selected); button.setAttribute('aria-pressed',String(selected));
    });
    document.getElementById('roleHeading').textContent = state.mode === 'direct' ? '选择目标岗位' : '最后选岗位';
    document.getElementById('roleHint').textContent = state.mode === 'direct' ? '沿用原有快捷岗位入口。' : current ? '推荐练习方向，可随时切换专业。' : '先选专业，查看推荐方向。';
    document.getElementById('majorHelp').textContent = current
      ? current.major.college + ' · ' + current.major.name + '。按练习兴趣选择，不限定你的真实专业。'
        + (current.major.language_track ? '当前使用中文问答，侧重岗位知识与情境分析。' : '')
      : '选择的是本次练习方向，不限定你的真实专业；可以自由切换。';
    var path = state.mode === 'major' && current ? current.discipline.name + ' / ' + current.major.name : '直接选岗位';
    document.getElementById('pathLabel').textContent = state.job ? path + ' / ' + state.job : current ? path + ' / 待选岗位' : '请选择一个练习方向';
    document.getElementById('roleFocus').textContent = state.job ? '重点练习：' + catalog.role_focus[state.job] : '选择岗位后，这里会显示本场的重点练习内容。';
    var ready = !!(state.job && state.level && jobs.indexOf(state.job) !== -1);
    startBtn.disabled = !ready || starting;
    summaryText.textContent = ready ? path + ' · ' + state.job + ' · ' + state.level
      : state.mode === 'major' ? '请选择学科、专业和推荐岗位' : '请选择一个目标岗位';
  }

  document.querySelectorAll('.entry-mode').forEach(function (button) {
    button.addEventListener('click',function () {
      if (starting || state.mode === button.dataset.mode) return;
      state.mode = button.dataset.mode; state.discipline = null; state.major_id = null; state.job = null;
      majorSearch.value = ''; renderMajorOptions(); syncUI();
    });
  });
  disciplineGrid.addEventListener('click',function (event) {
    var button = event.target.closest('.discipline-option'); if (!button || starting) return;
    state.discipline = button.dataset.discipline; state.major_id = null; state.job = null;
    majorSearch.value = ''; renderMajorOptions(); syncUI();
  });
  majorSelect.addEventListener('change',function () { if (starting) return; state.major_id = this.value || null; state.job = null; syncUI(); });
  majorSearch.addEventListener('input',function () { if (starting) return; state.major_id = null; state.job = null; renderMajorOptions(); syncUI(); });
  jobGrid.addEventListener('click',function (event) {
    var button = event.target.closest('.job-card'); if (!button || starting) return;
    state.job = button.dataset.job; syncUI();
  });
  levelRow.querySelectorAll('.seg').forEach(function (button) {
    button.setAttribute('role','button'); button.setAttribute('tabindex','0');
    button.addEventListener('keydown',function (event) { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); button.click(); } });
  });
  levelRow.addEventListener('click',function (event) {
    var button = event.target.closest('.seg'); if (!button || starting) return;
    state.level = button.dataset.level; syncUI();
  });
  renderMajorOptions();

  startBtn.addEventListener("click", function () {
    if (starting) return;
    if (!state.job || !state.level) {
      showToast("请先选择岗位与难度");
      return;
    }
    var payload = {job: state.job, level: state.level};
    if (state.mode === 'major' && state.major_id) payload.major_id = state.major_id;
    if (backgroundEnabled.checked) {
      var background = {};
      Object.keys(backgroundInputs).forEach(function (key) {
        var value = document.getElementById(backgroundInputs[key]).value.trim();
        if (value) background[key] = value;
      });
      if (Object.keys(background).length) {
        if (!backgroundConsent.checked) { showToast('请确认背景信息使用说明，或点击清空背景并跳过'); return; }
        payload.background = background;
        payload.background_consent = true;
      }
    }
    if(window.Account && Account.profileConsent) payload.profile_consent=Account.profileConsent();
    starting = true;
    syncUI();
    var original = startBtn.innerHTML;
    startBtn.disabled = true;
    startBtn.innerHTML = "正在生成首题…";

    var startController = window.AbortController ? new AbortController() : null;
    var startTimer = setTimeout(function(){if(startController)startController.abort();},90000);
    fetch("/api/interview/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: startController ? startController.signal : undefined
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (r) {
        if (!r.ok) {
          showError(r.data && r.data.error ? r.data.error : "面试启动失败（" + r.status + "），请稍后重试");
          starting = false;
          syncUI();
          startBtn.innerHTML = original;
          return;
        }
        // 保存会话与配置，供面试页读取
        try {
          if(window.Account && !Account.ownsPage())throw new Error("账户已切换，请刷新页面");
          localStorage.setItem("iv-config", JSON.stringify({ job: r.data.job, level: r.data.level, major_id: r.data.selection && r.data.selection.major_id || null }));
          localStorage.setItem("iv-session", JSON.stringify({
            session_id: r.data.session_id,
            job: r.data.job,
            level: r.data.level,
            question: r.data.question,
            progress: r.data.progress,
            selection: r.data.selection || {},
            question_sequence: r.data.question_sequence || 1,
            background_active: !!r.data.background_active
          }));
        } catch (e) {
          showError('本场面试已保存，但浏览器未能保存进入信息。请允许本站存储后，从历史记录继续，避免重复开始。');
          starting=false;syncUI();startBtn.innerHTML=original;return;
        }
        clearBackground();
        window.location.href = "/interview";
      })
      .catch(function (error) {
        showError(error.name==="AbortError" ? "首题等待超时。请先在历史记录核对是否已有练习，再重试；当前选择仍保留。" : "连接暂时中断。请先在历史记录核对已保存练习，再重试；当前选择仍保留。");
        starting = false;
        syncUI();
        startBtn.innerHTML = original;
      }).finally(function(){clearTimeout(startTimer);});
  });

  syncUI();
})();
