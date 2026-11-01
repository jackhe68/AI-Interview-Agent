"""Self-contained PDF exports from saved report data. No browser, AI, or remote assets."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
from interview_time import display_time
import math
from pathlib import Path
import re
import threading
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, Flowable, Paragraph, SimpleDocTemplate,
                               Spacer, Table, TableStyle)

FONT_PATH = Path(__file__).parent / 'assets' / 'fonts' / 'InterviewSans-Regular.ttf'
FONT_NAME = 'InterviewSans'
FONT_LOCK = threading.Lock()
PRIMARY = colors.HexColor('#6255DB')
INK = colors.HexColor('#18233B')
MUTED = colors.HexColor('#58677F')
LINE = colors.HexColor('#DFE5F1')
SOFT = colors.HexColor('#F5F5FC')


def ensure_font():
    with FONT_LOCK:
        if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
            pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold=FONT_NAME,
                                          italic=FONT_NAME, boldItalic=FONT_NAME)


def clean(value):
    value = '' if value is None else str(value)
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', value).replace('\r\n', '\n').replace('\r', '\n')


def pdf_text(value):
    """Keep data literal: never interpret user or model text as PDF/HTML markup."""
    value = clean(value)
    supported = pdfmetrics.getFont(FONT_NAME).face.charWidths
    # Unsupported symbols remain identifiable without rendering missing-glyph boxes.
    value = ''.join(c if c in '\n\t' or ord(c) in supported else f'[U+{ord(c):04X}]' for c in value)
    return escape(value).replace('\t', '    ').replace('  ', '&#160; ').replace('\n', '<br/>')


def number(value):
    return value if not isinstance(value, bool) and isinstance(value, (int, float)) and 0 <= value <= 100 and math.isfinite(value) else None


class RadarChart(Flowable):
    """Vector chart: unknown observations are gaps, not zero-valued vertices."""
    def __init__(self, dimensions, width=510, height=274):
        super().__init__()
        self.width, self.height = width, height
        self.dimensions = dimensions

    def draw(self):
        canvas = self.canv
        dimensions = self.dimensions
        if not dimensions:
            return
        count = len(dimensions)
        cx, cy, radius = self.width/2, self.height/2, 86

        def point(i, ratio):
            angle = math.pi/2 - 2*math.pi*i/count
            return cx+math.cos(angle)*radius*ratio, cy+math.sin(angle)*radius*ratio

        canvas.saveState()
        canvas.setLineWidth(.6)
        canvas.setStrokeColor(LINE)
        for layer in range(1, 5):
            path = canvas.beginPath()
            for i in range(count):
                x, y = point(i, layer/4)
                (path.moveTo if i == 0 else path.lineTo)(x, y)
            path.close()
            canvas.drawPath(path, stroke=1, fill=0)
        for i in range(count):
            canvas.line(cx, cy, *point(i, 1))
        values = [number(d.get('score')) for d in dimensions]
        canvas.setStrokeColor(PRIMARY)
        canvas.setFillColor(colors.HexColor('#E4DFFC'))
        canvas.setLineWidth(1.5)
        path = canvas.beginPath()
        for i, value in enumerate(values):
            if value is None:
                continue
            x, y = point(i, value/100)
            (path.moveTo if i == 0 or values[i-1] is None else path.lineTo)(x, y)
        complete = all(v is not None for v in values)
        if complete:
            path.close()
        canvas.drawPath(path, stroke=1, fill=int(complete))
        canvas.setFillColor(colors.white)
        for i, value in enumerate(values):
            if value is not None:
                canvas.circle(*point(i, value/100), 2.7, stroke=1, fill=1)
        canvas.setFont(FONT_NAME, 9)
        for i, dimension in enumerate(dimensions):
            x, y = point(i, 1.34)
            canvas.setFillColor(MUTED)
            canvas.drawCentredString(x, y+4, clean(dimension.get('label')))
            canvas.setFillColor(PRIMARY if values[i] is not None else MUTED)
            canvas.drawCentredString(x, y-11, str(round(values[i])) if values[i] is not None else '未评估')
        canvas.restoreState()


def build_report_pdf(payload):
    if not isinstance(payload, dict) or not payload.get('available'):
        raise ValueError('A saved, available report is required')
    ensure_font()
    buffer = BytesIO()
    width = A4[0]-84
    styles = {
        'title': ParagraphStyle('title', fontName=FONT_NAME, fontSize=25, leading=35,
                                textColor=INK, spaceAfter=12, wordWrap='CJK'),
        'h1': ParagraphStyle('h1', fontName=FONT_NAME, fontSize=15, leading=23,
                             textColor=PRIMARY, spaceBefore=18, spaceAfter=10, keepWithNext=True, wordWrap='CJK'),
        'h2': ParagraphStyle('h2', fontName=FONT_NAME, fontSize=12, leading=20,
                             textColor=INK, spaceBefore=14, spaceAfter=8, wordWrap='CJK'),
        'label': ParagraphStyle('label', fontName=FONT_NAME, fontSize=10, leading=17,
                                textColor=PRIMARY, spaceBefore=10, spaceAfter=4, wordWrap='CJK'),
        'body': ParagraphStyle('body', fontName=FONT_NAME, fontSize=10, leading=18,
                               textColor=INK, spaceAfter=8, wordWrap='CJK', splitLongWords=True),
        'small': ParagraphStyle('small', fontName=FONT_NAME, fontSize=8, leading=13,
                                textColor=MUTED, spaceAfter=7, wordWrap='CJK', splitLongWords=True),
        'score': ParagraphStyle('score', fontName=FONT_NAME, fontSize=23, leading=34,
                                textColor=PRIMARY, spaceBefore=4, spaceAfter=10, wordWrap='CJK'),
        'center': ParagraphStyle('center', fontName=FONT_NAME, fontSize=9, leading=15,
                                 alignment=TA_CENTER, textColor=MUTED, spaceAfter=8, wordWrap='CJK'),
    }
    story = []

    def para(value, kind='body'):
        return Paragraph(pdf_text(value), styles[kind])

    def add(value, kind='body'):
        if value is not None and str(value).strip():
            if kind in ('h1', 'h2', 'label'):
                story.append(CondPageBreak(110 if kind in ('h1', 'h2') else 72))
            story.append(para(value, kind))

    def field(label, value):
        if value is not None and str(value).strip():
            add(label, 'label')
            add(value)

    def items(values):
        for i, item in enumerate(values if isinstance(values, list) else []):
            add(f'{i+1}. {item}')

    def table(rows, widths):
        rendered = [[para(cell, 'small') for cell in row] for row in rows]
        result = Table(rendered, colWidths=widths, hAlign='LEFT', splitByRow=0)
        result.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BACKGROUND', (0,0), (-1,-1), SOFT),
            ('LINEBELOW', (0,0), (-1,-1), .4, colors.white),
            ('LEFTPADDING', (0,0), (-1,-1), 11),
            ('RIGHTPADDING', (0,0), (-1,-1), 11),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ]))
        story.append(result)

    interview = payload.get('interview') or {}
    scores = payload.get('scores') or {}
    add('面试练习报告', 'title')
    add(f"岗位：{interview.get('job', '')}    难度：{interview.get('difficulty', '')}")
    selection = interview.get('selection') or {}
    if selection:
        add(f"练习方向：{selection.get('discipline', '')} / {selection.get('major', '')}", 'small')
    add(f"开始时间：{display_time(interview.get('started_at'))}    作答：{interview.get('answered_count', 0)} 次", 'small')
    seconds = interview.get('duration_sec')
    duration = f'{int(seconds)//60} 分 {int(seconds)%60} 秒' if isinstance(seconds, (int, float)) and seconds >= 0 else '未记录'
    add(f"状态：{'提前结束' if interview.get('status') == 'ended' else '已完成'}    用时：{duration}", 'small')
    add(f"综合得分  {scores.get('overall', '-')} / 100    {payload.get('grade', '')}", 'score')
    weighted = [f"{label}：{scores.get(key, '-')} / 100（权重 {weight}）" for key, label, weight in [
        ('knowledge', '专业知识', '40%'), ('completeness', '回答完整性', '30%'),
        ('expression', '逻辑表达', '20%'), ('job_relevance', '岗位相关性', '10%')]]
    table([weighted[:2], weighted[2:]], [width/2, width/2])
    add(payload.get('disclaimer'), 'small')
    add('八维能力分析', 'h1')
    dimensions = payload.get('radar_dimensions') or []
    story.append(RadarChart(dimensions, width=width))
    add('“未评估”表示本场缺少回答依据，不记为零分。综合分仍按四项原有权重计算。', 'small')
    rows = []
    for i in range(0, len(dimensions), 2):
        row = []
        for d in dimensions[i:i+2]:
            value = number(d.get('score'))
            row.extend([d.get('label', ''), '未评估' if value is None else f'{round(value)} / 100'])
        rows.append(row + ['']*(4-len(row)))
    if rows:
        table(rows, [width*.28, width*.22, width*.28, width*.22])

    add('总评与优先改进方向', 'h1')
    add(payload.get('knowledge_summary'))
    add(payload.get('overall_comment'))
    add(payload.get('confidence_note'), 'small')
    add('薄弱知识点', 'h2')
    weaknesses = payload.get('weaknesses') or []
    if not weaknesses:
        add('本场报告未列出具体薄弱点；回答较少时，不代表已掌握全部知识。', 'small')
    for item in weaknesses:
        add(item.get('topic'), 'label')
        add(item.get('explanation'))
        if number(item.get('score')) is not None:
            add(f"掌握度：{round(item['score'])} / 100", 'small')
    add('改进练习清单', 'h2')
    items(payload.get('suggestions'))

    reviews = payload.get('answer_reviews') or []
    if reviews:
        add('逐题复盘与重答练习', 'h1')
        add('先回顾自己的回答，再对照参考回答。参考回答用于学习，不是唯一标准答案。', 'small')
    for i, review in enumerate(reviews, 1):
        add(f'第 {i} 次作答', 'h2')
        field('问题', review.get('question'))
        field('你的回答', review.get('answer'))
        field('当时的点评', review.get('comment'))
        field('做得好的地方', review.get('strength'))
        field('需要补齐什么', review.get('gap'))
        field('对应回答原文', review.get('evidence'))
        if review.get('answer_outline'):
            add('回答思路', 'label')
            items(review['answer_outline'])
        field('参考回答（供练习）', review.get('reference_answer'))
        if not review.get('reference_answer'):
            add('这份历史报告没有参考回答，导出不会额外生成或补造内容。', 'small')
        field('下一步怎么练', review.get('practice_task'))
        if review.get('checklist'):
            add('重答后自查', 'label')
            items(review['checklist'])
        story.append(Spacer(1, 9))

    evidence = [d for d in dimensions if d.get('evidence') or d.get('reason')]
    if evidence:
        add('八维评分依据', 'h1')
        for d in evidence:
            add(d.get('label'), 'label')
            add(d.get('reason'), 'small')
            if d.get('evidence'):
                add('回答原文：' + d['evidence'], 'small')

    speech_entries = payload.get('speech_analyses') or []
    if speech_entries:
        add('语言与语音表达分析', 'h1')
        add('以下为已保存的测量与建议，不参与上方综合评分。', 'small')
        metric_labels = [('duration_s', '录音时长', '秒'), ('speech_s', '有效语音时长', '秒'),
                         ('hanzi_per_min_speech', '中文语速（语音段）', '汉字/分钟'),
                         ('english_words_per_min_speech', '英文语速（语音段）', '词/分钟'),
                         ('pause_count', '内部停顿次数', '次'), ('pause_total_s', '内部停顿总时长', '秒'),
                         ('rms_dbfs', '数字音频电平', 'dBFS')]
        for i, entry in enumerate(speech_entries, 1):
            add(f'第 {i} 段录音', 'h2')
            field('对应问题', entry.get('question'))
            metrics = (entry.get('analysis') or {}).get('metrics') or {}
            for key, label, unit in metric_labels:
                if metrics.get(key) is not None:
                    add(f'{label}：{metrics[key]} {unit}')
            feedback = entry.get('feedback') or {}
            for value in (feedback.get('content') or {}).values():
                if isinstance(value, dict):
                    add(value.get('comment'))
            for value in feedback.get('voice_observations') or []:
                if isinstance(value, dict):
                    add(value.get('comment'))
            items(feedback.get('suggestions'))

    exported_at = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST')

    def page_header_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(42, A4[1]-25, 'AI Interview Agent')
        canvas.drawRightString(A4[0]-42, A4[1]-25, f'导出时间：{exported_at}')
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(.5)
        canvas.line(42, A4[1]-32, A4[0]-42, A4[1]-32)
        canvas.line(42, 34, A4[0]-42, 34)
        canvas.setFont(FONT_NAME, 7)
        canvas.drawString(42, 21, '仅用于学习与复盘；字体不支持的符号以 Unicode 编号显示。')
        canvas.drawRightString(A4[0]-42, 21, f'第 {doc.page} 页')
        canvas.restoreState()

    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=42, rightMargin=42,
                                 topMargin=48, bottomMargin=47,
                                 title='面试练习报告', author='AI Interview Agent')
    document.build(story, onFirstPage=page_header_footer, onLaterPages=page_header_footer)
    return buffer.getvalue()
