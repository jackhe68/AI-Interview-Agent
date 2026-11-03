/* ============================================================
   AI Interview Agent · 报告页脚本（第三阶段：真实数据联动）
   ------------------------------------------------------------
   - 从 GET /api/report/<session_id> 读取 SQLite 中的真实评分
   - 渲染：综合评分环、4 维加权评分条 / 8 维能力雷达、薄弱知识点、改进建议
   - 语音指标需关联录音；无数据保持未采集，不虚构
   - session_id 来源：URL ?id= 或 localStorage iv-session
   - 保留底部三按钮逻辑（返回首页 / 更换岗位 / 同配置再练）
   ============================================================ */
(function () {
  "use strict";

  /* ---------- 浅色主题图表配色 ---------- */
  var THEME = {
    grid: "rgba(15, 23, 42, 0.07)",
    gridFill: "rgba(15, 23, 42, 0.015)",
    axis: "rgba(15, 23, 42, 0.06)",
    label: "#475569",
    labelDim: "#667085",
    line: "#6254E8",
    lineGlow: "rgba(108, 99, 255, 0.45)",
    pointFill: "#FFFFFF",
    radarFillTop: "rgba(108, 99, 255, 0.22)",
    radarFillBottom: "rgba(139, 92, 246, 0.18)"
  };

  var DIM_LABELS = ["专业知识", "回答完整性", "逻辑表达", "岗位相关性"];
  var DIM_KEYS = ["knowledge", "completeness", "expression", "job_relevance"];
  var DIM_WEIGHTS = ["40%", "30%", "20%", "10%"];

  /* ---------- 获取 session_id ---------- */
  function getSid() {
    var p = new URLSearchParams(location.search);
    var sid = p.get("id") || p.get("sid");
    if (sid) return sid;
    try {
      var s = JSON.parse(localStorage.getItem("iv-session") || "null");
      if (s && s.session_id) return s.session_id;
    } catch (e) {}
    return null;
  }

  /* ---------- DOM ---------- */
  var el = function (id) { return document.getElementById(id); };
  var reportBody = el("reportBody");
  var reportEmpty = el("reportEmpty");
  var emptyTitle = el("emptyTitle");
  var emptyDesc = el("emptyDesc");
  var exportReady = false;
  var exportBusy = false;
  var exportFailed = false;
  var exportSid = null;

  function syncExportButton() {
    var button = el('exportBtn');
    if (!button) return;
    button.disabled = exportBusy || !exportReady;
    button.setAttribute('aria-busy', exportBusy ? 'true' : 'false');
    button.textContent = exportBusy ? '正在生成 PDF…' : exportFailed ? '重试导出 PDF' : '导出 PDF 报告';
  }

  function showEmpty(title, desc) {
    exportReady = false;
    syncExportButton();
    reportBody.classList.add("is-hidden");
    reportEmpty.classList.remove("is-hidden");
    if (title && emptyTitle.textContent !== title) emptyTitle.textContent = title;
    if (desc && emptyDesc.textContent !== desc) emptyDesc.textContent = desc;
  }
  function showBody() {
    reportEmpty.classList.add("is-hidden");
    reportBody.classList.remove("is-hidden");
  }

  /* ---------- 工具 ---------- */
  function fmtDuration(sec) {
    if (sec == null) return "—";
    var m = Math.floor(sec / 60), s = sec % 60;
    return (m < 10 ? "0" + m : m) + ":" + (s < 10 ? "0" + s : s);
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    return window.formatInterviewTime(iso);
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var partialSignature = '';
  function renderPartial(items) {
    if (!Array.isArray(items) || !items.length) return;
    var signature = JSON.stringify(items);
    if (signature !== partialSignature) {
      el('partialReviews').innerHTML = items.map(function (item,index) {
        return '<details class="answer-review"' + (index===0 ? ' open' : '') + '><summary>第 ' + (index+1) + ' 次作答：' + esc(item.question) + '</summary>'
          + '<p class="review-label">你的回答</p><blockquote>' + esc(item.answer) + '</blockquote>'
          + '<p class="review-label">已保存的点评</p><p class="saved-feedback">' + esc(item.comment || '这题未保存点评，可先回看自己的回答。') + '</p></details>';
      }).join('');
      partialSignature = signature;
    }
    el('partialReport').classList.remove('is-hidden');
  }

  /* ---------- 评分环动画 ---------- */
  var RING_CIRC = 2 * Math.PI * 76;
  function animateScore(target) {
    var ringValue = el("ringValue");
    var scoreNum = el("scoreNum");
    scoreNum.parentNode.querySelector('small').hidden=typeof target!=='number';
    if(typeof target!=='number'){scoreNum.textContent='未评分';ringValue.setAttribute('stroke-dashoffset',String(RING_CIRC));return;}
    var start = null, dur = 1500;
    function tick(ts) {
      if (!start) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      var cur = target * eased;
      scoreNum.textContent = Math.round(cur);
      ringValue.setAttribute("stroke-dashoffset", String(RING_CIRC * (1 - cur / 100)));
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  /* ---------- 渲染：头部 meta ---------- */
  function renderMeta(iv) {
    el("reportTitle").textContent = "面试报告";
    var meta = el("reportMeta");
    var html = "";
    html += '<span class="badge">岗位：' + esc(iv.job) + '</span>';
    html += '<span class="badge">难度：' + esc(iv.difficulty) + '</span>';
    if (iv.selection && iv.selection.major) html += '<span class="badge">专业：' + esc(iv.selection.major) + '</span>';
    if(iv.practice_profile && iv.practice_profile.consent) html += '<span class="badge">本场背景：'+esc(iv.practice_profile.major)+' · '+esc(iv.practice_profile.grade)+'</span>';
    html += '<span class="badge">' + fmtDate(iv.started_at) + '</span>';
    if (iv.duration_sec != null) html += '<span class="badge">时长：' + fmtDuration(iv.duration_sec) + '</span>';
    html += iv.coverage ? '<span class="badge">有效作答：'+esc(iv.coverage.effective_answers)+' 次 · 跳过：'+esc(iv.coverage.skipped)+' 次</span>'
      : '<span class="badge">答题：' + iv.answered_count + ' 次</span>';
    html += '<span class="badge">状态：' + (iv.status === "ended" ? "提前结束" : "已完成") + '</span>';
    meta.innerHTML = html;
  }

  /* ---------- 渲染：维度条 ---------- */
  function renderScoreSub(scores) {
    var sub = el("scoreSub");
    var html = "";
    DIM_KEYS.forEach(function (k, i) {
      var v = scores[k];
      html += '<div class="score-sub__item">'
        + '<div class="row"><span>' + DIM_LABELS[i] + ' <small style="color:var(--text-3)">权重 ' + DIM_WEIGHTS[i] + '</small></span><b>' + (typeof v==='number'?v:'未评估') + '</b></div>'
        + '<div class="track"><div class="fill" data-w="' + (typeof v==='number'?v:0) + '"></div></div>'
        + '</div>';
    });
    sub.innerHTML = html;
    // 触发条形动画
    setTimeout(function () {
      sub.querySelectorAll(".fill").forEach(function (f, i) {
        setTimeout(function () { f.style.width = f.getAttribute("data-w") + "%"; }, 120 + i * 100);
      });
    }, 200);
  }

  /* ---------- 渲染：总评 ---------- */
  function renderComment(data) {
    var box = el("reportComment");
    el("commentHead").textContent = data.knowledge_summary || "";
    el("commentBody").textContent = data.overall_comment || "";
    var note = el("confidenceNote");
    if (data.confidence_note) {
      note.textContent = data.confidence_note;
      note.classList.remove("is-hidden");
    } else {
      note.classList.add("is-hidden");
    }
    box.classList.remove("is-hidden");
  }

  /* ---------- 渲染：薄弱知识点 ---------- */
  function renderWeaknesses(weaknesses,unassessed) {
    var list = el("weakList");
    var tags = el("weakTags");
    if (!weaknesses || !weaknesses.length) {
      list.innerHTML = '<div class="pace-empty">'+(unassessed ? '本场依据不足，暂不能判断薄弱项；可补充回答后继续练习。' : '本场已回答内容中暂无可核对的薄弱项，不代表未考察能力都已掌握。')+'</div>';
      tags.innerHTML = "";
      return;
    }
    var html = "";
    weaknesses.forEach(function (w) {
      var pct = w.score;
      html += '<div class="weak-item">'
        + '<div class="row"><span class="name">' + esc(w.topic) + '</span><span class="pct">练习关注项</span></div>'
        + (w.explanation ? '<div style="font-size:12px;color:var(--text-2);margin-top:6px;line-height:1.6;">' + esc(w.explanation) + '</div>' : '')
        + '</div>';
    });
    list.innerHTML = html;
    tags.innerHTML = weaknesses.map(function (w) {
      return '<span class="tag"># ' + esc(w.topic) + '</span>';
    }).join("");
    setTimeout(function () {
      list.querySelectorAll(".fill").forEach(function (f, i) {
        setTimeout(function () { f.style.width = f.getAttribute("data-w") + "%"; }, 200 + i * 120);
      });
    }, 300);
  }

  /* ---------- 渲染：改进建议 ---------- */
  function renderSuggestions(suggestions) {
    var list = el("adviceList");
    if (!suggestions || !suggestions.length) {
      list.innerHTML = '<div class="pace-empty">暂无建议。</div>';
      return;
    }
    var html = "";
    suggestions.forEach(function (s) {
      html += '<div class="advice-item"><div class="no"></div><div><p>' + esc(s) + '</p></div></div>';
    });
    list.innerHTML = html;
  }

  /* ---------- 雷达图 ---------- */
  function setupCanvas(canvas) {
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    var ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    return { ctx: ctx, w: rect.width, h: rect.height };
  }

  var RADAR_KEYS = DIM_KEYS.concat(['problem_analysis', 'practical_application', 'examples', 'reflection']);
  var RADAR_LABELS = DIM_LABELS.concat(['问题分析', '实践应用', '举例论证', '复盘改进']);
  var radarFrame = null;
  var lastDimensions = null;

  function getRadarDimensions(data) {
    var entries = Array.isArray(data.radar_dimensions) ? data.radar_dimensions : [];
    return RADAR_KEYS.map(function (key, i) {
      var found = entries.find(function (entry) { return entry.key === key; });
      var value = found ? found.score : data.scores[key];
      return {key:key, label:RADAR_LABELS[i], score:typeof value === 'number' && isFinite(value) && value >= 0 && value <= 100 ? value : null,
        evidence:found && found.evidence || '', reason:found && found.reason || ''};
    });
  }

  function renderRadarValues(dimensions) {
    var observed = dimensions.filter(function (d) { return d.score !== null; }).length;
    el('radarNote').textContent = '已评估 ' + observed + '/8 项。未评估表示缺少本场回答依据，不记为零分。综合分仍按左侧四项权重计算。';
    el('radarValues').innerHTML = dimensions.map(function (d) {
      return '<div class="radar-value"><div><span>' + esc(d.label) + '</span><b>' + (d.score === null ? '未评估' : d.score + ' / 100') + '</b></div>'
        + (d.evidence || d.reason ? '<details><summary>评分依据</summary><p>' + esc(d.reason) + '</p><p>回答原文：' + esc(d.evidence) + '</p></details>' : '') + '</div>';
    }).join('');
  }

  function renderReviews(reviews) {
    var root = el('reviewList');
    reviews = Array.isArray(reviews) ? reviews : [];
    if (!reviews.length) {
      root.innerHTML = '<p class="practice-intro">本场没有可复盘的作答。</p>';
      return;
    }
    function paragraph(label, value) {
      return value ? '<p class="review-label">' + label + '</p><p>' + esc(value) + '</p>' : '';
    }
    root.innerHTML = reviews.map(function (r, i) {
      var steps = Array.isArray(r.answer_outline) ? r.answer_outline : [];
      var checks = Array.isArray(r.checklist) ? r.checklist : [];
      return '<details class="answer-review"' + (i === 0 ? ' open' : '') + '><summary>第 ' + (i + 1) + ' 次作答：' + esc(r.question) + '</summary>'
        + '<p class="review-label">你的回答</p><blockquote>' + esc(r.answer) + '</blockquote>'
        + paragraph('当时的点评', r.comment)
        + paragraph('做得好的地方', r.strength) + paragraph('需要补齐什么', r.gap)
        + (r.evidence ? '<p>对应回答原文：' + esc(r.evidence) + '</p>' : '')
        + (steps.length ? '<p class="review-label">回答思路</p><ol>' + steps.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ol>' : '')
        + (r.reference_answer ? '<details class="reference-answer"><summary>展开参考回答，与你的回答对照</summary><p>' + esc(r.reference_answer) + '</p></details>' : '<p class="practice-intro">这份报告没有可用的参考回答；历史报告保留原有数据，不补造内容。</p>')
        + paragraph('下一步怎么练', r.practice_task)
        + (checks.length ? '<p class="review-label">重答后自查</p><ul>' + checks.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ul>' : '')
        + '<button type="button" class="btn btn--outline reanswer-open" data-sequence="'+r.answer_sequence+'">保存一次重答练习</button></details>';
    }).join('');
  }

  function drawRadar(dimensions) {
    var canvas = el('radarChart');
    if (!canvas) return;
    if (radarFrame !== null) cancelAnimationFrame(radarFrame);
    lastDimensions = dimensions;
    var setup = setupCanvas(canvas), ctx = setup.ctx, w = setup.w, h = setup.h;
    if (w <= 0 || h <= 0) return;
    var cx = w / 2, cy = h / 2;
    var radius = Math.max(12, Math.min(w, h) / 2 - 72);
    var n = dimensions.length, font = getComputedStyle(document.body).fontFamily;
    var values = dimensions.map(function (d) { return d.score; });
    function point(i, ratio) {
      var angle = -Math.PI / 2 + 2 * Math.PI * i / n;
      return [cx + Math.cos(angle) * radius * ratio, cy + Math.sin(angle) * radius * ratio];
    }
    function polygon(ratio) {
      ctx.beginPath();
      for (var i = 0; i < n; i++) {
        var p = point(i, ratio);
        if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
      }
      ctx.closePath();
    }
    function frame() {
      var eased = 1;
      ctx.clearRect(0, 0, w, h);
      ctx.lineWidth = 1; ctx.strokeStyle = THEME.grid; ctx.fillStyle = THEME.gridFill;
      for (var layer = 1; layer <= 4; layer++) { polygon(layer / 4); ctx.fill(); ctx.stroke(); }
      for (var axis = 0; axis < n; axis++) {
        var edge = point(axis, 1);
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(edge[0], edge[1]); ctx.stroke();
      }
      ctx.lineWidth = 2; ctx.strokeStyle = THEME.line;
      var complete = values.every(function (v) { return v !== null; });
      ctx.beginPath();
      for (var k = 0; k < n; k++) {
        if (values[k] === null) continue;
        var p = point(k, values[k] / 100 * eased);
        if (k === 0 || values[k - 1] === null) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
      }
      if (complete) { ctx.closePath(); ctx.fillStyle = THEME.radarFillTop; ctx.fill(); }
      ctx.stroke();
      for (var m = 0; m < n; m++) {
        if (values[m] === null) continue;
        var dot = point(m, values[m] / 100 * eased);
        ctx.beginPath(); ctx.arc(dot[0], dot[1], 4, 0, Math.PI * 2);
        ctx.fillStyle = THEME.pointFill; ctx.fill(); ctx.stroke();
      }
      // Labels must be redrawn after every clearRect, including the final frame.
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (var t = 0; t < n; t++) {
        var label = point(t, 1.36);
        ctx.font = '11px ' + font; ctx.fillStyle = THEME.label;
        ctx.fillText(dimensions[t].label, label[0], label[1] - 7);
        ctx.font = '11px ' + font; ctx.fillStyle = values[t] === null ? THEME.labelDim : THEME.line;
        ctx.fillText(values[t] === null ? '未评估' : String(values[t]), label[0], label[1] + 10);
      }
      radarFrame = null;
    }
    frame();
  }

  /* 独立展示服务器保存的测量值，绝不使用 AI 返回的数字替换指标。 */
  function renderSpeech(entries) {
    var root = el('speechReport');
    var button = el('speechReviewBtn');
    entries = Array.isArray(entries) ? entries : [];
    el('speechReportBadge').textContent = entries.length ? entries.length + ' 段已关联录音' : '尚未采集';
    button.classList.toggle('is-hidden', !entries.length);
    if (!entries.length) {
      root.innerHTML = '<div class="pace-empty">本场没有已关联的音频分析。历史文字报告仍可正常查看，不会补造语音数值。</div>';
      return;
    }
    function measured(value, unit, digits) {
      return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits == null ? 1 : digits) + (unit || '') : '未采集 / 不适用';
    }
    var spoken = 0, hanzi = 0, chineseSeconds = 0;
    entries.forEach(function (entry) {
      var m = entry.analysis.metrics;
      spoken += m.speech_s || 0;
      if (m.hanzi_per_min_speech != null) { hanzi += m.hanzi_count; chineseSeconds += m.speech_s; }
    });
    var html = '<p>有效语音共 ' + measured(spoken, ' 秒') + '；中文字符速率（按有效语音时间加权）：' + measured(chineseSeconds ? hanzi * 60 / chineseSeconds : null, ' 汉字/分钟') + '。</p>';
    html += '<p>中英文分别计数，共用该段有效语音时长，不把汉字和英文单词直接相加。停顿阈值为半秒，长停顿阈值为一点五秒，均排除首尾静音。</p>';
    var contentLabels = {relevance:'切题程度', knowledge:'专业知识', completeness:'回答完整度', logic:'逻辑结构', repetition:'重复表达', fillers:'口头禅候选'};
    var rows = [
      ['总时长','duration_s','秒'], ['有效语音','speech_s','秒'], ['静音总量（含首尾）','silence_s','秒'],
      ['中文速率（有效语音）','hanzi_per_min_speech','汉字/分钟'], ['英文速率（有效语音）','english_words_per_min_speech','词/分钟'],
      ['内部停顿次数','pause_count','次',0], ['平均停顿','pause_mean_s','秒'], ['最长停顿','pause_max_s','秒'],
      ['内部停顿总时长','pause_total_s','秒'], ['长停顿次数','long_pause_count','次',0],
      ['平均 RMS 数字音量','rms_dbfs_mean',' dBFS'], ['音量变化（四分位距）','rms_dbfs_iqr',' dB'],
      ['音量波动全范围','rms_dbfs_range',' dB'], ['基频中位数','f0_hz_median',' Hz'],
      ['基频最低','f0_hz_min',' Hz'], ['基频最高','f0_hz_max',' Hz'], ['音调变化（四分位距）','f0_semitone_iqr','半音']
    ];
    var metricLabels = {};
    rows.forEach(function (row) { metricLabels[row[1]] = row; });
    entries.forEach(function (entry, index) {
      var analysis = entry.analysis, m = analysis.metrics, feedback = entry.feedback;
      html += '<details class="speech-answer"' + (index === 0 ? ' open' : '') + '><summary>回答 ' + (index + 1) + ' · ' + esc(entry.question) + '</summary>';
      if (entry.answer_edited_after_asr) html += '<p class="confidence-note">回答文字在识别后有修改；声学速率仍基于原始识别文字，内容评价使用最终提交文字。</p>';
      html += '<h4>语言表达分析</h4>';
      if (feedback && feedback.status === 'ok') {
        Object.keys(contentLabels).forEach(function (key) {
          var item = feedback.content[key];
          html += '<p><b>' + contentLabels[key] + '：</b>' + esc(item.comment) + (item.evidence ? ' <small>依据：“' + esc(item.evidence) + '”</small>' : '') + '</p>';
        });
      } else html += '<p>AI 定性分析暂不可用，可重试生成；原评分与音频测量不受影响。</p>';
      var evidence = entry.lexical_evidence || {};
      var candidates = evidence.candidate_phrase_counts || {};
      html += '<p>文本候选词匹配：' + Object.keys(candidates).map(function (word) { return esc(word) + ' × ' + candidates[word]; }).join('；') + '。匹配次数不等同于口头禅。</p>';
      html += '<p>完全重复的句子：' + ((evidence.repeated_sentences || []).map(esc).join('；') || '未检出') + '。</p>';
      html += '<h4>语音特征分析</h4><div class="speech-table-wrap"><table class="speech-metrics"><tbody>';
      rows.forEach(function (row) { html += '<tr><th>' + row[0] + '</th><td>' + measured(m[row[1]], row[2], row[3]) + '</td></tr>'; });
      html += '<tr><th>有声帧比例（语音区间内）</th><td>' + measured(analysis.quality.voiced_frame_coverage == null ? null : analysis.quality.voiced_frame_coverage * 100, '%') + '</td></tr>';
      html += '<tr><th>削波样本比例</th><td>' + measured(analysis.quality.clipping_ratio == null ? null : analysis.quality.clipping_ratio * 100, '%', 2) + '</td></tr></tbody></table></div>';
      if (analysis.quality.flags.length) html += '<p class="confidence-note">部分指标受录音质量或有效语音长度限制；不可用项未填充数值。</p>';
      if (feedback && feedback.status === 'ok') {
        html += '<h4>综合改进建议</h4>';
        feedback.voice_observations.forEach(function (observation) {
          var row = metricLabels[observation.metric];
          html += '<p>' + (row ? row[0] : '已采集指标') + '：' + measured(m[observation.metric], row ? row[2] : '', row ? row[3] : 1) + '。' + esc(observation.comment) + '</p>';
        });
        html += '<ul>' + feedback.suggestions.map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('') + '</ul>';
      }
      // SER is intentionally not produced by the live pipeline until validated.
      if (analysis.emotion && analysis.emotion.status === 'validated_experimental') {
        html += '<h4>实验性语音情绪模型预测</h4><p>' + esc(analysis.emotion.model) + ' · ' + esc(analysis.emotion.label) + '</p>';
        html += '<p>模型输出不是心理诊断，不代表真实心理状态。</p>';
      }
      html += '</details>';
    });
    root.innerHTML = html;
  }
  var speechReviewBusy = false;
  var speechAutoStarted = false;
  function loadSpeechReview() {
    if (speechReviewBusy) return;
    speechReviewBusy = true;
    var button = el('speechReviewBtn');
    button.disabled = true; button.textContent = '正在生成 AI 语音建议…';
    fetch('/api/report/' + encodeURIComponent(getSid()) + '/speech-review', {method:'POST'})
      .then(function (response) { if (!response.ok) throw new Error(); return response.json(); })
      .then(function (data) {
        renderSpeech(data.speech_analyses);
    el('partialReport').classList.add('is-hidden');
        var complete = data.speech_analyses.every(function (entry) { return entry.feedback && entry.feedback.status === 'ok'; });
        showToast(complete ? '语音建议已生成并保存' : '部分语音建议暂不可用，可稍后重试；测量结果仍可查看');
      })
      .catch(function () { showToast('语音建议暂不可用，原报告仍可查看'); })
      .finally(function () { speechReviewBusy = false; button.disabled = false; button.textContent = '生成或重试 AI 语音建议'; });
  }
  el('speechReviewBtn').addEventListener('click', loadSpeechReview);


  /* ---------- 主渲染 ---------- */
  function renderReport(data) {
    showBody();
    renderMeta(data.interview);
    el("gradeBadge").textContent = data.grade || "—";
    el("reportDisclaimer").textContent = data.disclaimer || "";
    animateScore(data.scores.overall);
    renderScoreSub(data.scores);
    var dimensions = getRadarDimensions(data);
    drawRadar(dimensions);
    renderRadarValues(dimensions);
    renderReviews(data.answer_reviews);
    renderComment(data);
    renderWeaknesses(data.weaknesses,typeof data.scores.overall!=='number');
    renderSuggestions(data.suggestions);
    renderSpeech(data.speech_analyses);
    el('partialReport').classList.add('is-hidden');
    exportReady = true;
    exportSid = data.interview.id || getSid();
    syncExportButton();
    var pending = (data.speech_analyses || []).some(function (entry) {
      return !entry.feedback || entry.feedback.status !== 'ok';
    });
    if (pending && !speechAutoStarted) {
      speechAutoStarted = true;
      loadSpeechReview();
    }
  }

  /* ---------- 加载报告 ---------- */
  var reportLoading = false;
  var reportFailed = false;
  var reportWaiting = false;
  var pendingPolls = 0;
  var reportRetryTimer = null;
  function loadReport() {
    if (reportLoading || exportBusy) return;
    clearTimeout(reportRetryTimer);
    var sid = getSid();
    if (!sid) {
      showEmpty("暂无报告数据", "请先完成一场面试，结束即可生成 AI 评分报告。");
      return;
    }
    reportLoading = true;
    el('refreshBtn').disabled = true;
    el('retryReportBtn').disabled = true;
    if (!reportWaiting) showEmpty('正在加载报告', '正在读取已保存的报告；首次评分可能需要一些时间，请稍候。');
    var controller = window.AbortController ? new AbortController() : null;
    var deadline = setTimeout(function () { if (controller) controller.abort(); }, 15000);
    fetch("/api/report/" + encodeURIComponent(sid), controller ? {signal: controller.signal} : {})
      .then(function (res) { return res.text().then(function (text) {
        var data;
        try { data = JSON.parse(text); }
        catch (error) { throw new Error('公网连接返回异常（HTTP ' + res.status + '）。请点击重试加载报告，面试记录不会被清空。'); }
        return {ok: res.ok, status: res.status, data: data};
      }); })
      .then(function (r) {
        reportFailed = r.data.reason === 'failed';
        reportWaiting = r.status === 202;
        if (r.status===202 || r.data.reason==='failed') renderPartial(r.data.partial);
        if (r.ok && r.data.available) {
          try { renderReport(r.data); }
          catch (error) { throw new Error('报告显示失败，请点击重试加载报告；面试记录仍会保留。'); }
        } else if (r.status === 202 && r.data.reason === 'generating') {
          showEmpty(r.data.task_state === 'pending' ? '报告已排队' : '报告正在生成', r.data.message || '正在分析回答，您可以离开，稍后从历史面试查看。');
          pendingPolls++;
          reportRetryTimer = setTimeout(loadReport, document.hidden ? 30000 : pendingPolls>20 ? 10000 : pendingPolls>10 ? 5000 : 2000);
        } else if (r.ok && r.data.reason === "not_finished") {
          showEmpty("面试尚未结束", r.data.message || "请先完成或结束本场面试。");
        } else if (r.status === 404) {
          el('partialReport').classList.add('is-hidden');
          showEmpty("无法访问这场面试", (r.data && r.data.error) || '请使用开始这场面试时的浏览器和网址，从历史面试重新打开。');
        } else {
          showEmpty("报告暂不可用", (r.data && r.data.error) || "请稍后重试");
        }
      })
      .catch(function (error) {
        reportWaiting = false;
        var message = error.name === 'AbortError' ? '等待报告响应超时，面试记录仍会保留。请点击重试加载报告。'
          : error.message === 'Failed to fetch' || error instanceof TypeError ? '连接暂时中断，面试记录仍会保留。请点击重试加载报告，无需重新面试。' : error.message;
        showEmpty("报告暂未加载成功", message || '请点击重试加载报告，无需重新面试。');
      }).finally(function () {
        clearTimeout(deadline);
        reportLoading = false;
        el('refreshBtn').disabled = reportWaiting;
        el('retryReportBtn').disabled = reportWaiting;
        el('retryReportBtn').textContent = reportWaiting ? '正在自动更新…' : '重试加载报告';
        el('emptyHomeLink').textContent = reportWaiting ? '返回首页，稍后查看' : '返回首页';
      });
  }

  document.addEventListener('visibilitychange',function () {
    if (!reportWaiting) return;
    clearTimeout(reportRetryTimer);
    if (document.hidden) reportRetryTimer=setTimeout(loadReport,30000);
    else loadReport();
  });

  /* ---------- 导出 / 刷新 / 再练按钮 ---------- */
  var exportBtn = el("exportBtn");
  if (exportBtn) {
    exportBtn.addEventListener("click", function () {
      if (exportBusy || !exportReady || !exportSid) return;
      exportBusy = true;
      exportFailed = false;
      syncExportButton();
      var status = el('exportStatus');
      status.classList.remove('is-error');
      status.textContent = '正在生成 PDF，请稍候；完整参考回答会包含在文件中。';
      el('refreshBtn').disabled = true;
      var controller = window.AbortController ? new AbortController() : null;
      var deadline = setTimeout(function () { if (controller) controller.abort(); }, 45000);
      fetch('/api/report/' + encodeURIComponent(exportSid) + '/export',
        controller ? {credentials:'same-origin', signal:controller.signal} : {credentials:'same-origin'})
        .then(function (response) {
          var type = (response.headers.get('Content-Type') || '').toLowerCase();
          if (!response.ok || type.indexOf('application/pdf') === -1) {
            return response.text().then(function (body) {
              var detail;
              try { detail = JSON.parse(body); } catch (error) { detail = null; }
              throw new Error(detail && detail.error || '导出连接异常（HTTP ' + response.status + '），请点击重试导出。');
            });
          }
          var disposition = response.headers.get('Content-Disposition') || '';
          var filename = 'AI面试报告.pdf';
          var encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
          var plain = /filename="([^"]+)"/i.exec(disposition);
          try { if (encoded) filename = decodeURIComponent(encoded[1]); else if (plain) filename = plain[1]; }
          catch (error) { filename = 'AI面试报告.pdf'; }
          filename = filename.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_');
          return response.blob().then(function (blob) {
            return blob.slice(0, 5).text().then(function (signature) {
              if (signature !== '%PDF-') throw new Error('收到的文件不是有效 PDF，请点击重试导出。');
              var url = URL.createObjectURL(blob);
              var link = document.createElement('a');
              link.href = url;
              link.download = filename;
              document.body.appendChild(link);
              link.click();
              link.remove();
              setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
              status.textContent = 'PDF 已生成，已请求浏览器下载。手机若打开预览，可通过分享菜单保存到文件。';
            });
          });
        })
        .catch(function (error) {
          exportFailed = true;
          status.classList.add('is-error');
          status.textContent = error.name === 'AbortError' ? '导出等待超时，请点击重试导出；报告仍保留。'
            : error instanceof TypeError ? '导出连接中断，请点击重试导出；报告仍保留。' : error.message;
        })
        .finally(function () {
          clearTimeout(deadline);
          exportBusy = false;
          syncExportButton();
          el('refreshBtn').disabled = false;
        });
    });
  }
  var refreshBtn = el("refreshBtn");
  el('retryReportBtn').addEventListener('click', function () {
    if (!reportFailed) { loadReport(); return; }
    if (reportLoading) return;
    reportLoading = true;
    el('retryReportBtn').disabled = true;
    fetch('/api/report/' + encodeURIComponent(getSid()) + '/generate', {method:'POST'})
      .then(function (res) { if (!res.ok) return res.json().then(function (data) { throw new Error(data.error || '请稍后重试'); }); reportFailed = false; })
      .catch(function (error) { showEmpty('重试暂未成功', error.message || '请检查网络后重试'); })
      .finally(function () { reportLoading = false; el('retryReportBtn').disabled = false; if (!reportFailed) loadReport(); });
  });
  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () {
      showToast("正在重新加载报告…");
      loadReport();
    });
  }

  var replaySameBtn = el("replaySameBtn");
  if (replaySameBtn) {
    var replayOriginalHTML = replaySameBtn.innerHTML;
    replaySameBtn.addEventListener("click", function () {
      var cfg = null;
      try { cfg = JSON.parse(localStorage.getItem("iv-config") || "null"); } catch (e) { cfg = null; }
      if (!cfg || !cfg.job || !cfg.level) {
        showToast("未找到上次面试配置，请先选择岗位与难度");
        setTimeout(function () { window.location.href = "/#config"; }, 900);
        return;
      }
      replaySameBtn.disabled = true;
      replaySameBtn.classList.add("is-loading");
      replaySameBtn.innerHTML = "正在生成首题…";
      var retryId;
      var reset=document.getElementById('replayResetBtn');if(reset)reset.hidden=true;
      var originalScope=window.Account && Account.scope;
      (window.Account ? Account.refresh() : Promise.resolve()).then(function(){
        if(window.Account && Account.scope!==originalScope){var changed=new Error('登录状态已改变，请刷新后确认练习配置；尚未发出AI请求。');changed.startPreparation=true;throw changed;}
        return InterviewStarts.request(Object.assign({ job: cfg.job, level: cfg.level }, cfg.major_id ? {major_id:cfg.major_id} : {}));
      })
        .then(function (r) {
          retryId=r.request_id;
          if (!r.ok || !r.data.session_id) {
            var code=r.data && r.data.code;
            if(code==='start_uncertain' || code==='start_conflict'){
              if(!reset){reset=document.createElement('button');reset.type='button';reset.id='replayResetBtn';reset.className='btn btn--ghost';replaySameBtn.parentNode.appendChild(reset);}
              reset.textContent='我已核对历史，允许新建一场';reset.hidden=false;
              reset.onclick=function(){InterviewStarts.finish(retryId);reset.hidden=true;showToast('已准备新请求，请再次点击再练一次。');};
            } else if(code!=='start_in_progress')InterviewStarts.finish(retryId);
            var failure=new Error(r.data && r.data.error ? r.data.error : '面试启动失败，请先从历史记录核对。');
            failure.startPreparation=true;throw failure;
          }
          try {
            if(window.Account && !Account.ownsPage())throw new Error("账户已切换，请刷新页面");
            localStorage.setItem("iv-session", JSON.stringify({
              session_id: r.data.session_id, job: r.data.job, level: r.data.level,
              selection: r.data.selection || {},
              question_sequence: r.data.question_sequence || 1,
              question: r.data.question, progress: r.data.progress, answered_count:r.data.answered_count || 0,
              finished:!!r.data.finished,background_active:!!r.data.background_active
            }));
          } catch (e) {
            var storageFailure=new Error('本场面试已保存，但浏览器未能保存进入信息。请允许本站存储后，从历史记录继续，避免重复开始。');
            storageFailure.startPreparation=true;throw storageFailure;
          }
          InterviewStarts.finish(retryId);
          window.location.href = "/interview";
        })
        .catch(function (error) {
          showError(error.startPreparation ? error.message : error.name==='AbortError' ? '首题等待超时。请先从历史记录核对已保存练习，再手动重试。' : '连接暂时中断或返回异常。请先从历史记录核对，当前报告仍保留。');
          replaySameBtn.disabled = false;
          replaySameBtn.classList.remove("is-loading");
          replaySameBtn.innerHTML = replayOriginalHTML;
        });
    });
  }

  /* ---------- 启动 ---------- */
  window.addEventListener("load", loadReport);
  window.addEventListener("resize", function () {
    // 仅当已有数据时重绘雷达
    if (!reportBody.classList.contains("is-hidden")) {
      if (lastDimensions) drawRadar(lastDimensions);
    }
  });
  // 缓存最近评分供 resize 重绘
  var _origRender = renderReport;
  renderReport = function (data) { window.__lastScores = data.scores; _origRender(data); };
})();
