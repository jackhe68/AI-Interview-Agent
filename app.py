# -*- coding: utf-8 -*-
"""
AI Interview Agent · Flask 后端（第三阶段）
------------------------------------------
- 页面路由：/ /interview /report
- 面试接口：
    POST /api/interview/start   开始面试（岗位 + 难度 → 首题），写入 interviews + messages
    POST /api/interview/answer  提交回答（AI 简评 + 追问/下一题/结束），全程写入 messages
    POST /api/interview/end     提前结束，生成报告
    GET  /api/report/<id>       读取（或按需生成）AI 评分报告
- 面试控制（Python 状态机）：3 道主问题 × 每题最多 1 次追问
- 持久化：SQLite（database.py），Flask 重启后仍可读取历史面试与报告
- 真实评分：调用 DeepSeek 基于实际回答生成结构化 JSON，Python 验证并按权重计算综合分
- DeepSeek 客户端配置复用 interview_core.py（.env 提供 DEEPSEEK_API_KEY）
"""
import json
import math
import hashlib
import os
import re
import threading
import time
import uuid
from io import BytesIO

import database as dbm
from interview_time import timestamp
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file, g, has_request_context
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError
from ai_limits import MAX_OUTPUT_TOKENS
from interview_catalog import catalog, selection_for, selection_prompt
from candidate_background import normalize_background, prompt_context
from practice_feedback import (REPORT_PRACTICE_INSTRUCTION, normalize_practice,
                               report_practice, answered_questions, format_feedback, coverage_of, report_scores, SKIP_ANSWER)

load_dotenv()
dbm.init_db()
from speech_temp import cleanup as cleanup_temporary_audio
cleanup_temporary_audio(dbm)  # Startup only: no requests are active yet.

# ------------------------------------------------------------------
# 配置（不打印、不外显任何密钥）
# ------------------------------------------------------------------
API_KEY = os.getenv("DEEPSEEK_API_KEY")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
BASE_URL = "https://api.deepseek.com"
REQUEST_TIMEOUT = 60
MAX_ANSWER_CHARS = 4000
MAIN_QUESTION_COUNT = 3
MAX_FOLLOWUP_PER_Q = 1

# 语音上传限制
ALLOWED_AUDIO_EXT = {".webm", ".mp3", ".wav", ".m4a", ".ogg", ".mp4", ".aac"}
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25MB

# 评分权重
SCORE_WEIGHTS = {
    "knowledge": 0.4,
    "completeness": 0.3,
    "expression": 0.2,
    "job_relevance": 0.1,
}
REPORT_DISCLAIMER = "本报告由 AI 基于练习回答生成，仅用于求职训练反馈，并非客观招聘评价。"

client = None
if API_KEY:
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=REQUEST_TIMEOUT,max_retries=0)

app = Flask(__name__, template_folder=".", static_folder="static")
app.config["TEMPLATES_AUTO_RELOAD"] = True
from asset_delivery import install as install_asset_delivery
install_asset_delivery(app)
app.config["MAX_CONTENT_LENGTH"] = MAX_AUDIO_BYTES  # 超过上限整体拒绝（413）

# ------------------------------------------------------------------
# 面试会话（内存，用于 busy 锁与上下文；DB 为持久真源，重启可重建）
# ------------------------------------------------------------------
SESSIONS = {}
SPEECH_REVIEW_LOCK = threading.Lock()
REPORT_STATE_LOCK = threading.Lock()
REPORT_INFLIGHT = set()
ANSWER_STATE_LOCK = threading.Lock()
REPORT_JOB_LOCK = threading.Lock()
REPORT_JOB_SERVICE = None


class APIError(Exception):
    """业务异常：code 为 HTTP 状态码，message 为可直接展示给用户的友好提示"""
    def __init__(self, code, message, retry_after=None, retryable=False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after
        self.retryable = retryable


def interviewer_system_prompt(job, level, background=None, selection=None):
    return (
        f"你是一名专业、友善的{job}面试官，正在对大学生实习求职者进行{level}难度的模拟面试。"
        "提问用简洁清晰的中文口语，每次只提一个问题，不要提前公布参考答案，"
        "不要闲聊，不要复述候选人说过的话。"
    ) + selection_prompt(selection, job) + prompt_context(background)


def call_deepseek(messages, max_tokens=MAX_OUTPUT_TOKENS):
    def fail(code,message,kind,retry_after=None,retryable=False):
        context=has_request_context()
        if context and retry_after is not None:g.provider_retry_after=retry_after
        app.logger.warning(json.dumps(dict(event='ai_failure',kind=kind,status=code,
            request_id=g.get('request_id') if context else None,task_id=g.get('report_task_id') if context else None)))
        raise APIError(code,message,retry_after=retry_after,retryable=retryable) from None
    if client is None:
        fail(503,'AI服务尚未就绪，请联系维护人员；已有练习记录仍保留','not_configured')
    ai_started=time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=messages, max_tokens=max_tokens,
        )
        choices=getattr(resp,'choices',None)
        if not isinstance(choices,(list,tuple)) or not choices:fail(502,'AI返回结果不完整，请稍后手动重试','invalid_response')
        choice=choices[0]
        finish=getattr(choice,'finish_reason',None)
        if finish=='length':fail(502,'AI回复达到长度上限，内容未完整生成，请重试','truncated')
        if finish!='stop':fail(502,'AI未返回完整的文字结果，请稍后手动重试','invalid_response')
        content=getattr(getattr(choice,'message',None),'content',None)
        if not isinstance(content,str):fail(502,'AI返回结果格式不正确，请稍后手动重试','invalid_response')
        if not content.strip():fail(502,'AI返回内容为空，请重试','empty_response')
        try:content.encode('utf-8')
        except UnicodeError:fail(502,'AI返回文字编码不完整，请稍后重试','invalid_response')
        if any(ord(char)<32 and char not in '\n\r\t' for char in content):fail(502,'AI返回文字格式不正确，请稍后重试','invalid_response')
        return content.strip()
    except APITimeoutError:
        fail(504,'AI响应超时，请核对已保存结果后手动重试','timeout')
    except APIConnectionError:
        fail(502,'AI连接暂时中断，请核对已保存结果后手动重试','connection')
    except APIStatusError as exc:
        status=exc.status_code
        if status in (401,403):fail(502,'AI服务暂时无法验证访问权限，请联系维护人员','authentication')
        if status==402:fail(503,'AI服务额度暂时不足，请联系维护人员；已有记录仍保留','provider_budget')
        if status==429:
            header=(getattr(exc.response,'headers',{}) or {}).get('retry-after','')
            retry=60
            if isinstance(header,str) and len(header)<=6 and header.isascii() and header.isdigit():retry=max(1,min(int(header),300))
            fail(429,'AI服务暂时繁忙，请按提示稍后重试', 'rate_limited',retry_after=retry,retryable=True)
        fail(502,'AI服务暂时不可用，请稍后手动重试','provider_status')
    except APIError:
        raise
    except Exception:
        fail(502,'AI服务返回异常，请稍后手动重试','unexpected_response')
    finally:
        if has_request_context():g.ai_ms=g.get('ai_ms',0)+(time.perf_counter()-ai_started)*1000


def extract_json(text):
    if not isinstance(text,str):return None
    text = text.strip()
    if text.startswith('```'):
        fenced=re.fullmatch(r'```(?:json)?\s*(.*?)\s*```',text,re.S|re.I)
        if not fenced:return None
        text=fenced.group(1)
    def unique_object(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate_json_key')
            result[key]=value
        return result
    try:
        value=json.loads(text,object_pairs_hook=unique_object)
        return value if isinstance(value,dict) else None
    except Exception:
        return None


def build_answer_instruction(mode, main_index):
    if mode == "followup":
        return (
            "请针对候选人上一个回答中的薄弱或含糊之处，提出 1 个简短有力的追问。"
            "追问必须与刚才的回答内容相关，不要开新话题。"
        )
    if mode == "next_main":
        return (
            f"候选人已完成第 {main_index + 1} 道主问题（含追问）。"
            f"请提出第 {main_index + 2} 道全新的主面试问题，"
            "换一个该岗位的核心考点，不要与之前的问题重复。"
        )
    return ""


def ask_next(session, mode):
    instruction = build_answer_instruction(mode, session["main_index"])
    if mode == "finish":
        question_rule = (
            '这是本场最后一问，之后面试结束。请输出 JSON（不要输出其他内容）：'
            '{"comment": "对候选人刚才回答的 1~2 句简评", "next_question": ""}'
        )
    else:
        question_rule = (
            "请输出 JSON（不要输出其他内容，一次只问一个问题）："
            '{"comment": "对候选人刚才回答的 1~2 句简评，指出亮点或不足", '
            '"next_question": "按上述要求生成的下一个问题"}'
        )
    question_rule += (
        'comment 必须对应刚才的实际回答，指出具体亮点、错误或遗漏，不能只说含糊或多练习。'
        '可增加 next_step 字段给一项具体改进动作。'
        + ('当前还要追问，只指出观察到的问题，不泄露追问答案；不要输出参考答案。' if mode == 'followup' else
           '增加 answer_outline（回答步骤字符串数组）和 reference_answer（本题参考回答）字段。'
           '参考回答只复盘刚完成的问题，不要泄露下一个问题答案，也不要编造候选人的经历。')
    )
    messages = [
        {"role": "system", "content": interviewer_system_prompt(session["job"], session["level"], dbm.get_background(session['id']), dbm.get_selection(session['id']))},
        *session["history"],
        {"role": "user", "content": instruction + question_rule},
    ]
    raw = call_deepseek(messages)
    data = extract_json(raw)
    if data and isinstance(data, dict):
        if session.get('answer_skipped'):
            data['comment']='已跳过本题；未提供实际回答，暂不评价该题能力。'
            data.pop('next_step',None)
        comment = format_feedback(data, mode)
        question = data.get("next_question")
        question = question.strip() if isinstance(question, str) else ''
        if mode != 'finish' and not question:
            raise APIError(502, 'AI 未生成下一题，请重试；当前回答仍保留')
        return comment, (question if question and mode != "finish" else None)
    raise APIError(502, 'AI 点评格式不完整，请重试；当前回答仍保留')


def progress_of(session):
    return {
        "main": min(session["main_index"] + 1, MAIN_QUESTION_COUNT),
        "total": MAIN_QUESTION_COUNT,
        "type": "followup" if session["phase"] == "followup" else "main",
    }


# ------------------------------------------------------------------
# 会话与 DB 的同步
# ------------------------------------------------------------------
def load_session(session_id):
    """优先内存；缺失时从 DB 重建（支持 Flask 重启后继续/读取）。"""
    if session_id in SESSIONS:
        return SESSIONS[session_id]
    iv = dbm.get_interview(session_id)
    if not iv:
        return None
    msgs = dbm.get_messages(session_id)
    # Match the live dialogue: saved coaching/solutions are not candidate answers.
    history = [{"role": m["role"], "content": m["content"]} for m in msgs if m['message_type'] != 'comment']
    # 推断 phase：最后一条 assistant 消息若是追问则处于 followup 阶段
    phase = "main"
    for m in reversed(msgs):
        if m["role"] == "assistant":
            phase = "followup" if m["message_type"] == "followup" else "main"
            break
    session = {
        "id": iv["id"],
        "job": iv["job"],
        "level": iv["difficulty"],
        "selection": dbm.get_selection(session_id),
        "main_index": max(iv["current_question"] - 1, 0),
        "phase": phase,
        "followup_used": iv["followup_count"],
        "history": history,
        "finished": iv["status"] in ("finished", "ended"),
        "started_at": timestamp(iv["started_at"]),  # 从持久记录恢复实际开始时间
        "busy": False,
    }
    SESSIONS[session_id] = session
    return session


# ------------------------------------------------------------------
# 真实 AI 评分
# ------------------------------------------------------------------
def build_transcript(messages):
    lines = []
    for m in messages:
        if m["role"] == "assistant":
            label = {"main_question": "问题", "followup": "追问", "comment": "点评"}.get(m["message_type"], "面试官")
            lines.append(f"【{label}】{m['content']}")
        else:
            lines.append(f"【回答】{m['content']}")
    return "\n".join(lines)


def clamp_score(v):
    try:
        v = int(round(float(v)))
    except Exception:
        v = 0
    return max(0, min(100, v))


def grade_of(overall):
    if overall >= 90:
        return "A · 优秀"
    if overall >= 80:
        return "B+ · 良好"
    if overall >= 70:
        return "B · 中上"
    if overall >= 60:
        return "C · 合格"
    return "D · 待提升"


def generate_report(interview_id):
    """Reuse saved reports and allow only one generation per interview."""
    with REPORT_STATE_LOCK:
        saved = dbm.get_report(interview_id)
        if saved:
            return saved
        if interview_id in REPORT_INFLIGHT:
            raise APIError(202, '报告正在生成，请稍候')
        REPORT_INFLIGHT.add(interview_id)
    try:
        return _generate_report(interview_id)
    finally:
        with REPORT_STATE_LOCK:
            REPORT_INFLIGHT.discard(interview_id)


def _generate_report(interview_id):
    """调用 DeepSeek 基于实际回答生成评分报告，落库并返回 dict。失败抛 APIError。"""
    iv = dbm.get_interview(interview_id)
    if not iv:
        raise APIError(404, "面试记录不存在")
    messages = dbm.get_messages(interview_id)
    answered = sum(1 for m in messages if m["role"] == "user")
    if answered == 0:
        raise APIError(400, "本场面试没有有效回答，无法生成评价")

    # Grade only actual question/answer pairs, excluding AI comments and reference solutions.
    transcript = json.dumps(
        [dict(answer_sequence=p['answer_sequence'], question=p['question'], answer=p['answer'])
         for p in answered_questions(messages)], ensure_ascii=False)
    prompt_user = (
        f"岗位：{iv['job']}\n难度：{iv['difficulty']}\n实际回答数量：{answered}\n\n"
        f"面试记录：\n{transcript}\n\n"
        "请仅输出 JSON（不要输出其他内容），格式如下：\n"
        "{\n"
        '  "knowledge_score": 0到100的整数或null（未观察）,\n'
        '  "completeness_score": 0到100的整数或null（未观察）,\n'
        '  "expression_score": 0到100的整数或null（未观察）,\n'
        '  "job_relevance_score": 0到100的整数或null（未观察）,\n'
        '  "knowledge_summary": "一句话总体评价",\n'
        '  "weaknesses": [{"topic":"练习关注项","answer_sequence":2,"evidence":"回答原文连续摘录","explanation":"基于这段证据的具体说明"}],\n'
        '  "suggestions": ["针对性改进建议"],\n'
        '  "overall_comment": "整场总结"\n'
        "}\n"
        "要求：评分必须基于候选人实际回答内容，薄弱点需对应真实答错或答不全之处，"
        "不得编造未回答问题的评分依据。"
    )
    prompt_user += '\n不得把跳过、缺少举例等同于没有能力。缺乏依据时写覆盖不足，薄弱点不输出伪精确掌握百分比。'
    prompt_user += REPORT_PRACTICE_INSTRUCTION
    prompt_user += selection_prompt(dbm.get_selection(interview_id), iv['job'])
    substantive=[p for p in answered_questions(messages) if p['answer'].strip() and p['answer'].strip()!='（候选人选择跳过此题）']
    unassessed=not substantive
    if unassessed:
        data=dict(knowledge_score=0,completeness_score=0,expression_score=0,job_relevance_score=0,weaknesses=[],suggestions=['选择一道题补充具体回答，再进行练习。'],overall_comment='本场没有足够的实际回答依据，暂不评分；跳过题目不能说明缺乏能力。',knowledge_summary='回答覆盖不足，暂未评分')
    else:
        raw = call_deepseek([
            {"role": "system", "content": "你是资深岗位面试评估专家，根据完整面试记录对大学生求职者进行练习性评价。结合实际岗位评价专业知识，不限于计算机方向。仅基于候选人实际回答评分，不得编造。"},
            {"role": "user", "content": prompt_user},
        ], max_tokens=MAX_OUTPUT_TOKENS)
        data = extract_json(raw)
        if not data or not isinstance(data, dict):
            raise APIError(502, "评分结果解析失败，请稍后重试")
    if not unassessed:
        for key in ('knowledge_score','completeness_score','expression_score','job_relevance_score'):
            if key not in data:raise APIError(502,'评分字段不完整，已保留作答与点评，请稍后重试生成报告')
            value=data.get(key)
            if value is None:continue
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100:
                raise APIError(502,'评分字段不完整，已保留作答与点评，请稍后重试生成报告')
    k = clamp_score(data.get("knowledge_score", 0))
    c = clamp_score(data.get("completeness_score", 0))
    e = clamp_score(data.get("expression_score", 0))
    jr = clamp_score(data.get("job_relevance_score", 0))
    overall = int(round(
        k * SCORE_WEIGHTS["knowledge"]
        + c * SCORE_WEIGHTS["completeness"]
        + e * SCORE_WEIGHTS["expression"]
        + jr * SCORE_WEIGHTS["job_relevance"]
    ))

    pairs={p['answer_sequence']:p for p in substantive}
    weaknesses=[]
    for item in data.get('weaknesses',[]) if isinstance(data.get('weaknesses'),list) else []:
        if not isinstance(item,dict):continue
        seq=item.get('answer_sequence');evidence=item.get('evidence')
        if not isinstance(seq,int) or not isinstance(evidence,str) or not evidence.strip() or seq not in pairs or evidence not in pairs[seq]['answer']:continue
        weaknesses.append(dict(topic=str(item.get('topic','练习关注项'))[:120],score=None,explanation=str(item.get('explanation',''))[:1000],evidence=evidence[:1000],answer_sequence=seq))
    weaknesses=weaknesses[:6]

    suggestions = data.get("suggestions") or []
    if isinstance(suggestions, list):
        suggestions = [str(s).strip() for s in suggestions if str(s).strip()][0:6]
    else:
        suggestions = []

    overall_comment = str(data.get("overall_comment", "")).strip() or "（未生成总结）"
    knowledge_summary = str(data.get("knowledge_summary", "")).strip() or "（未生成总评）"

    try:
        practice_detail=normalize_practice(data,messages)
    except ValueError:
        raise APIError(502,'评分维度与理由对应结果不一致，已保留作答和点评，请稍后重试生成报告') from None
    missing=[key for key in SCORE_WEIGHTS if key not in practice_detail['radar_dimensions']]
    for key,field in [('knowledge','knowledge_score'),('completeness','completeness_score'),('expression','expression_score'),('job_relevance','job_relevance_score')]:
        entry=practice_detail['radar_dimensions'].get(key)
        if entry and not entry.get('reason'):
            practice_detail['radar_dimensions'].pop(key);missing.append(key)
    missing=list(dict.fromkeys(missing))
    if 'knowledge' in missing:k=0
    if 'completeness' in missing:c=0
    if 'expression' in missing:e=0
    if 'job_relevance' in missing:jr=0
    overall_unassessed=bool(missing)
    if overall_unassessed:
        overall=0
        knowledge_summary='部分评分依据不足，暂不计算综合分。'
        overall_comment='本场缺少部分核心维度可核对的回答依据，暂不作整场能力判断。已观察内容见逐题复盘与有依据的维度；未评估不代表缺乏能力。'
    coverage=coverage_of(messages)
    confidence_note=''
    if coverage['main_topics_covered']<MAIN_QUESTION_COUNT or coverage['skipped'] or overall_unassessed:
        confidence_note=(f"本场有{coverage['effective_answers']}次有效回答、{coverage['skipped']}次跳过，覆盖{coverage['main_topics_covered']}/{MAIN_QUESTION_COUNT}道主问题。"
                         '覆盖有限或缺少评分依据的维度显示未评估，不代表缺乏能力。')
    report = {
        "interview_id": interview_id,
        "overall_score": overall,
        "knowledge_score": k,
        "completeness_score": c,
        "expression_score": e,
        "job_relevance_score": jr,
        "weaknesses": weaknesses,
        "suggestions": suggestions,
        "overall_comment": overall_comment,
        "knowledge_summary": knowledge_summary,
        "confidence_note": confidence_note,
        "detail": {"unassessed":unassessed,"overall_unassessed":overall_unassessed,"unassessed_core":missing,
                   "coverage":coverage,"scoring_version":"practice-v4-evidence", "raw_dim_count": 4, **practice_detail},
    }
    dbm.save_report(report)
    # Optional voice advice is requested separately after the score is displayed.
    return report


def review_interview_speech(interview_id):
    from speech_review import generate_reviews
    if not SPEECH_REVIEW_LOCK.acquire(blocking=False):
        return False
    try:
        entries = dbm.list_speech_analyses(interview_id)
        if entries:
            results = generate_reviews(dbm.get_interview(interview_id), entries,
                                       dbm.get_messages(interview_id), call_deepseek)
            for analysis_id, feedback in results.items():
                dbm.save_speech_feedback(analysis_id, interview_id, feedback)
        return True
    finally:
        SPEECH_REVIEW_LOCK.release()


def report_job_payload(interview_id, retry=False):
    global REPORT_JOB_SERVICE
    from report_jobs import ReportJobs
    with REPORT_JOB_LOCK:
        if REPORT_JOB_SERVICE is None:
            REPORT_JOB_SERVICE = ReportJobs(dbm, app, lambda sid: generate_report(sid))
    guard = app.extensions.get('public_api_guard')
    subjects = guard.report_context() if guard else ()
    job = REPORT_JOB_SERVICE.ensure(interview_id, subjects, retry=retry)
    partial = answered_questions(dbm.get_messages(interview_id))
    if job['state'] == 'failed':
        return {'available': False, 'reason': 'failed', 'task_state': 'failed', 'task_id':hashlib.sha256(interview_id.encode()).hexdigest()[:16], 'error': job['error'], 'partial': partial}, 503
    return {'available': False, 'reason': 'generating', 'task_state': job['state'], 'task_id':hashlib.sha256(interview_id.encode()).hexdigest()[:16], 'partial': partial,
            'message': '正在等待分析，您可以离开，稍后从历史记录查看。' if job['state']=='pending' else 'AI 正在分析回答并整理报告，您可以离开，稍后回来查看。'}, 202


def report_to_json(interview_id, allow_generate=True, background=False):
    """供 /api/report 返回：读取已存报告；不存在则按需生成。"""
    iv = dbm.get_interview(interview_id)
    if not iv:
        return {"available": False, "error": "面试记录不存在"}, 404
    if iv["status"] == "active":
        return {"available": False, "reason": "not_finished",
                "message": "本场面试尚未结束，暂无报告。请先完成或结束面试。"}, 200

    report = dbm.get_report(interview_id)
    if not report:
        if not allow_generate:
            return {'available': False, 'error': '报告尚未生成，请先加载报告后再导出'}, 409
        if background and not app.config.get('REPORT_JOBS_INLINE', False):
            if not any(m['role']=='user' for m in dbm.get_messages(interview_id)):
                return {'available': False, 'error': '本场面试没有有效回答，无法生成评价'}, 400
            return report_job_payload(interview_id)
        # One AI request per attempt; a refresh reuses an already saved result.
        try:
            report = generate_report(interview_id)
        except APIError as exc:
            if exc.code == 202:
                return {"available": False, "reason": "generating", "message": exc.message}, 202
            return {"available": False, "error": exc.message}, exc.code

    messages = dbm.get_messages(interview_id)
    answered = sum(1 for m in messages if m["role"] == "user")
    duration = None
    if iv["ended_at"] and iv["started_at"]:
        try:
            from datetime import datetime
            s = datetime.fromisoformat(iv["started_at"])
            e = datetime.fromisoformat(iv["ended_at"])
            duration = int((e - s).total_seconds())
        except Exception:
            duration = None

    from speech_review import report_entries
    return {
        "available": True,
        **report_practice(report, messages),
        "speech_analyses": report_entries(dbm.list_speech_analyses(interview_id)),
        "interview": {
            "id": iv["id"],
            "job": iv["job"],
            "difficulty": iv["difficulty"],
            "selection": dbm.get_selection(interview_id),
            "practice_profile": dbm.get_profile_snapshot(interview_id),
            "started_at": iv["started_at"],
            "ended_at": iv["ended_at"],
            "status": iv["status"],
            "answered_count": answered,
            "duration_sec": duration,
            "coverage": report.get('detail',{}).get('coverage'),
            "scoring_version": report.get('detail',{}).get('scoring_version','legacy-unversioned'),
        },
        "scores": report_scores(report),
        "grade": "覆盖不足 · 未评分" if report_scores(report)['overall'] is None else grade_of(report["overall_score"]),
        "weaknesses": [dict(item,score=None) for item in report["weaknesses"]],
        "suggestions": report["suggestions"],
        "overall_comment": report["overall_comment"],
        "knowledge_summary": report["knowledge_summary"],
        "confidence_note": report.get("confidence_note", ""),
        "disclaimer": REPORT_DISCLAIMER,
    }, 200


# ------------------------------------------------------------------
# 页面路由
# ------------------------------------------------------------------
@app.route("/")
def page_index():
    return render_template("index.html", interview_catalog=catalog())


@app.route("/interview")
def page_interview():
    return render_template("interview.html")


@app.route("/report")
def page_report():
    return render_template("report.html")


@app.route("/history")
def page_history():
    return render_template("history.html")


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "deepseek_configured": client is not None})


@app.route('/api/catalog')
def api_catalog():
    return jsonify(catalog())


# ------------------------------------------------------------------
# GET /api/interviews  历史面试列表
# ------------------------------------------------------------------
@app.route("/api/interviews")
def api_interviews():
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    try:
        rows = dbm.list_interviews(limit)
    except Exception:
        return jsonify({"error": "历史记录读取失败，请稍后重试"}), 500
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "selection": dbm.get_selection(r['id']),
            "job": r["job"],
            "difficulty": r["difficulty"],
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
            "status": r["status"],
            "overall_score": r["overall_score"],          # None 表示暂无报告
            "has_report": r["overall_score"] is not None,
            "answered_count": r["answered_count"],
            "can_view_report": r["status"] in ("finished", "ended") and r["answered_count"] > 0,
        })
    return jsonify({"total": len(items), "items": items})


# ------------------------------------------------------------------
# DELETE /api/interview/<session_id>  删除一场历史面试（级联消息+报告）
# ------------------------------------------------------------------
@app.route("/api/interview/<session_id>", methods=["DELETE"])
def api_delete_interview(session_id):
    if not dbm.interview_exists(session_id):
        return jsonify({"error": "面试记录不存在或已删除"}), 404
    try:
        deleted = dbm.delete_interview(session_id)
    except Exception:
        return jsonify({"error": "删除失败，请稍后重试"}), 500
    if not deleted:
        return jsonify({"error": "面试记录不存在或已删除"}), 404
    SESSIONS.pop(session_id, None)  # 同步清理内存会话
    return jsonify({"deleted": True, "id": session_id})


# ------------------------------------------------------------------
# POST /api/speech/transcribe  音频上传 → faster-whisper 中文转写
# ------------------------------------------------------------------
@app.route("/api/speech/transcribe", methods=["POST"])
def api_transcribe():
    include_analysis = request.form.get("include_analysis", "").lower() == "true"
    analysis_session_id = request.form.get("session_id", "")
    question_sequence = None
    if include_analysis and analysis_session_id:
        iv = dbm.get_interview(analysis_session_id)
        if not iv or iv['status'] != 'active':
            return jsonify({"success": False, "error": "面试已结束或不存在，请重新开始"}), 409
        questions = [m for m in dbm.get_messages(analysis_session_id)
                     if m['message_type'] in ('main_question', 'followup') and m['role'] == 'assistant']
        question_sequence = questions[-1]['sequence'] if questions else None
        if questions and request.form.get('question') and request.form['question'] != questions[-1]['content']:
            return jsonify({'success':False, 'error':'当前题目已改变，请刷新面试页面后重新录音'}), 409
    if "audio" not in request.files:
        return jsonify({"success": False, "error": "未收到音频文件"}), 400
    f = request.files["audio"]
    if not f or not f.filename:
        return jsonify({"success": False, "error": "音频文件为空"}), 400

    # 用原始扩展名决定临时文件后缀；扩展名白名单校验，禁止任意路径
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_AUDIO_EXT:
        return jsonify({"success": False, "error": "不支持的音频格式（支持 webm/mp3/wav/m4a/ogg/mp4/aac）"}), 400

    # 探测 faster-whisper 是否可用（不触发模型下载）
    import speech
    if not speech.is_available():
        return jsonify({"success": False, "error": "语音识别服务未就绪，请联系管理员安装 faster-whisper"}), 503

    # 安全临时文件：用户无法控制服务端路径
    from speech_temp import create as create_temporary_audio
    tmp_path = create_temporary_audio(dbm,analysis_session_id,ext)
    try:
        size = 0
        with open(tmp_path, "wb") as out:
            while True:
                chunk = f.stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    out.close()
                    os.unlink(tmp_path)
                    return jsonify({"success": False, "error": "音频过大（超过 25MB）"}), 413
                out.write(chunk)
        if size == 0:
            return jsonify({"success": False, "error": "音频文件为空，可能未真正录制"}), 400

        # 调用 faster-whisper 转写
        try:
            text, duration = speech.transcribe(tmp_path)
        except speech.AudioTooLong:
            return jsonify({"success": False, "error": "录音过长，请控制在 120 秒以内"}), 413
        except RuntimeError:
            # 不向客户端返回底层异常，以免暴露令牌、代理地址等配置。
            return jsonify({"success": False, "error": "语音识别模型暂不可用，请检查服务器模型缓存后重试"}), 503
        except Exception:
            return jsonify({"success": False, "error": "音频解码或识别失败，请换一种录音方式重试"}), 502

        if not text:
            return jsonify({"success": False, "error": "未识别到语音内容（可能为静音或环境噪音）"}), 422

        payload = {
            "success": True,
            "text": text,
            "duration": round(duration, 1) if duration else None,
        }
        if analysis_session_id and not dbm.interview_exists(analysis_session_id):
            return jsonify(success=False,error='这场练习已被删除，识别结果不再保留'),404
        # Opt-in, ephemeral measurements. ASR and scoring remain independent.
        if include_analysis:
            try:
                from audio_analysis import analyze_audio
                payload["analysis"] = analyze_audio(tmp_path, asr_text=text)
                if analysis_session_id and question_sequence is not None:
                    analysis_id = uuid.uuid4().hex
                    if dbm.save_pending_speech(analysis_id, analysis_session_id, question_sequence, payload['analysis']):
                        payload['analysis_id'] = analysis_id
            except Exception:
                payload["analysis"] = {
                    "schema_version": "audio-analysis.v1", "status": "unavailable",
                    "metrics": None, "warnings": ["analysis_failed"],
                    "emotion": {"enabled": False, "status": "not_evaluated"},
                }
        return jsonify(payload)
    finally:
        # 无论成功失败都清理临时音频
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ------------------------------------------------------------------
# POST /api/interview/start
# ------------------------------------------------------------------
@app.route("/api/interview/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or {}
    job = (data.get("job") or "").strip()
    level = (data.get("level") or "").strip()
    if not job or not level:
        return jsonify({"error": "请先选择面试岗位与难度"}), 400
    try:
        selection = selection_for(data.get('major_id'), job)
        background = normalize_background(data.get('background'), data.get('background_consent'))
        requested_background=dict(background)
        if not isinstance(data.get('profile_consent',False),bool):raise ValueError('资料使用选项格式不正确')
        user=g.get('current_user')
        if data.get('profile_consent'):
            if not user:raise ValueError('请先登录后选择使用账户资料')
            background = normalize_background(dict(background,major=user['major'],stage=user['grade_label']),True)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    from start_requests import reserve,complete,failed,StartRequestError
    try:
        reservation,cached=reserve(dbm,data.get('request_id'),dict(job=job,level=level,major_id=data.get('major_id'),
            background=requested_background,profile_consent=data.get('profile_consent',False)))
    except StartRequestError as exc:
        return jsonify(error=exc.message,code=exc.code),exc.status
    if cached:return jsonify(cached[0]),cached[1]
    try:
        first_q = call_deepseek([
            {"role": "system", "content": interviewer_system_prompt(job, level, background, selection)},
            {"role": "user", "content": "请开始面试，先让候选人做个自我介绍。只输出这一个开场问题。"},
        ])
    except APIError as e:
        failed(dbm,reservation,e.code,e.message)
        return jsonify(error=e.message,code='start_failed'), e.code
    except Exception:
        message='首题结果暂未确认，请先核对历史，不要重复新建'
        failed(dbm,reservation,500,message,uncertain=True)
        return jsonify(error=message,code='start_uncertain'),500

    session_id = uuid.uuid4().hex
    progress=dict(main=1,total=MAIN_QUESTION_COUNT,type='main')
    response=dict(session_id=session_id,selection=selection,question_sequence=1,answered_count=0,
                  job=job,level=level,question=first_q,progress=progress,finished=False,background_active=bool(background))
    try:
        with dbm.get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            dbm.create_interview(session_id, job, level, background=background, selection=selection,connection=conn)
            dbm.add_message(session_id, "assistant", first_q, "main_question", 1,connection=conn)
            if user:
                conn.execute('INSERT INTO interview_profile_snapshots VALUES (?,?,?,?,?)',(session_id,user['major'],user['grade_label'],int(data.get('profile_consent',False)),'profile-consent-v1'))
            complete(conn,reservation,session_id,response)
    except Exception:
        message='面试保存结果暂未确认，请先核对历史，再决定是否新建一场'
        failed(dbm,reservation,500,message,uncertain=True)
        return jsonify(error=message,code='start_uncertain'),500

    session = {
        "id": session_id,
        "job": job,
        "level": level,
        "selection": selection,
        "main_index": 0,
        "phase": "main",
        "followup_used": 0,
        "history": [{"role": "assistant", "content": first_q}],
        "finished": False,
        "started_at": time.time(),
        "busy": False,
    }
    SESSIONS[session_id] = session
    return jsonify(response)


# ------------------------------------------------------------------
# POST /api/interview/answer
# ------------------------------------------------------------------
@app.route('/api/interview/<session_id>/state')
def api_interview_state(session_id):
    iv = dbm.get_interview(session_id)
    if not iv:
        return jsonify(error='面试记录不存在，请从首页重新开始'), 404
    messages = dbm.get_messages(session_id)
    questions = [m for m in messages if m['role'] == 'assistant' and m['message_type'] in ('main_question','followup')]
    question = questions[-1] if questions else None
    comments = [m for m in messages if m['message_type'] == 'comment']
    # Display-only completion facts from persisted questions/answers, never client text.
    answers = {}
    current = None
    for message in messages:
        if message['role']=='assistant' and message['message_type'] in ('main_question','followup'):
            current=message['sequence']
        elif message['role']=='user' and message['message_type']=='answer' and current is not None:
            answers[current]=message['content'].strip()
    skipped=sum(answers.get(q['sequence'])==SKIP_ANSWER for q in questions)
    unanswered=sum(not answers.get(q['sequence']) for q in questions)
    processed=bool(iv['status']=='finished' and sum(q['message_type']=='main_question' for q in questions)==MAIN_QUESTION_COUNT and not unanswered)
    all_answered=processed and skipped==0
    completion=dict(kind='active' if iv['status']=='active' else 'complete' if all_answered else 'skipped' if skipped else 'ended',
                    all_answered=all_answered,all_processed=processed,skipped=skipped,unanswered=unanswered,
                    question_count=len(questions),answered_count=len(answers),status=iv['status'])
    report_state='ready' if dbm.get_report(session_id) else 'not_generated'
    if report_state!='ready':
        with dbm.get_conn() as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_jobs'").fetchone():
                job=conn.execute('SELECT state,lease_until FROM report_jobs WHERE interview_id=?',(session_id,)).fetchone()
                if job and job['state'] in ('pending','running','failed'):
                    report_state=job['state']
                    if report_state in ('pending','running') and (REPORT_JOB_SERVICE is None or not REPORT_JOB_SERVICE.thread or not REPORT_JOB_SERVICE.thread.is_alive() or (report_state=='running' and job['lease_until']<time.time())):
                        report_state='interrupted'
    from datetime import datetime
    try:
        end_time = datetime.fromisoformat(iv['ended_at']).timestamp() if iv['ended_at'] else time.time()
        elapsed = max(0, int(end_time-datetime.fromisoformat(iv['started_at']).timestamp()))
    except (ValueError, TypeError):
        elapsed = 0
    response = jsonify(session_id=session_id, job=iv['job'], level=iv['difficulty'], selection=dbm.get_selection(session_id),
                   elapsed_seconds=elapsed, background_active=bool(dbm.get_background(session_id)),
                   question=question['content'] if question else '', question_sequence=question['sequence'] if question else None,
                   progress=dict(main=iv['current_question'],total=MAIN_QUESTION_COUNT,
                                 type='followup' if question and question['message_type']=='followup' else 'main'),
                   finished=iv['status'] != 'active', comment=comments[-1]['content'] if comments else '',
                   completion=completion,last_answer=answers.get(question['sequence'],'') if question else '',report_state=report_state,
                   answered_count=sum(m['role']=='user' for m in messages),
                   processing=bool(SESSIONS.get(session_id, {}).get('busy')))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@app.route('/api/interview/answer', methods=['POST'])
def api_answer():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='请求格式不正确'), 400
    session_id = data.get('session_id')
    answer = data.get('answer')
    if not isinstance(session_id, str) or not isinstance(answer, str):
        return jsonify(error='回答或面试标识格式不正确'), 400
    try:answer.encode('utf-8')
    except UnicodeError:return jsonify(error='回答含不支持的字符，请重新输入'),400
    if any(ord(c)<32 and c not in '\n\r\t' for c in answer):return jsonify(error='回答含不支持的控制字符'),400
    answer = answer.strip()
    analysis_id = data.get('analysis_id') or None
    request_id = data.get('request_id')
    question_sequence = data.get('question_sequence')
    if request_id is not None and (not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{32}',request_id)):
        return jsonify(error='提交标识格式不正确，请刷新后恢复草稿'), 400
    if request_id is not None and question_sequence is None:
        return jsonify(error='请先恢复当前题目，再提交回答'),400
    if question_sequence is not None and (isinstance(question_sequence,bool) or not isinstance(question_sequence,int) or question_sequence<1):
        return jsonify(error='题目标识格式不正确'), 400
    if not answer or len(answer)>MAX_ANSWER_CHARS:
        return jsonify(error=f'回答必须是1至{MAX_ANSWER_CHARS}字的文字'), 400
    if analysis_id is not None and (not isinstance(analysis_id,str) or not re.fullmatch(r'[0-9a-f]{32}',analysis_id)):
        return jsonify(error='录音分析标识格式不正确'), 400
    request_hash = hashlib.sha256(json.dumps([answer,analysis_id,question_sequence],ensure_ascii=False).encode()).hexdigest()
    with ANSWER_STATE_LOCK:
        receipt = dbm.get_answer_receipt(session_id,request_id) if request_id else None
        if receipt:
            if receipt['request_hash'] != request_hash:
                return jsonify(error='同一提交标识不能用于不同回答，请先恢复当前题目'), 409
            return jsonify(receipt['response'])
        session = load_session(session_id)
        if not session:
            return jsonify(error='面试会话不存在或已过期，请重新开始面试'),404
        if session['finished']:
            return jsonify(error='本场作答已完成，请查看最后点评或进入报告'),409
        if session.get('busy'):
            return jsonify(error='上一条回答正在处理，请稍后恢复状态，不要重复作答'),409
        with dbm.get_conn() as conn:
            current_question = dbm.current_question_sequence(conn,session_id)
        if question_sequence is not None and question_sequence != current_question:
            return jsonify(error='题目已更新，请先恢复当前题目；原草稿仍保留'),409
        if analysis_id and not dbm.get_pending_speech(analysis_id,session_id):
            return jsonify(error='录音分析已过期或不属于当前题目，请取消关联后重试'),409
        session['busy'] = True
    original_history = list(session['history'])
    try:
        session['history'].append(dict(role='user',content=answer))
        sequence = dbm.next_sequence(session_id)
        mode = 'followup' if session['phase']=='main' and session['followup_used']<MAX_FOLLOWUP_PER_Q else (
            'next_main' if session['main_index']+1<MAIN_QUESTION_COUNT else 'finish')
        comment,next_q = ask_next(dict(session,answer_skipped=answer==SKIP_ANSWER),mode)
        planned = dict(session)
        if mode=='followup':
            planned.update(followup_used=session['followup_used']+1,phase='followup')
            question_type='followup'
        elif mode=='next_main':
            planned.update(main_index=session['main_index']+1,phase='main',followup_used=0)
            question_type='main_question'
        else:
            planned['finished']=True
            question_type=None
        response=dict(comment=comment,next_question=next_q,finished=planned['finished'],progress=progress_of(planned),
                      question_sequence=sequence+2 if next_q else current_question,
                      answered_count=sum(m['role']=='user' for m in session['history']))
        dbm.commit_answer_turn(session_id,answer,sequence,analysis_id,comment,next_q,question_type,
                               planned['main_index']+1,planned['followup_used'],planned['finished'],
                               current_question,request_id,request_hash,response)
        session.update(planned)
        if next_q:session['history'].append(dict(role='assistant',content=next_q))
        return jsonify(response)
    except ValueError:
        session['history']=original_history
        return jsonify(error='题目或录音关联已更新，请恢复状态后重试；草稿仍保留'),409
    except APIError as exc:
        session['history']=original_history
        return jsonify(error=exc.message),exc.code
    except Exception:
        session['history']=original_history
        return jsonify(error='本次提交未能完成，请重试；草稿仍保留'),500
    finally:
        with ANSWER_STATE_LOCK:session['busy']=False


# ------------------------------------------------------------------
# POST /api/interview/end （提前结束）
# ------------------------------------------------------------------
@app.route("/api/interview/end", methods=["POST"])
def api_end():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id") or ""
    # Share the answer admission lock; never end a turn while its AI work is in flight.
    # The lock covers only local state/DB, never a provider call.
    with ANSWER_STATE_LOCK:
        session = load_session(session_id)
        if not session:
            return jsonify({"error": "面试会话不存在或已过期"}), 404
        if session.get('busy'):
            return jsonify(error='上一条回答仍在处理，请等待保存完成后再结束；草稿仍保留',code='answer_in_progress'),409
        answered = sum(1 for m in session["history"] if m["role"] == "user")
        if not session['finished']:
            try:
                dbm.finish_interview(session_id, "ended")
            except Exception:
                return jsonify(error='结束状态保存失败，请重试；回答仍保留'), 503
            session["finished"] = True
    # Return immediately; report generation belongs to the report-page request.
    return jsonify({
        "finished": True,
        "stats": {
            "job": session["job"],
            "level": session["level"],
            "answers": answered,
            "duration_sec": int(time.time() - session["started_at"]),
        },
    })


# ------------------------------------------------------------------
# GET /api/report/<session_id>
# ------------------------------------------------------------------
@app.route("/api/report/<session_id>")
def api_report(session_id):
    # HEAD may inspect a saved report, but must never start or recover AI work.
    payload, code = report_to_json(session_id,allow_generate=False) if request.method=='HEAD' else report_to_json(session_id,background=True)
    return jsonify(payload), code


@app.route('/api/report/<session_id>/generate', methods=['POST'])
def api_report_generate(session_id):
    iv = dbm.get_interview(session_id)
    if not iv:
        return jsonify(error='面试记录不存在'), 404
    if iv['status']=='active':
        return jsonify(error='请先结束本场面试'), 409
    if not any(m['role']=='user' for m in dbm.get_messages(session_id)):
        return jsonify(error='本场面试没有有效回答，无法生成评价'), 400
    if dbm.get_report(session_id):
        payload, code = report_to_json(session_id, allow_generate=False)
    else:
        payload, code = report_job_payload(session_id, retry=True)
    return jsonify(payload), code


@app.route('/api/report/<session_id>/export')
def api_export_report(session_id):
    payload, code = report_to_json(session_id, allow_generate=False)
    if code != 200:
        return jsonify(payload), code
    if not payload.get('available'):
        return jsonify(error='请先结束面试并加载报告后再导出'), 409
    try:
        from report_pdf import build_report_pdf
        pdf = build_report_pdf(payload)
    except Exception as exc:
        app.logger.error('PDF export failed (%s)', type(exc).__name__)
        return jsonify(error='PDF 暂时生成失败，请点击重试导出；已保存的报告不受影响'), 503
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)[:12] or 'report'
    response = send_file(BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
                         download_name=f'AI面试报告-{safe_id}.pdf',
                         conditional=False, etag=False, max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.route('/api/report/<session_id>/speech-review', methods=['POST'])
def api_speech_review(session_id):
    iv = dbm.get_interview(session_id)
    if not iv:
        return jsonify({'error': '面试记录不存在'}), 404
    if iv['status'] == 'active':
        return jsonify({'error': '请先结束面试'}), 409
    try:
        if not review_interview_speech(session_id):
            return jsonify({'error': '语音建议正在生成，请稍后重试'}), 409
    except Exception:
        return jsonify({'error': '语音建议暂不可用，原报告不受影响'}), 503
    from speech_review import report_entries
    return jsonify({'speech_analyses': report_entries(dbm.list_speech_analyses(session_id))})


@app.route('/api/interview/<session_id>/background', methods=['GET', 'DELETE'])
def api_clear_background(session_id):
    if not dbm.interview_exists(session_id):
        return jsonify(error='面试记录不存在'), 404
    if request.method == 'GET':
        return jsonify(active=bool(dbm.get_background(session_id)))
    dbm.clear_background(session_id)
    return jsonify(cleared=True)


import sys as _sys
from accounts import install as install_accounts
app.config['APP_INSECURE'] = os.getenv('APP_INSECURE') == '1'
install_accounts(app,dbm,_sys.modules[__name__])
from observability import install as install_observability
install_observability(app)
from reanswer import install as install_reanswer
install_reanswer(app,dbm)

if __name__ == "__main__":
    from candidate_background import start_cleanup
    start_cleanup(dbm)
    app.run(host="127.0.0.1", port=5001, debug=False)
