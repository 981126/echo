from __future__ import annotations

from statistics import median

from ..models.platform import CreatorAccount, PlatformPost, PlatformPostComment


def _evidence(item: dict) -> list[dict]:
    return [{
        "evidence_id": f"metric:{item['key']}",
        "key": item["key"],
        "label": item["label"],
        "value": item["value"],
        "baseline": item["baseline"],
        "percentile": item["percentile"],
        "sample_count": item["sample_count"],
    }]


def _finding(facts: dict, key: str, dimension: str, rule: str, title: str, conclusion: str, suggestion: str, target: str, hypothesis: bool = False, content: list | None = None) -> dict:
    return {
        "dimension": dimension,
        "rule_key": rule,
        "title": title,
        "judgement_type": "hypothesis" if hypothesis else "fact",
        "conclusion": conclusion,
        "metric_evidence": _evidence(facts[key]),
        "content_evidence": content or [],
        "comparison_post_ids": [],
        "suggestion": suggestion,
        "target_metric": target,
    }


def build_findings(comparison: dict, transcript: str, comments: list[PlatformPostComment], retention: list[dict]) -> list[dict]:
    facts = comparison["facts"]
    out: list[dict] = []

    def state(key: str) -> str:
        return facts[key]["state"]

    opening = (transcript or "")[:180].strip()
    opening_slow = any(word in opening[:60] for word in ("大家好", "我是", "今天想", "最近", "先介绍", "背景"))
    if state("bounce_2s_rate") == "low" or state("finish_5s_rate") == "low":
        content = []
        if opening:
            content.append({"evidence_id": "content:opening", "text": opening, "source": "视频开头转写"})
        hypothesis = bool(opening and opening_slow)
        out.append(_finding(
            facts, "bounce_2s_rate" if state("bounce_2s_rate") == "low" else "finish_5s_rate", "completion", "early_retention_weak",
            "开头进入主题可能偏慢" if hypothesis else "开头留人表现低于平时",
            "开头流失高于平时" if state("bounce_2s_rate") == "low" else "观众看到5秒的比例低于平时",
            "下一条先给出结果或观众最关心的问题，再补充背景。" if hypothesis else "检查前5秒是否尽快进入主题，先做一个只改开头的版本。",
            "completion", hypothesis, content,
        ))
    if state("finish_5s_rate") != "low" and state("finish_rate") == "low":
        out.append(_finding(
            facts, "finish_rate", "completion", "late_retention_weak", "开头还可以，但完整看完的人偏少",
            "前5秒表现没有明显偏弱，但完整完播率低于平时。",
            "检查中段是否重复解释，下一条只保留一个核心问题，并提前结束重复总结。", "completion", True,
            [{"evidence_id": "content:body", "text": (transcript or "")[:1200], "source": "视频转写"}] if transcript else [],
        ))
    if state("cover_click_rate") == "low":
        out.append(_finding(
            facts, "cover_click_rate", "plays", "cover_weak", "封面点击率低于平时",
            "看到封面后点击观看的人比例偏低。", "下一条只调整封面和标题，让主题和能解决的问题更具体。", "plays",
        ))
    if state("plays") in ("high", "normal") and state("like_rate") == "low":
        out.append(_finding(
            facts, "like_rate", "engagement", "engagement_weak", "有人看，但愿意点赞的人偏少",
            "播放没有明显偏低，但点赞率低于平时。", "保留当前主题，检查内容是否只有信息罗列，加入真实经历或更明确的观点。", "engagement", True,
        ))
    if state("plays") == "low" and (state("finish_rate") == "high" or state("follower_per_1k") == "high"):
        out.append(_finding(
            facts, "plays", "plays", "good_content_low_reach", "看过的人反馈不错，但看的人偏少",
            "播放不高，但完播或涨粉表现有亮点。", "不要放弃这个主题；下一条保留内容方向，只修改开头或封面中确实偏弱的一项。", "plays",
        ))
    if state("plays") in ("high", "normal") and state("profile_visits") == "low":
        out.append(_finding(
            facts, "profile_visits", "followers", "profile_interest_weak", "看完以后想继续了解你的人偏少",
            "播放没有明显偏低，但主页访问量低于平时。", "结尾明确告诉观众，你会持续讲哪一类问题，并优先发布同方向的后续内容。", "followers", True,
        ))
    if state("profile_visits") in ("high", "normal") and state("follower_per_1k") == "low":
        out.append(_finding(
            facts, "follower_per_1k", "followers", "follow_weak", "有人进主页，但关注没有同步增加",
            "主页访问不算弱，但每1000次播放带来的关注低于平时。", "检查主页简介、近期视频和置顶内容是否围绕同一个方向，让观众知道关注后还能看什么。", "followers", True,
        ))
    if state("follower_per_1k") == "high" or state("follower_gain") == "high":
        key = "follower_per_1k" if state("follower_per_1k") == "high" else "follower_gain"
        out.append(_finding(
            facts, key, "followers", "follow_strength", "这条内容带来了较好的关注",
            "这条视频的粉丝增量或每千次播放关注高于平时。", "优先保留这个主题，并围绕观众还在追问的问题连续发布相关内容。", "followers",
        ))
    if state("plays") == "low" and not out:
        out.append(_finding(
            facts, "plays", "plays", "reach_weak", "播放量低于平时",
            "当前主要差异是观看人数较少，其他原因还需要更多数据判断。", "先保留内容主题，下一条只重点调整封面或开头中的一项。", "plays",
        ))
    if retention and comparison["charts"]["retention"]["reliable"]:
        points = [p for p in retention if isinstance(p.get("current"), (int, float))]
        drops = []
        for before, after in zip(points, points[1:]):
            drop = float(before["current"]) - float(after["current"])
            if drop > 0:
                drops.append(drop)
        if drops:
            typical = median(drops)
            for before, after in zip(points, points[1:]):
                drop = float(before["current"]) - float(after["current"])
                if drop >= 0.05 and drop > typical * 2:
                    out.append({
                        "dimension": "completion", "rule_key": "trend_drop", "title": f"观众在 {after['time_label']} 附近离开增多",
                        "judgement_type": "fact", "conclusion": f"留存曲线在这里下降了{drop * 100:.1f}个百分点。",
                        "metric_evidence": [{"evidence_id": f"metric:trend:{after['time_label']}", "drop": drop, "time": after["time_label"]}],
                        "content_evidence": [], "comparison_post_ids": [],
                        "suggestion": "查看这个时间点附近是否进入新话题或重复解释；没有逐秒转写时，只能先检查内容，不能直接认定某句台词导致离开。",
                        "target_metric": "completion",
                    })
                    break
    return out[:6]


def summary_for(comparison: dict, findings: list[dict]) -> str:
    overall = comparison["overall"]
    if overall == "unknown":
        return "历史数据还比较少，先查看当前数据和最需要关注的一项"
    if overall == "good":
        return "这条整体表现较好，优先保留有效主题和做法"
    if overall == "needs_improvement":
        return findings[0]["title"] if findings else "这条有几项表现低于平时，需要优先修改"
    return findings[0]["title"] if findings else "这条有好有坏，需要分别看播放、互动、完播和涨粉"


def comment_questions(comments: list[PlatformPostComment]) -> list[dict]:
    groups: dict[str, dict] = {}
    hints = ("怎么", "如何", "为什么", "能不能", "是不是", "吗", "？", "?", "求", "请教")
    for comment in comments:
        text = (comment.text or "").strip()
        if len(text) < 4 or not any(h in text for h in hints):
            continue
        key = text[:24]
        group = groups.setdefault(key, {"group_title": key, "commenter_count": 0, "likes": 0, "comment_ids": [], "comments": []})
        group["commenter_count"] += 1
        group["likes"] += int(comment.likes or 0)
        group["comment_ids"].append(comment.id)
        group["comments"].append({"id": comment.id, "text": text, "likes": comment.likes})
    return sorted(groups.values(), key=lambda x: (x["commenter_count"], x["likes"]), reverse=True)[:8]


def homepage_analysis(account: CreatorAccount, recent_posts: list[PlatformPost]) -> dict:
    extra = account.extra()
    supplied_raw = extra.get("review_homepage")
    supplied: dict = supplied_raw if isinstance(supplied_raw, dict) else {}
    bio = str(supplied.get("bio") or "")
    direction = str(supplied.get("direction_note") or "")
    titles = [p.title for p in recent_posts[:10]]
    return {
        "bio": bio,
        "direction_note": direction,
        "pinned_post_ids": supplied.get("pinned_post_ids") or [],
        "recent_titles": titles,
        "source": "author" if supplied else "platform",
        "needs_author_input": not bio or not supplied.get("pinned_post_ids"),
        "message": "主页信息已补齐" if bio and supplied.get("pinned_post_ids") else "请补充主页简介和置顶视频，才能判断进主页后是否有关注理由",
    }
