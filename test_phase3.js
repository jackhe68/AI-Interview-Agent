/* 第三阶段验收测试：完整面试 → DB 持久化 → 真实评分报告 → 重启后读取 → 新旧隔离 */
const BASE = "http://127.0.0.1:5001";
async function jpost(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return { status: r.status, data: await r.json().catch(() => ({})) };
}
async function jget(url) {
  const r = await fetch(url);
  return { status: r.status, data: await r.json().catch(() => ({})) };
}

(async () => {
  console.log("=== 1. 开始 Java 面试 ===");
  const start = await jpost(BASE + "/api/interview/start", { job: "Java 后端", level: "校招标准" });
  const sid = start.data.session_id;
  console.log("session:", sid.slice(0, 8), "| 首题:", start.data.question);
  if (!sid) { console.log("!! 启动失败"); return; }

  const answers = [
    "我是大三学生，熟悉Java和Spring，做过电商秒杀项目，用Redis缓存和消息队列削峰。",
    "HashMap底层是数组加链表，put时算hash定位桶，链表尾插，节点多转红黑树。",
    "JVM内存有堆、栈、方法区、程序计数器，堆会OOM。",
    "ArrayList基于数组随机访问快，LinkedList基于链表插入快。",
    "线程安全是多线程下状态正确，synchronized是JVM锁，ReentrantLock是API锁。",
    "索引底层是B+树，like前置模糊查询会失效。"
  ];

  let finished = false;
  for (let i = 0; i < answers.length; i++) {
    const a = await jpost(BASE + "/api/interview/answer", { session_id: sid, answer: answers[i] });
    console.log(`  答${i + 1}: status=${a.status} progress=${JSON.stringify(a.data.progress)} finished=${a.data.finished}`);
    if (a.status !== 200) { console.log("!! 异常:", a.data.error); return; }
    if (a.data.finished) { finished = true; console.log("  >>> 面试正常结束"); break; }
  }
  if (!finished) { console.log("!! 未正常结束"); return; }

  console.log("\n=== 2. 读取真实评分报告 ===");
  const rep = await jget(BASE + "/api/report/" + sid);
  console.log("status:", rep.status, "| available:", rep.data.available);
  if (rep.data.available) {
    const s = rep.data.scores;
    console.log("综合分:", s.overall, "| 等级:", rep.data.grade);
    console.log("维度: 专业知识", s.knowledge, "完整性", s.completeness, "表达", s.expression, "岗位相关", s.job_relevance);
    console.log("加权校验:", Math.round(s.knowledge * 0.4 + s.completeness * 0.3 + s.expression * 0.2 + s.job_relevance * 0.1) === s.overall ? "✓" : "✗");
    console.log("薄弱点数:", rep.data.weaknesses.length, "| 首:", rep.data.weaknesses[0] && rep.data.weaknesses[0].topic);
    console.log("建议数:", rep.data.suggestions.length);
    console.log("总评:", (rep.data.overall_comment || "").slice(0, 60));
    console.log("免责声明:", rep.data.disclaimer ? "✓" : "✗");
  } else { console.log("!! 报告不可用:", rep.data); return; }

  console.log("\n=== 3. 验证旧报告未受影响（再开一场前端面试，确认旧报告仍可读）===");
  const s2 = await jpost(BASE + "/api/interview/start", { job: "前端开发", level: "实习入门" });
  const sid2 = s2.data.session_id;
  console.log("新面试 session:", sid2.slice(0, 8), "≠ 旧:", sid2 !== sid ? "✓" : "✗");
  const repOldAgain = await jget(BASE + "/api/report/" + sid);
  console.log("旧报告重读:", repOldAgain.status, repOldAgain.data.available ? "✓ 仍可读" : "✗", "| 综合分仍为", repOldAgain.data.scores && repOldAgain.data.scores.overall);
  const repNew = await jget(BASE + "/api/report/" + sid2);
  console.log("新面试报告(未结束):", repNew.data.available ? "意外可用" : "✓ 未结束无报告 / " + (repNew.data.reason || repNew.data.error));

  console.log("\n=== 测试完成。请手动重启 Flask 后再次运行第 2 步验证持久化（脚本将退出）===");
  console.log("旧 session_id（用于重启后验证）:", sid);
})();
