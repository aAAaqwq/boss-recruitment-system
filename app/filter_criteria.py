"""
筛选条件模块 — 轻量级，无重量依赖

包含:
    - 名校白名单 (国内 + 海外)
    - 可扩展的 FilterCriteria 数据类
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ========== 名校白名单 ==========

# 国内名校
DOMESTIC_ELITE_SCHOOLS = [
    "清华大学", "北京大学", "浙江大学", "复旦大学",
    "上海交通大学", "华中科技大学", "武汉大学", "中山大学",
    "南京大学", "西安交通大学", "哈尔滨工业大学", "中国科学技术大学",
    "中国人民大学", "同济大学", "北京航空航天大学", "北京理工大学",
    "天津大学", "南开大学", "东南大学", "厦门大学", "四川大学",
    "电子科技大学", "华南理工大学", "中南大学", "湖南大学",
    "北京师范大学", "华东师范大学", "吉林大学", "大连理工大学",
    "西北工业大学", "重庆大学", "山东大学", "兰州大学",
]

# 海外名校 - 美国
US_ELITE_SCHOOLS = [
    # English names
    "Harvard University", "Massachusetts Institute of Technology", "MIT",
    "Stanford University", "University of California, Berkeley", "UC Berkeley", "UCB",
    "California Institute of Technology", "Caltech",
    "Princeton University", "Yale University",
    "Columbia University", "University of Pennsylvania", "UPenn",
    "Cornell University", "University of Chicago", "UChicago",
    "Duke University", "Northwestern University",
    "Johns Hopkins University", "JHU",
    "University of California, Los Angeles", "UCLA",
    "Carnegie Mellon University", "CMU",
    "University of Michigan", "UMich",
    "New York University", "NYU",
    "University of Washington", "Georgia Institute of Technology", "Georgia Tech",
    "University of Illinois Urbana-Champaign", "UIUC",
    "University of Texas at Austin", "UT Austin",
    "University of Wisconsin-Madison", "Brown University",
    "Dartmouth College", "Rice University", "Vanderbilt University",
    # 中文翻译名
    "哈佛大学", "麻省理工学院", "斯坦福大学",
    "加州大学伯克利分校", "伯克利", "加州理工学院",
    "普林斯顿大学", "耶鲁大学", "哥伦比亚大学",
    "宾夕法尼亚大学", "康奈尔大学", "芝加哥大学",
    "杜克大学", "西北大学", "约翰霍普金斯大学",
    "加州大学洛杉矶分校", "卡内基梅隆大学",
    "密歇根大学", "纽约大学", "华盛顿大学",
    "佐治亚理工学院", "伊利诺伊大学香槟分校",
    "德克萨斯大学奥斯汀分校", "威斯康星大学麦迪逊分校",
    "布朗大学", "达特茅斯学院", "莱斯大学", "范德堡大学",
]

# 海外名校 - 英国
UK_ELITE_SCHOOLS = [
    # English names
    "University of Oxford", "Oxford University", "Oxford",
    "University of Cambridge", "Cambridge University", "Cambridge",
    "Imperial College London", "Imperial College",
    "London School of Economics", "LSE",
    "University College London", "UCL",
    "University of Edinburgh", "University of Manchester",
    "King's College London", "University of Bristol",
    "University of Warwick",
    # 中文翻译名
    "牛津大学", "剑桥大学", "帝国理工学院",
    "伦敦政治经济学院", "伦敦大学学院",
    "爱丁堡大学", "曼彻斯特大学",
    "伦敦国王学院", "布里斯托大学", "华威大学",
]

# 海外名校 - 其他地区
OTHER_ELITE_SCHOOLS = [
    # English names
    # 瑞士
    "ETH Zurich", "EPFL",
    # 加拿大
    "University of Toronto", "University of British Columbia", "UBC",
    "McGill University", "University of Waterloo",
    # 新加坡
    "National University of Singapore", "NUS",
    "Nanyang Technological University", "NTU",
    # 日本
    "University of Tokyo", "Tokyo University",
    "Kyoto University", "Tokyo Institute of Technology",
    # 香港
    "University of Hong Kong", "HKU",
    "Chinese University of Hong Kong", "CUHK",
    "Hong Kong University of Science and Technology", "HKUST",
    # 澳大利亚
    "University of Melbourne", "Australian National University", "ANU",
    "University of Sydney", "University of New South Wales", "UNSW",
    # 欧洲其他
    "University of Amsterdam", "Technical University of Munich",
    "LMU Munich", "Heidelberg University",
    "Sorbonne University", "PSL University",
    "KU Leuven", "Delft University of Technology",
    "University of Copenhagen", "Karolinska Institute",
    # 韩国
    "Seoul National University", "KAIST",
    "Yonsei University", "Korea University",
    # 中文翻译名
    "苏黎世联邦理工学院", "洛桑联邦理工学院",
    "多伦多大学", "不列颠哥伦比亚大学", "麦吉尔大学", "滑铁卢大学",
    "新加坡国立大学", "南洋理工大学",
    "东京大学", "京都大学", "东京工业大学",
    "香港大学", "香港中文大学", "香港科技大学",
    "墨尔本大学", "澳大利亚国立大学", "悉尼大学", "新南威尔士大学",
    "阿姆斯特丹大学", "慕尼黑工业大学", "慕尼黑大学", "海德堡大学",
    "索邦大学", "巴黎文理研究大学",
    "鲁汶大学", "代尔夫特理工大学",
    "哥本哈根大学", "卡罗林斯卡学院",
    "首尔大学", "韩国科学技术院", "延世大学", "高丽大学",
]

# 合并全部名校
ALL_ELITE_SCHOOLS = DOMESTIC_ELITE_SCHOOLS + US_ELITE_SCHOOLS + UK_ELITE_SCHOOLS + OTHER_ELITE_SCHOOLS


# ========== 可扩展筛选条件 ==========

@dataclass
class FilterCriteria:
    """可扩展的筛选条件

    当前支持的维度:
        - school_whitelist: 学校白名单
        - min_degree: 最低学历
        - min_years: 最低工作年限
    后续可扩展:
        - age_range: 年龄范围 (min, max)
        - tech_stack: 技术栈要求
        - industry: 行业经验
        - job_title_keywords: 职位关键词
    """
    school_whitelist: Optional[List[str]] = None
    min_degree: str = "本科"
    min_years: int = 3
    # ---- 预留扩展字段 ----
    age_range: Optional[Tuple[int, int]] = None       # (min_age, max_age)
    tech_stack: Optional[List[str]] = None              # ["Python", "React", ...]
    industry: Optional[List[str]] = None                # ["互联网", "金融", ...]
    job_title_keywords: Optional[List[str]] = None      # ["工程师", "产品经理", ...]
    exclude_keywords: Optional[List[str]] = None        # 排除关键词

    def get_active_filters(self) -> List[str]:
        """返回已激活的筛选维度名"""
        active = []
        if self.school_whitelist:
            active.append("school")
        if self.min_degree:
            active.append("degree")
        if self.min_years is not None:
            active.append("years")
        if self.age_range:
            active.append("age")
        if self.tech_stack:
            active.append("tech_stack")
        if self.industry:
            active.append("industry")
        if self.job_title_keywords:
            active.append("job_title")
        return active


# ========== 学校匹配 ==========

def match_school(candidate_school: str, whitelist: list) -> bool:
    """检查候选人的学校是否匹配白名单中的任一学校

    匹配规则:
        中文学校名: 完全相等（避免"电子科技大学"误匹配"桂林电子科技大学"）
        英文学校名: 支持缩写互推 + 包含匹配
        纯大写缩写: "MIT" <-> "Massachusetts Institute of Technology"
    """
    if not candidate_school or not whitelist:
        return False

    school = candidate_school.strip()
    school_lower = school.lower()
    is_chinese = bool(re.search(r'[一-龥]', school))

    for white_school in whitelist:
        white = white_school.strip()
        white_lower = white.lower()

        # 完全匹配
        if school_lower == white_lower:
            return True

        # 中文学校名: 只做完全匹配，不做包含匹配
        if is_chinese:
            continue

        # 英文: 包含匹配 + 缩写匹配
        if white_lower in school_lower or school_lower in white_lower:
            return True

        # 纯大写缩写匹配: "MIT" <-> "Massachusetts Institute of Technology"
        if white.isupper() and len(white) <= 7:
            words = school_lower.replace(',', '').split()
            if len(words) >= 2:
                abbr = ''.join(w[0].upper() for w in words if w[0].isalpha())
                if white.upper() == abbr:
                    return True

    return False
