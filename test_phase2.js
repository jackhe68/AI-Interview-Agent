/* 第二阶段验收测试：真实调用 Flask + DeepSeek，不打印任何密钥 */
const BASE = "http://127.0.0.1:5001";

async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const data = await r.json().catch(() => ({}));
  return { status: r.status, data };
}

(async () => {
  console.log("=== 1. 启动面试 ===");
  const start = await jpost(BASE + "/api/interview/start", { job: "Java 后端", level: "校招标准" });
  console.log("status:", start.status);
  console.log("session_id:", start.data.session_id ? start.data.session_id.slice(0, 8) + "…" : null);
  console.log("progress:", JSON.stringify(start.data.progress));
  console.log("首题:", start.data.question);
  if (start.status !== 200 || !start.data.session_id) {
    console.log("!! 启动失败，终止测试"); return;
  }
  const sid = start.data.session_id;

  const answers = [
    "我是大三计算机专业学生，熟悉Java和Spring，做过一个电商秒杀项目，用Redis缓存和消息队列削峰。",
    "HashMap底层是数组加链表，put时先算hash定位桶，链表尾插，节点多了会转红黑树。",
    "JVM内存有堆、栈、方法区、程序计数器，堆会OOM。",
    "ArrayList基于数组随机访问快，LinkedList基于链表插入快。",
    "线程安全是多线程下状态正确，synchronized是JVM锁，ReentrantLock是API锁。",
    "索引底层是B+树，like前置模糊查询会失效。"
  ];

  for (let i = 0; i < answers.length; i++) {
    console.log(`\n=== ${i + 2}. 提交第 ${i + 1} 个回答 ===`);
    const a = await jpost(BASE + "/api/interview/answer", { session_id: sid, answer: answers[i] });
    console.log("status:", a.status, "| progress:", JSON.stringify(a.data.progress), "| finished:", a.data.finished);
    console.log("AI简评:", a.data.comment);
    console.log("下一问:", a.data.next_question ? a.data.next_question : "（无，面试结束）");
    if (a.status !== 200) { console.log("!! 异常状态，终止"); return; }
    if (a.data.finished) { console.log(">>> 面试正常结束"); break; }
  }

  console.log("\n=== 错误用例 ===");

  // 空回答
  const empty = await jpost(BASE + "/api/interview/answer", { session_id: sid, answer: "   " });
  console.log("空回答:", empty.status, empty.data.error);

  // 无效 session
  const bad = await jpost(BASE + "/api/interview/answer", { session_id: "nope", answer: "test" });
  console.log("无效ID:", bad.status, bad.data.error);

  // 已结束会话再次提交
  const afterEnd = await jpost(BASE + "/api/interview/answer", { session_id: sid, answer: "again" });
  console.log("结束后提交:", afterEnd.status, afterEnd.data.error);

  // 重复提交（并发）—— 新建一个会话做并发测试
  const s2 = await jpost(BASE + "/api/interview/start", { job: "前端开发", level: "实习入门" });
  const sid2 = s2.data.session_id;
  const [r1, r2] = await Promise.all([
    jpost(BASE + "/api/interview/answer", { session_id: sid2, answer: "重复测试A" }),
    jpost(BASE + "/api/interview/answer", { session_id: sid2, answer: "重复测试B" })
  ]);
  console.log("并发提交1:", r1.status, "| 并发提交2:", r2.status, r2.data.error || "(成功)");
  console.log("(期望：一个 200，一个 409 重复提交)");
})();
