"""Explicit fictional AI fixtures with quoted answer evidence, never real scoring."""
import copy,json

def with_evidence(data,messages=None,answer=None,sequence=2):
    result=copy.deepcopy(data)
    if messages is not None:
        prompt=messages[-1]['content']
        start=prompt.index('面试记录：')+len('面试记录：')
        pairs=json.JSONDecoder().raw_decode(prompt[start:].lstrip())[0]
        pair=next(p for p in pairs if p['answer'].strip() and p['answer'].strip()!='（候选人选择跳过此题）')
        answer=pair['answer'];sequence=pair['answer_sequence']
    if not answer:raise ValueError('Fictional scored fixture needs an actual answer')
    result['radar_dimensions']=[dict(key=key,score=result[key+'_score'],answer_sequence=sequence,
        evidence=answer[:80],reason='虚构模型的契约测试说明，不是真实能力评价')
        for key in ('knowledge','completeness','expression','job_relevance')]
    return result
