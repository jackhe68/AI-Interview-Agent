"""One real DeepSeek request against synthetic data, isolated from production DB."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from test_speech_integration import sample_analysis
from speech_review import generate_reviews

try:
    analysis=sample_analysis()
    entry={'id':'synthetic-live-review','question':'请介绍自己',
           'answer':'我熟悉数据库索引，在项目中用执行计划定位慢查询。',
           'analysis':analysis,'feedback':None}
    result=generate_reviews({'job':'Java 后端','difficulty':'标准'},[entry],[],env.server.call_deepseek)
    report={'source':'One real DeepSeek call; synthetic fixture measurements and constructed text; no production data',
            'result':result}
    target=env.ROOT/'docs/live-review-smoke.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Real DeepSeek review status:',result[entry['id']]['status'])
    assert result[entry['id']]['status']=='ok', 'Live cloud review unavailable or validation failed; see sanitized report'
finally:env.tearDownModule()
