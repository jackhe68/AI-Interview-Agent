/* Answer text only, on this browser for 24 hours. No audio or resume form storage. */
(function () {
  'use strict';
  var PREFIX = 'iv-answer-draft-v1:';
  var TTL = 24 * 60 * 60 * 1000;
  window.InterviewDrafts = function (sid) {
    var namespace = PREFIX + encodeURIComponent(sid) + ':';
    var memory = {};
    var self = this;
    this.available = true;
    function readKey(key) {
      if (memory[key] !== undefined) return memory[key];
      try { return localStorage.getItem(key); }
      catch (error) { self.available = false; return memory[key] || null; }
    }
    this.get = function (question) {
      var key = namespace + question;
      try {
        var item = JSON.parse(readKey(key) || 'null');
        if (!item) return null;
        if (typeof item.text !== 'string' || !Number.isFinite(item.updated_at) || Date.now()-item.updated_at > TTL) {
          this.remove(question); return null;
        }
        return item;
      } catch (error) { return null; }
    };
    this.put = function (question, text, pending) {
      var key = namespace + question;
      var item = {text:text, pending:pending || null, updated_at:Date.now()};
      if (!text && !pending) { this.remove(question); return; }
      memory[key] = JSON.stringify(item);
      try { localStorage.setItem(key, memory[key]); }
      catch (error) { this.available = false; }
    };
    this.remove = function (question) {
      var key = namespace + question; delete memory[key];
      try { localStorage.removeItem(key); } catch (error) { self.available = false; }
    };
    this.clear = function () {
      Object.keys(memory).forEach(function (key) { delete memory[key]; });
      try {
        Object.keys(localStorage).filter(function (key) { return key.indexOf(namespace) === 0; })
          .forEach(function (key) { localStorage.removeItem(key); });
      } catch (error) { self.available = false; }
    };
    try {
      Object.keys(localStorage).filter(function (key) { return key.indexOf(PREFIX) === 0; }).forEach(function (key) {
        try {
          var item = JSON.parse(localStorage.getItem(key));
          if (!item || typeof item.updated_at !== 'number' || Date.now()-item.updated_at > TTL) localStorage.removeItem(key);
        } catch (error) { localStorage.removeItem(key); }
      });
    } catch (error) { this.available = false; }
  };
})();
