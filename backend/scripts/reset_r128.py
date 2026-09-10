"""R-128 一次性数据重置：清空人设档案、校验记录、AI 提示词与逐篇提取缓存。

用法（在项目根目录）：
    backend/.venv/bin/python -m backend.scripts.reset_r128   # 或在 backend 目录下 python scripts/reset_r128.py

仅删除本需求指定的数据，不动素材/草稿/指标等其它表；删除后由服务启动时
ensure_defaults 重新 seed 新版默认提示词。
"""

from __future__ import annotations

import sys

from app.db import SessionLocal, init_db
from app.models.kv import Kv
from app.models.persona import PersonaCheck, PersonaTag
from app.models.prompt import AiPrompt
from app.services.prompt_service import ensure_defaults


def main() -> int:
    init_db()  # 幂等建表 + 迁移（含 R-128 新增 persona_checks / persona_tags.dimension）
    db = SessionLocal()
    try:
        counts = {
            "persona_tags": db.query(PersonaTag).delete(synchronize_session=False),
            "persona_checks": db.query(PersonaCheck).delete(synchronize_session=False),
            "ai_prompts": db.query(AiPrompt).delete(synchronize_session=False),
        }
        cache = (
            db.query(Kv)
            .filter(Kv.key.like("persona_piece_v1:%") | (Kv.key == "persona_incremental_pending"))
            .delete(synchronize_session=False)
        )
        counts["persona_cache_kv"] = cache
        db.commit()
        for key, value in counts.items():
            print(f"已清除 {key}: {value} 行")
        ensure_defaults(db)  # 重新 seed 新版默认提示词（v1）
        total = db.query(AiPrompt).count()
        print(f"已重新 seed 默认提示词: {total} 条")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
