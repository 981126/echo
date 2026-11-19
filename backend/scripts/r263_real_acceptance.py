"""R-263：固定 20 主题真实模型验收；作者盲评分单独留空。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.db import SessionLocal
from app.models.author_generation import GenerationRun
from app.services.generation_pipeline import generate_author_draft, generation_run_payload

TOPICS = [
    "临时加班和已经约好的朋友聚餐冲突了，怎么决定更合适？",
    "工作三年想涨薪，领导一直画饼，下一步怎么办？",
    "和伴侣消费习惯差异很大，怎样谈钱不伤感情？",
    "经常熬夜后白天没精神，怎样调整作息更现实？",
    "想买一款很火但明显超预算的耳机，怎么判断值不值？",
    "月薪一万想开始存钱，怎样制定能执行的预算？",
    "AI 工具每天都在更新，普通创作者该怎么选而不是全买？",
    "赶早班高铁，地图显示时间刚好够，还要不要提前出门？",
    "减脂期间特别想吃火锅，怎样安排更可持续？",
    "孩子写作业拖延，家长陪写和不管之间怎么把握？",
    "厨房很小，怎样通过收纳提高做饭效率？",
    "手机拍照总是不好看，先换手机还是先学构图？",
    "刚拿驾照不敢上高速，怎样循序渐进练车？",
    "办了健身卡坚持不下来，怎样重新开始运动？",
    "租房合同里哪些条款最容易被忽略？",
    "孩子沉迷短视频，家长完全没收手机是不是好办法？",
    "任务很多总被打断，怎样安排一天的优先级？",
    "工作出错后一直很焦虑，怎样避免反复内耗？",
    "公共热点刚出现时事实不完整，创作者应该马上跟进吗？",
    "垂直账号流量下降，应该换赛道还是继续优化内容？",
]


def _one(topic: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        try:
            draft = generate_author_draft(db, topic)
            run = (
                db.query(GenerationRun)
                .filter(GenerationRun.draft_id == draft.id)
                .order_by(GenerationRun.id.desc())
                .first()
            )
        except Exception as exc:  # noqa: BLE001 失败也保留运行现场与报告，不挑案例
            db.rollback()
            run = (
                db.query(GenerationRun)
                .filter(GenerationRun.topic == topic)
                .order_by(GenerationRun.id.desc())
                .first()
            )
            if run is None:
                return {"topic": topic, "status": "failed", "error": str(exc)[:500]}
        payload = generation_run_payload(run)
        payload["error"] = payload.get("error") or ""
        return payload
    finally:
        db.close()


def main() -> None:
    report_path = Path(__file__).resolve().parents[2] / "data" / "backups" / "r263-real-generation-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="r263-acceptance") as executor:
        for result in executor.map(_one, TOPICS):
            results.append(result)
            succeeded = sum(item.get("status") == "succeeded" for item in results)
            print(f"completed={len(results)}/20 succeeded={succeeded}", flush=True)
            report_path.write_text(
                json.dumps(
                    {
                        "topics": TOPICS,
                        "completed": len(results),
                        "succeeded": succeeded,
                        "needs_input": sum(item.get("status") == "needs_input" for item in results),
                        "needs_review": sum(item.get("status") == "needs_review" for item in results),
                        "failed": sum(item.get("status") == "failed" for item in results),
                        "quality_passed": sum(bool(item.get("quality_passed")) for item in results),
                        "author_blind_review": {
                            "status": "pending_author",
                            "author_likeness_average": None,
                            "willingness_average": None,
                            "record_ready_average": None,
                            "record_ready_below_3_count": None,
                        },
                        "results": results,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    print(report_path)


if __name__ == "__main__":
    main()
