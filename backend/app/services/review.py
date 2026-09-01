"""复盘服务：A 报表 / B 归因 / C 建议 / D 赛道雷达（LLM + 启发式兜底）。"""
import json

from sqlalchemy.orm import Session

from ..core.metrics import engagement_rate
from ..core.review import best_topic_by_engagement, heuristic_direction
from ..models.metrics import ReviewReport
from .llm import LLMError
from .metrics import summary
from .persona import PersonaService

REVIEW_SYSTEM = (
    "你是自媒体数据分析专家。基于以下视频数据，输出复盘 JSON："
    '{"B_attribution":[{"video":"文件名","why":"为什么好/差（结合内容特征与数据）"}],'
    '"C_next_action":"下一条应该做什么（具体可执行）",'
    '"D_topic_direction":"赛道方向建议（求职/面试/赚钱/知识 怎么取舍，结合赛道雷达）"}'
)


def _radar(db: Session) -> dict:
    data = summary(db)
    radar = []
    for topic, s in data["by_topic"].items():
        radar.append(
            {
                "topic": topic,
                "videos": s["videos"],
                "plays": s["plays"],
                "likes": s["likes"],
                "engagement": engagement_rate(s["plays"], s["likes"], s["favorites"], s["comments"]),
            }
        )
    radar.sort(key=lambda x: x["engagement"], reverse=True)
    return radar


def _llm_abcd(db: Session, data: dict, radar: list[dict]) -> dict:
    lines = []
    for v in data["per_video"][:15]:
        lines.append(
            f"- {v['filename']} | 赛道:{v['main_topic']} | 平台:{v['platform']} | "
            f"播放:{v['plays']} 赞:{v['likes']} 藏:{v['favorites']} 评:{v['comments']}"
        )
    radar_lines = "\n".join(
        f"- {r['topic']}: {r['videos']} 条, 播放 {r['plays']}, 互动率 {r['engagement']}%"
        for r in radar
    )
    persona = PersonaService()
    try:
        llm_data = persona.llm.chat_json(
            [
                {"role": "system", "content": REVIEW_SYSTEM},
                {
                    "role": "user",
                    "content": f"视频数据：\n" + "\n".join(lines) + f"\n\n赛道雷达：\n{radar_lines}",
                },
            ],
            temperature=0.4,
        )
        return {
            "B_attribution": llm_data.get("B_attribution") or [],
            "C_next_action": str(llm_data.get("C_next_action", "")),
            "D_topic_direction": str(llm_data.get("D_topic_direction", "")),
        }
    except LLMError:
        return {}


def generate_report(db: Session, run_date: str | None = None) -> ReviewReport:
    """生成完整复盘（A 报表 + B/C/D），入库。"""
    import datetime

    key = run_date or datetime.date.today().isoformat()
    data = summary(db)
    radar = _radar(db)
    abcd = _llm_abcd(db, data, radar)

    best = best_topic_by_engagement(radar)
    worst = min(radar, key=lambda x: x["engagement"]) if radar else None
    if not abcd.get("D_topic_direction"):
        abcd["D_topic_direction"] = heuristic_direction(best, worst)
    if not abcd.get("C_next_action"):
        abcd["C_next_action"] = (
            "数据量较小时：保持当前赛道稳定更新，优先复盘表现最好的单条视频，复制其结构。"
            if best is None
            else f"围绕「{best['topic']}」再产出 2~3 条，验证方向稳定性。"
        )

    report = ReviewReport(
        run_date=key,
        report_type="full",
        content=json.dumps(
            {
                "A_report": {
                    "by_topic": data["by_topic"],
                    "by_platform": data["by_platform"],
                    "per_video": data["per_video"][:50],
                },
                "B_attribution": abcd.get("B_attribution", []),
                "C_next_action": abcd.get("C_next_action", ""),
                "D_topic_direction": abcd.get("D_topic_direction", ""),
                "radar": radar,
            },
            ensure_ascii=False,
        ),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def latest_report(db: Session) -> dict | None:
    row = db.query(ReviewReport).order_by(ReviewReport.id.desc()).first()
    if row is None:
        return None
    try:
        content = json.loads(row.content or "{}")
    except json.JSONDecodeError:
        content = {}
    return {"run_date": row.run_date, "report_type": row.report_type, "content": content}
