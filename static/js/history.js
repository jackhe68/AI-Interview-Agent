/* ============================================================
   AI Interview Agent · 历史面试列表脚本
   - GET /api/interviews 读取历史记录（按开始时间倒序）
   - 渲染列表：岗位/难度/时间/状态/综合评分
   - 已完成且有回答 → 可点击「查看报告」跳转 /report?id=<sid>
   - 空状态展示
   ============================================================ */
(function () {
  "use strict";

  var listEl = document.getElementById("historyList");
  var emptyEl = document.getElementById("historyEmpty");

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    return iso.replace("T", " ").slice(0, 16);
  }
  function statusInfo(status) {
    if (status === "finished") return { text: "已完成", cls: "is-done" };
    if (status === "ended") return { text: "提前结束", cls: "is-ended" };
    return { text: "进行中", cls: "is-active" };
  }
  function scoreGrade(s) {
    if (s == null) return null;
    if (s >= 90) return "A";
    if (s >= 80) return "B+";
    if (s >= 70) return "B";
    if (s >= 60) return "C";
    return "D";
  }

  function renderRow(item) {
    var st = statusInfo(item.status);
    var scoreHtml;
    if (item.overall_score != null) {
      scoreHtml = '<div class="h-score">'
        + '<span class="h-score__num">' + item.overall_score + '</span>'
        + '<span class="h-score__grade">' + (scoreGrade(item.overall_score) || "") + '</span>'
        + '</div>';
    } else {
      scoreHtml = '<div class="h-score h-score--none">暂无评分</div>';
    }

    var actionHtml;
    if (item.can_view_report) {
      actionHtml = '<a class="btn btn--outline btn--sm" href="/report?id=' + encodeURIComponent(item.id) + '">查看报告</a>'
        + '<button class="btn btn--ghost btn--sm h-del" data-id="' + esc(item.id) + '" title="删除该记录">删除</button>';
    } else if (item.status === "active") {
      actionHtml = '<span class="badge">进行中</span>'
        + '<button class="btn btn--ghost btn--sm h-del" data-id="' + esc(item.id) + '" title="删除该记录">删除</button>';
    } else {
      actionHtml = '<span class="badge">无有效回答</span>'
        + '<button class="btn btn--ghost btn--sm h-del" data-id="' + esc(item.id) + '" title="删除该记录">删除</button>';
    }

    return '<div class="glass-card history-row" data-id="' + esc(item.id) + '">'
      + '<div class="h-main">'
      + '<div class="h-title">' + esc(item.job) + ' <span class="h-diff">· ' + esc(item.difficulty) + '</span></div>'
      + '<div class="h-meta">'
      + (item.selection && item.selection.major ? '<span class="badge">' + esc(item.selection.major) + '</span>' : '')
      + '<span class="h-date">' + fmtDate(item.started_at) + '</span>'
      + '<span class="badge ' + st.cls + '">' + st.text + '</span>'
      + '<span class="badge">答题 ' + item.answered_count + ' 次</span>'
      + '</div>'
      + '</div>'
      + scoreHtml
      + '<div class="h-action">' + actionHtml + '</div>'
      + '</div>';
  }

  /* ---------- 删除：行内二次确认 ---------- */
  function bindDelete() {
    listEl.addEventListener("click", function (e) {
      var delBtn = e.target.closest(".h-del");
      if (!delBtn) return;
      var row = delBtn.closest(".history-row");
      var id = delBtn.getAttribute("data-id");
      var action = row.querySelector(".h-action");
      // 切换为确认态
      action.innerHTML = '<span class="h-confirm-text">确认删除？</span>'
        + '<button class="btn btn--danger btn--sm h-del-yes" data-id="' + esc(id) + '">删除</button>'
        + '<button class="btn btn--ghost btn--sm h-del-no">取消</button>';
      action.classList.add("h-action--confirm");
    });

    listEl.addEventListener("click", function (e) {
      if (e.target.closest(".h-del-no")) {
        var row = e.target.closest(".history-row");
        restoreAction(row);
        return;
      }
      var yes = e.target.closest(".h-del-yes");
      if (!yes) return;
      var id = yes.getAttribute("data-id");
      var row = yes.closest(".history-row");
      yes.disabled = true;
      yes.textContent = "删除中…";
      fetch("/api/interview/" + encodeURIComponent(id), { method: "DELETE" })
        .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, data: d }; }); })
        .then(function (r) {
          if (!r.ok) {
            showToast(r.data && r.data.error ? r.data.error : "删除失败");
            restoreAction(row);
            return;
          }
          // A restored question may quote background facts; clear this record's cache too.
          try {
            var cached = JSON.parse(localStorage.getItem('iv-session') || 'null');
            if (cached && cached.session_id === id) localStorage.removeItem('iv-session');
          } catch (error) {}
          row.style.transition = "opacity .25s ease, transform .25s ease, height .25s ease";
          row.style.opacity = "0";
          row.style.transform = "translateX(-12px)";
          setTimeout(function () {
            row.remove();
            if (!listEl.querySelector(".history-row")) renderEmpty();
          }, 250);
          if (window.InterviewDrafts) new InterviewDrafts(id).clear();
          showToast("已删除该面试记录及本机草稿");
        })
        .catch(function () {
          showToast("网络异常，删除失败");
          restoreAction(row);
        });
    });
  }

  function restoreAction(row) {
    var id = row.getAttribute("data-id");
    var action = row.querySelector(".h-action");
    action.classList.remove("h-action--confirm");
    // 重新渲染该行 action：简单做法——重新拉取列表
    load();
  }

  function renderEmpty() {
    listEl.innerHTML = "";
    emptyEl.classList.remove("is-hidden");
  }

  function renderList(items) {
    if (!items || !items.length) { renderEmpty(); return; }
    emptyEl.classList.add("is-hidden");
    listEl.innerHTML = items.map(renderRow).join("");
  }

  function load() {
    fetch("/api/interviews")
      .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, data: d }; }); })
      .then(function (r) {
        if (!r.ok || !r.data || !r.data.items) {
          showToast(r.data && r.data.error ? r.data.error : "历史记录加载失败");
          renderEmpty();
          return;
        }
        renderList(r.data.items);
      })
      .catch(function () {
        showToast("网络异常，无法连接服务器");
        renderEmpty();
      });
  }

  window.addEventListener("load", function () {
    bindDelete();
    load();
  });
})();
