/* AI Interview Agent：保留文字面试，停止录音后自动 ASR（4.2），手动浏览器 TTS（4.3）。 */
(function () {
 function boot() {
  "use strict";

  var MAX_ANSWER_CHARS = 4000;

  /* ---------- 读取会话（来自首页 start） ---------- */
  var session;
  try {
    session = JSON.parse(localStorage.getItem("iv-session") || "null");
  } catch (e) { session = null; }

  // 会话缺失 → 回到首页重新开始
  if (!session || !session.session_id) {
    window.location.replace("/");
    return;
  }

  /* ---------- DOM ---------- */
  var stage = document.getElementById("ivStage");
  var qIndexEl = document.getElementById("qIndex");
  var questionTextEl = document.getElementById("questionText");
  var qLevelBadge = document.getElementById("qLevelBadge");
  var jobBadge = document.getElementById("jobBadge");
  var qNowEl = document.getElementById("qNow");
  var qTotalEl = document.getElementById("qTotal");
  var progressFill = document.getElementById("progressFill");
  var progressPhase = document.getElementById("progressPhase");
  var stateTextEl = document.getElementById("stateText");
  var orbEmoji = document.getElementById("orbEmoji");
  var micBtn = document.getElementById("micBtn");
  var replayBtn = document.getElementById("replayBtn");
  var skipBtn = document.getElementById("skipBtn");
  var answerInput = document.getElementById("answerInput");
  var submitBtn = document.getElementById("submitAnswerBtn");
  var feedbackCard = document.getElementById("aiFeedback");
  var feedbackTagEl = document.getElementById("feedbackTag");
  var feedbackBodyEl = document.getElementById("feedbackBody");
  var timerTextEl = document.getElementById("timerText");
  var recTimeEl = document.getElementById("recTime");
  var answeredCountEl = document.getElementById("answeredCount");
  var ttsHint = document.getElementById("ttsHint");
  var endBtn = document.getElementById("endBtn");
  var endModal = document.getElementById("endModal");
  var cancelEndBtn = document.getElementById("cancelEndBtn");
  var confirmEndBtn = document.getElementById("confirmEndBtn");
  var waveEl = document.getElementById("wave");

  /* ---------- 声波条生成（视觉装饰） ---------- */
  for (var i = 0; i < 36; i++) {
    var bar = document.createElement("i");
    bar.style.animationDelay = (Math.random() * 1.0).toFixed(2) + "s";
    waveEl.appendChild(bar);
  }

  /* ---------- 状态 ---------- */
  var answered = session.answered_count || 0;
  var totalSec = session.elapsed_seconds || 0;
  var busy = false;
  var ending=false;
  var finished = !!session.finished;
  var questionId = session.question_sequence || 'legacy-' + ((session.progress || {}).main || 1) + '-' + ((session.progress || {}).type || 'main');
  var drafts = new InterviewDrafts(session.session_id);
  var draftStatus = document.getElementById('draftStatus');
  var stateReady = false, recovering = false, stateProcessing = false, recoveryPromise = null;
  var recoverBtn = document.getElementById('recoverStateBtn');
  var clearDraftBtn = document.getElementById('clearDraftBtn');
  var completionCard = document.getElementById('completionCard');
  function status(text, error) { if (draftStatus.textContent !== text) draftStatus.textContent = text; draftStatus.classList.toggle('is-error',!!error); }
  function saveDraft() {
    if(window.Account && !Account.ownsPage())return;
    if (finished) return;
    var old = drafts.get(questionId);
    drafts.put(questionId, answerInput.value, old && old.pending);
    status(drafts.available ? (answerInput.value ? '草稿已保存在当前浏览器，24小时内可恢复。' : '草稿仅保存在当前浏览器，保留24小时；录音文件不保存。') : '浏览器暂不能保存草稿，请复制回答备份后再离开页面。', !drafts.available);
  }
  function showArchived(item) {
    if (item && item.text) {
      document.getElementById('previousDraftText').textContent = item.text;
      document.getElementById('previousDraft').classList.remove('is-hidden');
    }
  }
  function checkpoint() {
    if(window.Account && !Account.ownsPage())return;
    session.question_sequence = questionId; session.finished = finished;
    session.answered_count = answered; session.elapsed_seconds = totalSec;
    session.question = questionTextEl.textContent;
    session.last_comment = feedbackBodyEl.textContent;
    try {
      var current = JSON.parse(localStorage.getItem('iv-session') || 'null');
      if (!current || current.session_id === session.session_id) {
        var cached = Object.assign({},session);
        delete cached.last_comment; // Reload feedback from the owner-scoped server state, not permanent local storage.
        localStorage.setItem('iv-session',JSON.stringify(cached));
      }
    } catch (error) {}
  }
  function showCompletion() {
    completionCard.classList.toggle('is-hidden',!finished);
    if (finished) {
      progressFill.style.width = '100%';
      document.getElementById('progressTrack').setAttribute('aria-valuenow','100');
      document.getElementById('progressTrack').setAttribute('aria-valuetext','本场作答已结束，等待手动查看报告');
      endBtn.textContent = '查看报告';
      setState('idle','作答已保存，请先查看最后点评，再手动进入报告','✅');
      progressPhase.textContent = '等待手动查看报告';
    }
    answerInput.readOnly = finished;
  }
  function displayFeedback(comment) {
    if (comment) { feedbackCard.open=!!finished; feedbackBodyEl.textContent = comment; syncFeedbackLabel(); feedbackCard.classList.remove('is-hidden'); }
  }
  function syncFeedbackLabel() { feedbackTagEl.textContent=feedbackCard.open ? '收起详情' : '展开详情'; }
  feedbackCard.addEventListener('toggle',syncFeedbackLabel);
  function applySnapshot(data) {
    var oldId = questionId, previous = drafts.get(oldId);
    if (data.question_sequence !== oldId) {
      if (typeof oldId === 'string' && data.question === session.question && previous && !previous.pending) {
        drafts.put(data.question_sequence,previous.text,null); drafts.remove(oldId);
      } else if (previous) {
        // Never silently move an answer to a different question.
        if (!previous.pending || previous.text.trim() !== previous.pending.answer) showArchived(previous);
        if (previous.pending && previous.text.trim() === previous.pending.answer) drafts.remove(oldId);
      }
      clearRecording();
    }
    questionId = data.question_sequence;
    finished = !!data.finished; if(finished)feedbackCard.open=true; stateProcessing = !!data.processing;
    answered = data.answered_count || 0; answeredCountEl.textContent = answered;
    if (Number.isFinite(data.elapsed_seconds)) { totalSec = data.elapsed_seconds; timerTextEl.textContent = fmt(totalSec); }
    session.progress = data.progress; session.question_sequence = questionId;
    showQuestion(data.question,data.progress); displayFeedback(data.comment);
    if(drafts.importLegacy) drafts.importLegacy(questionId);
    var restored = drafts.get(questionId);
    answerInput.value = !finished && restored ? restored.text : '';
    if (finished) { drafts.clear(); status('作答已保存，最后点评会一直保留，直到你手动查看报告。'); }
    else if (stateProcessing) status('上一条回答仍在处理，请稍后点击“恢复当前题目”；草稿已保留。');
    else status(oldId !== questionId ? '已恢复服务器上的当前题目；旧草稿不会自动填入新题。' : restored && restored.text ? '已恢复本题草稿，可继续编辑或手动提交。' : '草稿仅保存在当前浏览器，保留24小时；录音文件不保存。');
    if (!finished && !drafts.available) status('浏览器暂不能保存草稿，请复制回答备份后再离开页面。',true);
    showCompletion(); checkpoint();
  }
  function recoverState() {
    if (recoveryPromise) return recoveryPromise;
    recovering = true; recoverBtn.disabled = true; syncControls();
    var controller = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) controller.abort(); },8000);
    recoveryPromise = fetch('/api/interview/' + encodeURIComponent(session.session_id) + '/state', controller ? {signal:controller.signal,cache:'no-store'} : {cache:'no-store'})
      .then(function (response) { return response.json().then(function (data) {
        if (!response.ok || !Number.isInteger(data.question_sequence)) throw new Error(data.error || '题目状态暂时无法恢复');
        stateReady = true; applySnapshot(data); return true;
      }); })
      .catch(function () {
        status('暂未连上面试服务，草稿仍可编辑。联网后点击“恢复当前题目”，再提交。',true); return false;
      }).finally(function () {
        clearTimeout(timer); recovering = false; recoveryPromise = null; recoverBtn.disabled = false; syncControls();
      });
    return recoveryPromise;
  }
  answerInput.addEventListener('input',saveDraft);
  clearDraftBtn.addEventListener('click',function () {
    if (busy || finished) return;
    var item = drafts.get(questionId);
    answerInput.value = ''; drafts.put(questionId,'',item && item.pending);
    status(drafts.available ? '本题输入草稿已清空。' : '输入已清空，但浏览器存储不可用，无法确认本机草稿已清除。', !drafts.available);
  });
  recoverBtn.addEventListener('click',function () { saveDraft(); recoverState(); });
  function viewReport() { drafts.clear(); window.location.href = '/report?id=' + encodeURIComponent(session.session_id); }
  document.getElementById('viewReportBtn').addEventListener('click',viewReport);
  var backgroundSession = document.getElementById('backgroundSession');
  var backgroundVersion = 0;
  if (session.background_active) backgroundSession.classList.remove('is-hidden');
  fetch('/api/interview/' + encodeURIComponent(session.session_id) + '/background')
    .then(function (response) { return response.json().then(function(data){return response.ok ? data : null;}); })
    .then(function (data) {
      if (data && backgroundVersion === 0) backgroundSession.classList.toggle('is-hidden', !data.active);
    }).catch(function () {});
  document.getElementById('clearSessionBackgroundBtn').addEventListener('click', function () {
    var button = this;
    if (button.disabled) return;
    backgroundVersion++;
    button.disabled = true;
    fetch('/api/interview/' + encodeURIComponent(session.session_id) + '/background', {method:'DELETE'})
      .then(function (response) { return response.json().then(function (data) {
        if (!response.ok || !data.cleared) throw new Error(data.error || '清除失败，请重试');
      }); })
      .then(function () {
        session.background_active = false;
        try {
          var saved = JSON.parse(localStorage.getItem('iv-session') || '{}');
          saved.background_active = false;
          localStorage.setItem('iv-session', JSON.stringify(saved));
        } catch (error) {}
        backgroundSession.classList.add('is-hidden');
        showToast('独立背景资料已清除；已有对话仍随面试记录保留');
      }).catch(function () { showToast('暂时未能清除背景，请稍后重试'); })
      .finally(function () { button.disabled = false; });
  });

  jobBadge.textContent = session.job;
  if (session.selection && session.selection.major) {
    jobBadge.textContent += ' · ' + session.selection.major;
  }
  qLevelBadge.textContent = session.level;
  qTotalEl.textContent = (session.progress && session.progress.total) || 3;

  function pad2(n) { return n < 10 ? "0" + n : "" + n; }
  function fmt(s) { return pad2(Math.floor(s / 60)) + ":" + pad2(s % 60); }

  function setState(next, text, emoji) {
    stage.setAttribute("data-state", next);
    if (text) stateTextEl.textContent = text;
    if (emoji) orbEmoji.textContent = emoji;
  }

  function updateProgress(progress) {
    if (!progress) return;
    var completed = Math.max(0,(progress.main-1)*2 + (progress.type==='followup' ? 1 : 0));
    var pct = Math.round(completed/(progress.total*2)*100);
    progressFill.style.width = Math.min(100,pct) + "%";
    document.getElementById('progressTrack').setAttribute('aria-valuenow',String(pct));
    document.getElementById('progressTrack').setAttribute('aria-valuetext','已完成'+completed+'次作答；当前主问题'+progress.main+'/'+progress.total);
    qNowEl.textContent = progress.main;
    qIndexEl.textContent = pad2(progress.main);
    progressPhase.textContent = progress.type === "followup" ? "追问中" : "首轮作答";
  }

  function showQuestion(text, progress) {
    if (tts) stopQuestionSpeech();
    questionTextEl.textContent = text;
    qIndexEl.textContent = pad2((progress && progress.main) || 1);
    if (progress) updateProgress(progress);
  }

  /* ---------- 总计时（面试用时） ---------- */
  setInterval(function () {
    if (!finished) totalSec++;
    timerTextEl.textContent = fmt(totalSec);
  }, 1000);

  /* ---------- 持久化会话（供刷新后恢复当前题） ---------- */
  // Restore local text immediately; verify the current question before submission.
  showQuestion(!window.Account || Account.scope==='legacy' ? session.question : '正在核对本场面试…',session.progress);
  var storedDraft = drafts.get(questionId);
  if (!finished && storedDraft && (!window.Account || Account.scope==='legacy')) answerInput.value = storedDraft.text;
  if(!window.Account || Account.scope==='legacy')displayFeedback(session.last_comment);
  answeredCountEl.textContent = answered;

  function newRequestId() {
    var bytes = new Uint8Array(16); window.crypto.getRandomValues(bytes);
    return Array.from(bytes).map(function (b) { return ('0'+b.toString(16)).slice(-2); }).join('');
  }
  function submitAnswer(value, withoutAudio) {
    if (busy || recovering || finished || voicePending()) return;
    var text = (value || '').trim();
    if (!text || text.length > MAX_ANSWER_CHARS) { status('回答需为1至4000字，请检查后手动提交。',true); return; }
    saveDraft();
    var originalQuestion = questionId;
    busy = true; syncControls(); stopQuestionSpeech();
    recoverState().then(function (ready) {
      if (!ready || finished || originalQuestion !== questionId || stateProcessing) return;
      var stored = drafts.get(questionId);
      var analysisId = withoutAudio ? null : rec.analysisId;
      var pending = stored && stored.pending;
      if (!pending || pending.answer !== text || pending.analysis_id !== analysisId) {
        pending = {request_id:newRequestId(), answer:text, analysis_id:analysisId, question_sequence:questionId};
      }
      drafts.put(questionId,answerInput.value,pending);
      setState('thinking','AI 正在分析你的回答…','🧠');
      status('正在提交；草稿已保留，请等待结果。');
      return fetch('/api/interview/answer',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(Object.assign({session_id:session.session_id},pending))
      }).then(function (response) { return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || '提交未完成，请恢复题目后重试');
        return data;
      }); }).then(function (data) {
        var edited = answerInput.value !== value;
        if (edited && answerInput.value) {
          drafts.put(originalQuestion,answerInput.value,null); showArchived(drafts.get(originalQuestion));
        } else drafts.remove(originalQuestion);
        answerInput.value = '';
        clearRecording();
        answered = data.answered_count || answered+1; answeredCountEl.textContent = answered;
        displayFeedback(data.comment);
        finished = !!data.finished; if(finished)feedbackCard.open=true;
        questionId = data.question_sequence || (data.next_question ? originalQuestion+3 : originalQuestion);
        session.progress = data.progress;
        if (data.next_question) showQuestion(data.next_question,data.progress);
        checkpoint(); showCompletion();
        if (!finished) {
          setState('idle','请查看上一题点评，并继续回答当前问题','🎙️'); updateProgress(data.progress);
          status(edited ? '上一题已提交；处理中新增的文字保留在上方，不会自动填入下一题。' : '上一题已保存。当前题目可继续作答，草稿将自动保存。');
        } else {
          drafts.clear(); status('最后一题的点评已保留。看完后，点击“结束面试并查看报告”。');
        }
      });
    }).catch(function (error) {
      status(error.message && error.message !== 'Failed to fetch' ? error.message : '连接中断，草稿仍保留。正在核对回答是否已保存。',true);
      setState('idle','提交结果待确认，草稿仍保留','🎙️');
      return recoverState(); // Read state only; never automatically send another answer.
    }).finally(function () { busy = false; syncControls(); });
  }

  /* ---------- 文字提交 ---------- */
  submitBtn.addEventListener("click", function () {
    var v = answerInput.value;
    submitAnswer(v);
  });

  // Ctrl/Cmd + Enter 快捷提交
  answerInput.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      submitBtn.click();
    }
  });

  /* ---------- 语音作答：只在 stop（最后一次 dataavailable 之后）组装并上传 ---------- */
  var REC_MAX_SEC = 120;
  var rec = {
    mediaRecorder: null, stream: null, timerId: null, sec: 0,
    blob: null, blobUrl: null, mimeType: '', state: 'idle',
    generation: 0, request: null, lastTranscript: '', analysisId: null
  };
  var voiceControls = document.getElementById('voiceControls');
  var voicePlayer = document.getElementById('voicePlayer');
  var voiceDur = document.getElementById('voiceDur');
  var voiceHint = document.getElementById('voiceHint');
  var redoBtn = document.getElementById('redoBtn');
  var transcribeBtn = document.getElementById('transcribeBtn');
  var transcribeStatus = document.getElementById('transcribeStatus');
  var analysisToggle = document.getElementById('includeAnalysis');
  var analysisPanel = document.getElementById('audioAnalysis');
  var analysisMetrics = document.getElementById('audioAnalysisMetrics');
  var analysisQuality = document.getElementById('audioAnalysisQuality');
  var unlinkAnalysisBtn = document.getElementById('unlinkAnalysisBtn');
  unlinkAnalysisBtn.addEventListener('click', function () {
    if (busy || voicePending()) return;
    rec.analysisId = null;
    analysisQuality.textContent = '已取消与回答的关联，本段指标不会进入面试报告。';
  });
  analysisToggle.addEventListener('change', function () {
    if (!analysisToggle.checked) { rec.analysisId = null; showAudioAnalysis(null); }
  });

  function showAudioAnalysis(data) {
    analysisPanel.classList.add('is-hidden');
    if (!data) return;
    analysisPanel.classList.remove('is-hidden');
    analysisPanel.open = true;
    if (data.status === 'unavailable' || !data.metrics) {
      analysisMetrics.textContent = '本次音频指标暂不可用，识别文字仍可编辑和提交。';
      analysisQuality.textContent = '可稍后勾选基础指标并重新识别。';
      return;
    }
    var metrics = data.metrics;
    function value(key, unit, digits) {
      var number = metrics[key];
      return typeof number === 'number' && Number.isFinite(number) ? number.toFixed(digits) + unit : '暂不可用';
    }
    analysisMetrics.textContent = [
      '录音时长：' + value('duration_s', '秒', 1),
      '语音时长：' + value('speech_s', '秒', 1),
      '内部停顿：' + value('pause_count', '次', 0) + ' / ' + value('pause_total_s', '秒', 1),
      '平均 / 最长停顿：' + value('pause_mean_s', '秒', 1) + ' / ' + value('pause_max_s', '秒', 1),
      '中文速率（含停顿）：' + value('hanzi_per_min_total', '汉字/分钟', 0),
      '中文速率（语音段）：' + value('hanzi_per_min_speech', '汉字/分钟', 0),
      '英文速率（语音段）：' + value('english_words_per_min_speech', '词/分钟', 0),
      '数字音量中位数：' + value('rms_dbfs_median', ' dBFS', 1),
      '基频中位数：' + value('f0_hz_median', ' Hz', 1),
      '音调变化（四分位距）：' + value('f0_semitone_iqr', '半音', 1)
    ].join('；');
    var labels = {no_speech: '未检测到可靠语音', too_short: '录音过短',
      insufficient_speech: '有效语音较短', clipping: '音频可能削波', low_level: '录音音量较低',
      no_hanzi: '无中文汉字，中文速率不适用', pitch_unreliable: '可靠有声帧不足，未提供基频'};
    var flags = data.quality && Array.isArray(data.quality.flags) ? data.quality.flags : [];
    analysisQuality.textContent = flags.length ? '质量提示：' + flags.map(function (flag) { return labels[flag] || '部分指标不可用'; }).join('；') : '已完成基础测量。停顿指语音段之间至少 0.5 秒的间隔，首尾静音另计。';
    if (!rec.analysisId) analysisQuality.textContent += ' 本段指标未关联面试，仅供当前查看。';
  }

  function voicePending() {
    return ['requesting', 'recording', 'stopping', 'uploading', 'recognizing'].indexOf(rec.state) >= 0;
  }
  function syncControls() {
    var locked = busy || finished || ending || recovering || !stateReady || stateProcessing;
    submitBtn.disabled = skipBtn.disabled = locked || voicePending();
    micBtn.disabled = locked || (voicePending() && rec.state !== 'recording');
    redoBtn.disabled = locked || ['requesting', 'recording', 'stopping'].indexOf(rec.state) >= 0;
    transcribeBtn.disabled = locked || voicePending() || !rec.blob;
    confirmEndBtn.disabled = busy || recovering || ending;
    endBtn.disabled = busy || recovering || ending;
    recoverBtn.disabled = busy || recovering;
    document.getElementById('viewReportBtn').disabled = busy || recovering;
    clearDraftBtn.disabled = busy || finished;
    answerInput.readOnly = finished;
    analysisToggle.disabled = locked || voicePending();
    unlinkAnalysisBtn.disabled = locked || voicePending();
  }
  function setRecState(state, message) {
    rec.state = state;
    var labels = {
      idle: '点击右侧麦克风开始录音（最长 120 秒）', ready: '录音完成，准备识别…',
      requesting: '等待麦克风权限…', recording: '正在录音，再次点击麦克风停止（最长 120 秒）',
      stopping: '正在生成完整音频…', uploading: '正在上传音频…',
      recognizing: '正在识别语音…首次加载模型可能较慢',
      completed: '识别完成，请检查文字后手动提交', failed: '语音处理失败，可重新识别或文字作答'
    };
    voiceHint.textContent = message || labels[state];
    if (!busy && !finished) setState(state === 'recording' ? 'listening' : 'idle', voiceHint.textContent, state === 'recording' ? '🎤' : '🎙️');
    if (['uploading', 'recognizing', 'completed', 'failed'].indexOf(state) >= 0) {
      transcribeStatus.classList.remove('is-hidden', 'is-loading', 'is-error');
      transcribeStatus.classList.toggle('is-loading', state === 'uploading' || state === 'recognizing');
      transcribeStatus.classList.toggle('is-error', state === 'failed');
      transcribeStatus.textContent = message || labels[state];
    }
    syncControls();
  }
  function releaseMic() {
    if (rec.stream) rec.stream.getTracks().forEach(function (track) { track.stop(); });
    rec.stream = null;
    clearInterval(rec.timerId); rec.timerId = null;
  }
  function cancelTranscription() {
    var request = rec.request;
    rec.request = null;
    if (request) request.abort();
  }
  function clearRecording() {
    rec.generation++;
    cancelTranscription();
    if (rec.mediaRecorder && rec.mediaRecorder.state !== 'inactive') {
      try { rec.mediaRecorder.stop(); } catch (e) { /* releasing tracks also stops capture */ }
    }
    rec.mediaRecorder = null;
    releaseMic();
    voicePlayer.pause(); voicePlayer.removeAttribute('src'); voicePlayer.load();
    if (rec.blobUrl) URL.revokeObjectURL(rec.blobUrl);
    rec.blobUrl = null; rec.blob = null; rec.sec = 0;
    rec.analysisId = null;
    recTimeEl.textContent = '00:00';
    voiceControls.classList.add('is-hidden');
    transcribeStatus.classList.add('is-hidden');
    showAudioAnalysis(null);
    setRecState('idle');
  }
  function pickMimeType() {
    return ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find(function (type) {
      return MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(type);
    }) || '';
  }
  function extFromMime(type) {
    if (/mp4/.test(type)) return '.mp4';
    if (/ogg/.test(type)) return '.ogg';
    return '.webm';
  }
  function startRecording() {
    if (busy || finished || voicePending()) return;
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setRecState('failed', '浏览器不支持录音，请使用 localhost 或 HTTPS，或直接文字作答'); return;
    }
    stopQuestionSpeech();
    clearRecording();
    var generation = rec.generation;
    setRecState('requesting');
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      if (generation !== rec.generation || finished) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
      rec.stream = stream;
      var type = pickMimeType();
      var recorder;
      try { recorder = new MediaRecorder(stream, type ? { mimeType: type } : {}); }
      catch (e) { recorder = new MediaRecorder(stream); }
      rec.mediaRecorder = recorder;
      rec.mimeType = recorder.mimeType || type;
      var chunks = [];
      recorder.ondataavailable = function (event) {
        if (generation === rec.generation && event.data && event.data.size) chunks.push(event.data);
      };
      recorder.onerror = function () {
        if (generation !== rec.generation) return;
        clearRecording(); setRecState('failed', '录音中断，请检查设备后重新录音');
      };
      recorder.onstop = function () {
        if (generation !== rec.generation) return;
        releaseMic(); rec.mediaRecorder = null;
        rec.blob = new Blob(chunks, { type: rec.mimeType || (chunks[0] && chunks[0].type) || 'audio/webm' });
        if (!rec.blob.size) { rec.blob = null; setRecState('failed', '录音为空，请检查麦克风后重试'); return; }
        rec.blobUrl = URL.createObjectURL(rec.blob);
        voicePlayer.src = rec.blobUrl;
        voiceDur.textContent = fmt(rec.sec) + ' · ' + rec.blob.type.split(';')[0];
        voiceControls.classList.remove('is-hidden');
        setRecState('ready');
        transcribeRecording(); // 不调用 submitAnswer，识别结果只进入可编辑文本框
      };
      recorder.start();
      setRecState('recording');
      rec.timerId = setInterval(function () {
        rec.sec++; recTimeEl.textContent = fmt(rec.sec);
        if (rec.sec >= REC_MAX_SEC) stopRecording();
      }, 1000);
    }).catch(function (error) {
      if (generation !== rec.generation) return;
      releaseMic();
      var messages = {
        NotAllowedError: '麦克风权限被拒绝，请在地址栏允许后重试，或直接文字作答',
        NotFoundError: '未检测到麦克风设备，可直接文字作答',
        NotReadableError: '麦克风不可用或被占用，请检查后重试'
      };
      setRecState('failed', messages[error.name] || '无法启动录音，请检查浏览器权限和设备');
    });
  }
  function stopRecording() {
    if (rec.state !== 'recording' || !rec.mediaRecorder) return;
    setRecState('stopping');
    clearInterval(rec.timerId); rec.timerId = null;
    try { rec.mediaRecorder.stop(); }
    catch (e) { clearRecording(); setRecState('failed', '无法结束录音，请重新录音'); }
  }
  function transcribeRecording() {
    if (busy || finished || voicePending() || !rec.blob || !rec.blob.size || rec.request) return;
    if (rec.blob.size >= 25 * 1024 * 1024) { setRecState('failed', '音频过大，请缩短录音'); return; }
    var generation = rec.generation;
    var request = new XMLHttpRequest();
    rec.request = request;
    function current() { return generation === rec.generation && rec.request === request && !finished; }
    function fail(message) {
      if (!current()) return;
      rec.request = null; setRecState('failed', message);
    }
    request.open('POST', '/api/speech/transcribe');
    if(window.Account) request.setRequestHeader('X-CSRF-Token',Account.csrf);
    request.timeout = 180000;
    request.upload.onload = function () { if (current()) setRecState('recognizing'); };
    request.onload = function () {
      if (!current()) return;
      var data;
      try { data = JSON.parse(request.responseText); } catch (e) { fail('服务器返回异常，请手动重新识别'); return; }
      if (request.status < 200 || request.status >= 300 || !data || !data.success || typeof data.text !== 'string' || !data.text.trim()) {
        fail((data && data.error) || '识别失败或未检测到语音，请重试'); return;
      }
      var text = data.text.trim();
      // 用户在等待时仍可编辑；保留已有草稿，将新识别内容追加到后面。
      if (answerInput.value.trim() && answerInput.value !== rec.lastTranscript) text = answerInput.value + '\n' + text;
      answerInput.value = text; rec.lastTranscript = text; saveDraft();
      rec.analysisId = typeof data.analysis_id === 'string' ? data.analysis_id : null;
      rec.request = null;
      setRecState('completed', '识别完成，文字已填入；请检查、编辑后手动提交');
      showAudioAnalysis(data.analysis);
      answerInput.focus();
    };
    request.onerror = function () { fail('网络异常，录音已保留，可手动重新识别或文字作答'); };
    request.ontimeout = function () { fail('识别等待超时，录音已保留，可稍后手动重试'); };
    request.onabort = function () { fail('识别已取消'); };
    var form = new FormData();
    form.append('audio', rec.blob, 'recording' + extFromMime(rec.blob.type));
    form.append('session_id', session.session_id);
    if (analysisToggle.checked) {
      form.append('include_analysis', 'true');
      form.append('question', questionTextEl.textContent);
    }
    rec.analysisId = null;
    showAudioAnalysis(null);
    setRecState('uploading');
    try { request.send(form); } catch (e) { fail('无法上传音频，请检查网络后重试'); }
  }
  micBtn.addEventListener('click', function () {
    if (rec.state === 'recording') stopRecording(); else startRecording();
  });
  redoBtn.addEventListener('click', function () {
    if (busy || finished || ['requesting', 'recording', 'stopping'].indexOf(rec.state) >= 0) return;
    clearRecording(); startRecording();
  });
  transcribeBtn.addEventListener('click', transcribeRecording);
  /* ---------- 浏览器 TTS：用户点击播放；能力/音色失败只更新提示 ---------- */
  var tts = { synth: window.speechSynthesis, utterance: null, token: 0, timer: null };
  function chineseVoices() {
    try { return tts.synth.getVoices().filter(function (voice) { return /^zh([_-]|$)/i.test(voice.lang); }); }
    catch (e) { return []; }
  }
  function updateTtsHint() {
    if (tts.utterance) return;
    if (!tts.synth || typeof window.SpeechSynthesisUtterance === 'undefined') {
      replayBtn.disabled = true;
      ttsHint.textContent = '此浏览器不支持语音播报，可继续文字面试';
    } else {
      ttsHint.textContent = chineseVoices().length ? '点击「朗读问题」播放中文语音' : '暂未检测到中文音色，请稍后重试或安装系统中文语音；可继续文字面试';
    }
  }
  function stopQuestionSpeech() {
    tts.token++;
    clearTimeout(tts.timer); tts.timer = null;
    tts.utterance = null;
    try { if (tts.synth) tts.synth.cancel(); } catch (e) { /* 文字流程独立 */ }
    replayBtn.textContent = '🔊 朗读问题';
    replayBtn.setAttribute('aria-pressed', 'false');
    updateTtsHint();
  }
  replayBtn.addEventListener('click', function () {
    if (tts.utterance) { stopQuestionSpeech(); return; }
    if (finished || busy || voicePending()) { showToast('请等待当前操作完成后再朗读问题'); return; }
    if (!tts.synth || typeof window.SpeechSynthesisUtterance === 'undefined') { updateTtsHint(); return; }
    var voices = chineseVoices();
    if (!voices.length) { updateTtsHint(); return; }
    stopQuestionSpeech();
    voicePlayer.pause();
    var token = tts.token;
    try {
      var utterance = new SpeechSynthesisUtterance(questionTextEl.textContent);
      tts.utterance = utterance; // 保持引用直到完成，避免部分浏览器提前回收
      utterance.lang = 'zh-CN';
      utterance.voice = voices.find(function (voice) { return /^zh[-_]CN$/i.test(voice.lang); }) || voices[0];
      utterance.rate = 1;
      function finish(message) {
        if (token !== tts.token) return;
        stopQuestionSpeech();
        if (message) ttsHint.textContent = message;
      }
      utterance.onstart = function () {
        if (token !== tts.token) return;
        clearTimeout(tts.timer);
        ttsHint.textContent = '正在朗读问题，点击按钮可停止';
        tts.timer = setTimeout(function () { finish('播报超时，可重试或继续文字面试'); }, 180000);
      };
      utterance.onend = function () { finish('朗读完成，可再次播放'); };
      utterance.onerror = function () { finish('语音播报失败，可重试或继续文字面试'); };
      replayBtn.textContent = '⏹ 停止朗读';
      replayBtn.setAttribute('aria-pressed', 'true');
      ttsHint.textContent = '正在启动语音播报…';
      tts.timer = setTimeout(function () { finish('未能启动语音播报，可重试或继续文字面试'); }, 8000);
      tts.synth.speak(utterance);
    } catch (e) {
      stopQuestionSpeech(); ttsHint.textContent = '语音播报不可用，可继续文字面试';
    }
  });
  if (tts.synth && tts.synth.addEventListener) tts.synth.addEventListener('voiceschanged', updateTtsHint);
  voicePlayer.addEventListener('play', stopQuestionSpeech);
  updateTtsHint();

  window.addEventListener('pagehide', function () { saveDraft(); checkpoint(); stopQuestionSpeech(); clearRecording(); });
  document.addEventListener('visibilitychange',function () { if (document.hidden) { saveDraft(); checkpoint(); } });
  window.addEventListener('pageshow',function (event) { if (event.persisted) { saveDraft(); recoverState(); } });
  syncControls();


  var compact=window.matchMedia('(max-width:640px)');
  var controls=document.querySelector('.iv-controls'),voiceCard=document.querySelector('.voice-card');
  var originalParent=controls && controls.parentNode;
  function placeControls(){if(!controls||!voiceCard)return;if(compact.matches)voiceCard.appendChild(controls);else originalParent.appendChild(controls);}
  placeControls();compact.addEventListener('change',placeControls);
  var keyboardTimer; if(window.visualViewport)window.visualViewport.addEventListener('resize',function(){clearTimeout(keyboardTimer);keyboardTimer=setTimeout(function(){if(document.activeElement===answerInput)answerInput.scrollIntoView({block:'center'});},100);});
  /* ---------- 跳过此题：提交跳过占位回答 ---------- */
  skipBtn.addEventListener("click", function () {
    if (busy || finished) { showToast(busy ? "AI 正在处理，请稍候" : "本场面试已结束"); return; }
    submitAnswer("（候选人选择跳过此题）", true);
  });

  /* ---------- 结束面试：焦点留在确认窗口，失败提示持续显示 ---------- */
  var modalReturnFocus = null, modalBackground = [];
  function closeEndModal() {
    if (confirmEndBtn.disabled) return;
    endModal.classList.remove('is-open'); endModal.hidden=true;
    modalBackground.forEach(function (entry) { entry.el.inert = entry.inert; });
    modalBackground = [];
    if (modalReturnFocus && modalReturnFocus.isConnected) modalReturnFocus.focus();
  }
  function openEndModal() {
    modalReturnFocus = document.activeElement;
    document.getElementById('endError').textContent = '';
    modalBackground = Array.from(document.body.children).filter(function (node) { return node !== endModal; }).map(function (node) { var entry={el:node,inert:node.inert}; node.inert=true; return entry; });
    endModal.hidden=false; endModal.classList.add('is-open'); cancelEndBtn.focus();
  }
  endBtn.addEventListener('click', function () { if (finished) viewReport(); else openEndModal(); });
  cancelEndBtn.addEventListener('click',closeEndModal);
  endModal.addEventListener('click',function (event) { if (event.target===endModal) closeEndModal(); });
  endModal.tabIndex = -1;
  document.addEventListener('keydown',function (event) {
    if (!endModal.classList.contains('is-open')) return;
    if (event.key==='Escape') { event.preventDefault(); closeEndModal(); }
    if (event.key==='Tab') {
      var buttons=Array.from(endModal.querySelectorAll('button:not(:disabled),[href],input:not(:disabled),[tabindex="0"]')).filter(function (node) { return node.getClientRects().length; });
      if (!buttons.length) { event.preventDefault(); endModal.focus(); return; }
      var first=buttons[0],last=buttons[buttons.length-1];
      if (event.shiftKey && (document.activeElement===first || !endModal.contains(document.activeElement))) { event.preventDefault();last.focus(); }
      else if (!event.shiftKey && (document.activeElement===last || document.activeElement===endModal)) { event.preventDefault();first.focus(); }
    }
  });
  document.addEventListener('focusin',function (event) {
    if (endModal.classList.contains('is-open') && !endModal.contains(event.target)) {
      if (confirmEndBtn.disabled) endModal.focus(); else cancelEndBtn.focus();
    }
  });
  confirmEndBtn.addEventListener('click',function () {
    if (busy || finished || confirmEndBtn.disabled) return;
    saveDraft(); finished=true; ending=true; confirmEndBtn.disabled=true; cancelEndBtn.disabled=true;
    document.getElementById('endError').textContent='正在保存并结束面试，请稍候…';
    stopQuestionSpeech(); clearRecording(); syncControls(); endModal.focus();
    var endController=window.AbortController ? new AbortController() : null;
    var endTimer=setTimeout(function () { if (endController) endController.abort(); },15000);
    fetch('/api/interview/end', {
      signal:endController ? endController.signal : undefined,
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:session.session_id})
    }).then(function (response) {
      return response.json().then(function (data) { if (!response.ok || !data.finished) throw new Error(data.error || '结束面试失败，请重试'); });
    }).then(function () { drafts.clear();checkpoint();viewReport(); })
      .catch(function (error) {
        finished=false;ending=false;confirmEndBtn.disabled=false;cancelEndBtn.disabled=false;syncControls();
        document.getElementById('endError').textContent=error.name==='AbortError' ? '结束结果暂未确认，草稿仍保留，请点击重试。' : error.name==='SyntaxError' ? '连接返回异常，草稿仍保留，请重试。' : error.message && error.message!=='Failed to fetch' ? error.message : '连接暂时中断，回答已保留，请再次点击结束面试。';
        confirmEndBtn.focus();
      }).finally(function () { clearTimeout(endTimer); });
  });

  setState("idle", "请在下方文字框输入你的回答", "🎙️");
  updateProgress(session.progress);
  showCompletion();
  recoverState();
 }
 if(window.Account) Account.ready.then(boot); else boot();
})();
