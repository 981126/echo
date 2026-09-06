"""灵感池相关度评分（R-072）——纯逻辑、无第三方依赖、离线可测。

- 热榜/评论是否「符合当前人设」用本地关键词命中打分，不调 LLM、零成本。
- 关键词来源（service 层组装）：确认的人设标签/描述（topic 类）+ 近期已发布视频的赛道扩展词 + #话题标签；
  红线词（redline 类）命中即剔除。
- 只有人设关键词非空时才算「生效」：未建人设时所有内容视为中性（不误标低相关）。
"""

from __future__ import annotations

import re

# 每个主赛道对应的种子关键词（用于扩展“近期已发话题”→ 热榜匹配）
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "求职": [
        "求职", "找工作", "offer", "简历", "面试", "投递", "招聘", "岗位", "转行", "跳槽",
        "校招", "社招", "试用期", "离职", "裸辞", "裁员", "offer怎么选", "背调", "空窗期",
        "上岸", "应届生", "毕业", "入职", "晋升", "涨薪",
    ],
    "面试": [
        "面试", "面试官", "hr", "一面", "二面", "反问", "自我介绍", "离职原因", "职业规划",
        "期望薪资", "谈薪", "面试技巧", "群面", "面试被问",
    ],
    "赚钱": [
        "赚钱", "副业", "搞钱", "月入", "收入", "搞副业", "存钱", "理财", "兼职", "自媒体",
        "变现", "ai", "ai工具", "豆包", "技能", "副业月入", "第一桶金", "睡后收入",
    ],
    "知识": [
        "知识", "干货", "教程", "怎么", "如何", "为什么", "经验", "避坑", "涨知识", "解读",
        "科普", "入门", "学习", "案例", "拆解", "复盘",
    ],
}

_AVOID_WORD_RE = re.compile(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()【】\[\]《》<>#＃\-—…]+")


def words_of(text: str) -> list[str]:
    """把一段中文/夹杂文本拆成候选关键词：去标点后按空白/分隔符切分，保留 ≥2 字段。

    用于人设描述/红线描述 → 关键词；整段长句保留整段（保守：宁缺毋滥，避免误匹配）。
    """
    out: list[str] = []
    for seg in _AVOID_WORD_RE.split(text or ""):
        seg = seg.strip().lower()
        if not seg:
            continue
        # 长句（含 >10 字且带常见虚词）不直接当关键词，避免几乎不可能命中的噪音
        if len(seg) > 12:
            continue
        if len(seg) >= 2 and seg not in out:
            out.append(seg)
    return out


def topic_expansion(topics) -> list[str]:
    """把赛道集合展开为种子关键词（求职/面试/赚钱/知识/其他）。"""
    out: list[str] = []
    for t in topics or []:
        t = (t or "").strip()
        if not t:
            continue
        if t in TOPIC_KEYWORDS:
            out.extend(TOPIC_KEYWORDS[t])
        else:
            out.append(t)
    return out


def score_title(title: str, *, keywords: list[str], avoid: list[str]) -> int:
    """返回标题相关度分：命中红线词 → -1；否则为命中的不同关键词个数（0..n）。"""
    t = (title or "").lower()
    if not t:
        return 0
    for av in avoid:
        if av and av.lower() in t:
            return -1
    hits: set[str] = set()
    for kw in keywords:
        if kw and kw.lower() in t:
            hits.add(kw.lower())
    return len(hits)
