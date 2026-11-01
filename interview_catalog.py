"""Practice directions transcribed from the user's major list; server-owned allowlists."""
import json

FEATURED_JOBS = ['Java 后端', '前端开发', 'Python 后端', '算法工程师', '产品经理', '数据分析']
LEVELS = {'实习入门', '校招标准', '社招进阶', '大厂冲刺'}
LANGUAGE_MAJORS = {'english','translation','german','french','russian','spanish','italian','portuguese',
                  'japanese','korean','thai','arabic'}


def major(id, name, college, *roles):
    return dict(id=id, name=name, college=college, roles=list(roles), language_track=id in LANGUAGE_MAJORS)


DISCIPLINES = [
    dict(id='literature', code='05', name='文学', description='语言、写作与传播', majors=[
        major('english', '英语', '英语学院', '英语教师', '外贸业务助理', '海外运营'),
        major('translation', '翻译', '英语学院', '笔译译员', '翻译项目助理', '本地化专员'),
        *[major(id, name, '西方语学院', '外贸业务助理', '海外运营', '笔译译员') for id, name in [
            ('german','德语'),('french','法语'),('russian','俄语'),('spanish','西班牙语'),('italian','意大利语'),('portuguese','葡萄牙语')]],
        *[major(id, name, '东方语学院', '外贸业务助理', '海外运营', '笔译译员') for id, name in [
            ('japanese','日语'),('korean','朝鲜语'),('thai','泰语'),('arabic','阿拉伯语')]],
        major('chinese-literature','汉语言文学','国际汉语教育学院','文案策划','内容编辑','语文教师'),
        major('international-chinese','汉语国际教育','国际汉语教育学院','国际中文教师','教育项目助理','内容编辑'),
        major('journalism','新闻学','国际传媒学院','新闻采编','内容编辑'),
        major('advertising','广告学','国际传媒学院','广告策划','品牌策划'),
        major('communication','传播学','国际传媒学院','传播策划','公关执行'),
        major('new-media','网络与新媒体','国际传媒学院','新媒体运营','内容策划'),
        major('international-journalism','国际新闻与传播','国际传媒学院','国际传播助理','新闻采编'),
    ]),
    dict(id='economics', code='02', name='经济学', description='经贸、市场与数字经济', majors=[
        major('international-trade','国际经济与贸易','国际商贸与管理学院','外贸业务助理','跨境电商运营','市场研究助理'),
        major('digital-economy','数字经济','国际商贸与管理学院','数据分析','数字化运营','市场研究助理'),
    ]),
    dict(id='education', code='04', name='教育学', description='教学、学习与体育实践', majors=[
        major('primary-education','小学教育','国际汉语教育学院','小学教师','教育项目助理'),
        major('social-sports','社会体育指导与管理','体育部','体育活动策划','健身指导','体育运营'),
    ]),
    dict(id='management', code='12', name='管理学', description='商业、项目与服务管理', majors=[
        major('international-business','国际商务','国际商贸与管理学院','商务助理','外贸业务助理','跨境电商运营'),
        major('engineering-management','工程管理','国际商贸与管理学院','项目管理助理','工程成本助理'),
        major('cultural-industry','文化产业管理','国际商贸与管理学院','文化项目运营','活动策划','品牌策划'),
        major('accounting-education','财务会计教育','国际商贸与管理学院','会计助理','财务分析助理','会计教学助理'),
        major('hotel-management','酒店管理','国际商贸与管理学院','酒店运营','客户服务','活动策划'),
    ]),
    dict(id='engineering', code='08', name='工学', description='软件、数据与数字技术', majors=[
        major('computer-science','计算机科学与技术','智能科学与工程学院','Java 后端','Python 后端','算法工程师'),
        major('software-engineering','软件工程','智能科学与工程学院','Java 后端','前端开发','软件测试'),
        major('data-science','数据科学与大数据技术','智能科学与工程学院','数据分析','数据工程师','算法工程师'),
        major('digital-media-tech','数字媒体技术','智能科学与工程学院','前端开发','交互设计','数字内容制作'),
    ]),
    dict(id='arts', code='13', name='艺术学', description='设计、影像与艺术表达', majors=[
        major('broadcasting','播音与主持艺术','国际传媒学院','主持与播音','内容策划'),
        major('film-production','影视摄影与制作','国际传媒学院','视频编导','视频剪辑','摄影摄像'),
        major('fine-arts','美术学','艺术学院','美术教师','艺术项目助理'),
        major('painting','绘画','艺术学院','插画设计','美术教师'),
        major('visual-communication','视觉传达设计','艺术学院','视觉设计','品牌设计'),
        major('environmental-design','环境设计','艺术学院','空间设计助理','展示设计'),
        major('product-design','产品设计','艺术学院','工业产品设计','用户研究助理'),
        major('fashion-design','服装与服饰设计','艺术学院','服装设计助理','时尚品牌运营'),
        major('digital-media-art','数字媒体艺术','艺术学院','交互设计','动态视觉设计','数字内容制作'),
        major('musicology','音乐学','音乐舞蹈学院','音乐教师','艺术项目助理'),
        major('music-performance','音乐表演','音乐舞蹈学院','音乐演出','艺术项目助理'),
        major('dance-performance','舞蹈表演','音乐舞蹈学院','舞蹈教学','舞蹈演出'),
    ]),
]

ROLE_FOCUS = {
    'Java 后端':'Java基础、接口设计、数据库与项目取舍', '前端开发':'页面实现、交互、可访问性与浏览器基础',
    'Python 后端':'Python基础、接口开发、数据库与异常处理', '算法工程师':'算法基础、实验设计与结果验证',
    '产品经理':'需求分析、优先级、方案设计与验证', '数据分析':'数据清洗、指标分析、可视化与结论验证',
    '英语教师':'教学设计、学情分析与课堂沟通', '语文教师':'阅读写作教学、学情分析与课堂沟通',
    '小学教师':'教学设计、课堂组织与学生沟通', '国际中文教师':'中文教学、跨文化表达与课堂活动',
    '外贸业务助理':'客户沟通、订单流程与跨文化协作', '海外运营':'内容本地化、受众理解与运营指标',
    '笔译译员':'文本理解、翻译取舍、术语一致性与校对', '翻译项目助理':'需求澄清、术语管理、进度与质量协调',
    '本地化专员':'文化适配、语言质量与产品协作', '文案策划':'受众分析、文案结构与内容表达',
    '内容编辑':'信息核实、选题、编辑与受众表达', '新闻采编':'选题、信息核实、采访与新闻表达',
    '广告策划':'受众洞察、创意方案与效果评估', '品牌策划':'定位、品牌表达与传播方案',
    '传播策划':'目标受众、传播策略与效果复盘', '公关执行':'沟通、活动执行与问题应对',
    '新媒体运营':'选题、内容制作、平台运营与数据复盘', '内容策划':'选题、内容结构与用户需求',
    '国际传播助理':'跨文化表达、信息核实与内容协作', '跨境电商运营':'选品、商品内容、客户沟通与运营指标',
    '市场研究助理':'研究问题、资料核实、数据分析与结论表达', '数字化运营':'业务流程、数据指标与改进验证',
    '教育项目助理':'课程活动、学习目标与项目协调', '体育活动策划':'活动设计、参与者需求与执行协调',
    '健身指导':'训练目标、动作基础、个体差异与风险识别', '体育运营':'服务设计、活动运营与客户沟通',
    '商务助理':'信息整理、商务沟通与任务协调', '项目管理助理':'目标拆解、进度、风险与团队协作',
    '工程成本助理':'成本构成、资料核对与方案比较', '文化项目运营':'受众、文化内容、项目执行与复盘',
    '活动策划':'目标、流程、预算取舍与现场应对', '会计助理':'会计基础、凭证核对与业务理解',
    '财务分析助理':'报表理解、指标比较与业务分析', '会计教学助理':'会计概念解释、案例设计与学习反馈',
    '酒店运营':'服务流程、跨部门协调与客户体验', '客户服务':'需求理解、沟通表达与问题处理',
    '软件测试':'测试设计、缺陷定位与质量验证', '数据工程师':'数据处理、质量控制与流程设计',
    '交互设计':'用户需求、交互流程、可用性与设计取舍', '数字内容制作':'内容目标、制作流程与呈现效果',
    '主持与播音':'稿件理解、表达结构、现场沟通与应变', '视频编导':'选题、脚本结构与制作协调',
    '视频剪辑':'叙事节奏、素材组织与剪辑选择', '摄影摄像':'画面设计、拍摄方案与作品讲述',
    '美术教师':'艺术教学、作品分析与课堂沟通', '艺术项目助理':'作品理解、项目组织与沟通执行',
    '插画设计':'主题表达、构图、风格选择与作品复盘', '视觉设计':'视觉层级、信息表达与作品讲述',
    '品牌设计':'品牌理解、视觉系统与设计取舍', '空间设计助理':'空间需求、方案表达与协作',
    '展示设计':'展示目标、动线、视觉叙事与方案取舍', '工业产品设计':'用户需求、造型功能、材料与设计验证',
    '用户研究助理':'研究问题、访谈、信息分析与结论表达', '服装设计助理':'设计主题、材料、工艺与作品讲述',
    '时尚品牌运营':'品牌内容、用户需求与运营活动', '动态视觉设计':'动态叙事、视觉节奏与制作流程',
    '音乐教师':'音乐知识、教学设计与学习反馈', '音乐演出':'曲目理解、排练协作与演出复盘',
    '舞蹈教学':'动作讲解、教学设计与学习反馈', '舞蹈演出':'作品理解、排练协作与表演复盘',
}

MAJORS = {m['id']: dict(m, discipline_id=d['id'], discipline=d['name'])
          for d in DISCIPLINES for m in d['majors']}
JOBS = set(FEATURED_JOBS) | {job for m in MAJORS.values() for job in m['roles']}


def catalog():
    return dict(disciplines=DISCIPLINES, featured_jobs=FEATURED_JOBS, role_focus=ROLE_FOCUS,
                major_count=len(MAJORS), job_count=len(JOBS))


def selection_for(major_id, job):
    if major_id is None:
        return {}
    if not isinstance(major_id, str) or major_id not in MAJORS:
        raise ValueError('请选择页面提供的练习专业')
    item = MAJORS[major_id]
    if job not in item['roles']:
        raise ValueError('请选择当前专业推荐的岗位，或切换到直接选岗位')
    return {key: item[key] for key in ('discipline_id','discipline','college')} | dict(major_id=item['id'], major=item['name'])


def selection_prompt(selection, job):
    if not selection:
        return ''
    return ('\n练习方向是服务器确认的配置：' + json.dumps(selection, ensure_ascii=False)
            + '\n岗位考点：' + ROLE_FOCUS.get(job, '岗位基础、场景分析与沟通')
            + '。专业选择只用于定位练习方向，不表示候选人的真实学历、经历或资格，不能据此直接加减分。'
            '默认使用中文问答，结合该专业与岗位提出核心知识、案例分析和实践思路问题。'
            '外语专业可用中文解释翻译与沟通思路，不要求未经支持的外语录音；'
            '不预设候选人有工作或作品经历，入门级允许用课程和设想案例回答。'
            '艺术表演、设计和体育方向只评估文字回答中可观察的知识与思路，不能虚构已观看作品、听到演奏或观察到动作。')
