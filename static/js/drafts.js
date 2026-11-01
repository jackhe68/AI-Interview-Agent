/* Answer text only, on this browser for 24 hours. No audio or resume form storage. */
(function () {
  'use strict';
  var PREFIX = 'iv-answer-draft-v1:';
  var TTL = 24 * 60 * 60 * 1000;
  window.InterviewDrafts = function (sid) {
    var identity=window.Account && Account.scope;
    var namespace = identity && identity!=='legacy' ? 'iv-answer-draft-v2:'+encodeURIComponent(identity)+':'+encodeURIComponent(sid)+':' : PREFIX+encodeURIComponent(sid)+':';
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
    this.importLegacy = function(question) {
      if(!identity || identity.indexOf('guest:')!==0 || !window.Account || !Account.ownsPage())return;
      try {var legacy=PREFIX+encodeURIComponent(sid)+':'+question,item=JSON.parse(localStorage.getItem(legacy)||'null');
       if(item && typeof item.text==='string' && Date.now()-item.updated_at<TTL && !localStorage.getItem(namespace+question)){localStorage.setItem(namespace+question,JSON.stringify(item));localStorage.removeItem(legacy);}
      }catch(e){}
    };
    this.put = function (question, text, pending) {
      if(window.Account && !Account.ownsPage())return;
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
      Object.keys(localStorage).filter(function (key) { return key.indexOf(PREFIX) === 0 || key.indexOf('iv-answer-draft-v2:') === 0; }).forEach(function (key) {
        try {
          var item = JSON.parse(localStorage.getItem(key));
          if (!item || typeof item.updated_at !== 'number' || Date.now()-item.updated_at > TTL) localStorage.removeItem(key);
        } catch (error) { localStorage.removeItem(key); }
      });
    } catch (error) { this.available = false; }
  };
})();
