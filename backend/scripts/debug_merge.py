"""R-128 调试脚本：观察归纳合并每一步的输入/输出规模（只读缓存，不写数据）。"""

from __future__ import annotations

import sys

from app.db import SessionLocal
from app.services import ingest
from app.services import persona_profile as pp
from app.services.persona import PersonaService


def size(profile: dict) -> int:
    return len((profile or {}).get("tags") or []) + len((profile or {}).get("redlines") or [])


def main() -> int:
    db = SessionLocal()
    try:
        cid = ingest.current_creator_id(db)
        materials = ingest._owner_materials(db, cid)
        texts = [t for _v, t in materials]
        parts = pp.extract_pieces(db, texts, service_factory=lambda: PersonaService())
        raw = sum(size(p) for p in parts)
        mech = pp.merge_mechanical(parts)
        print(f"篇数={len(parts)} 原始条目={raw} 机械近义去重后={size(mech)}")
        svc = PersonaService()
        orig = svc._llm_merge

        def traced(key: str, batch: list[dict]) -> dict | None:
            n_in = sum(size(p) for p in batch)
            result = orig(key, batch)
            print(f"  llm_merge key={key} 输入={n_in} 输出={'None(失败/截断)' if result is None else size(result)}")
            return result

        svc._llm_merge = traced  # type: ignore[method-assign]
        profile = svc.merge_full(parts)
        print(f"最终档案：标签={len(profile['tags'])} 红线={len(profile['redlines'])}")
        for t in profile["tags"][:25]:
            print(f"  [{t.get('dimension','')}] {t.get('label','')}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
