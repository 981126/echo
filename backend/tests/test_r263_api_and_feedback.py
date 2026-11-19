"""R-263：生成运行 API、回炉版本与反馈学习。"""

from __future__ import annotations

import json

import pytest
from conftest import fresh_engine
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import drafts as drafts_api
from app.db import get_db
from app.models.author_generation import AuthorAsset, GenerationRun
from app.models.draft import Draft
from app.models.draft_version import DraftVersion
from app.models.persona import PersonaTag
from app.models.platform import Creator
from app.models.task import BackgroundTask
from app.services import generation_feedback
from app.services.author_assets import content_hash, validate_asset_evidence
from app.services.draft_versions import snapshot_version


@pytest.fixture()
def db():
    engine = fresh_engine()
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    owner = Creator(kind="owner", name="我", is_current=True)
    session.add(owner)
    session.commit()
    session.refresh(owner)
    yield session, owner
    session.close()


@pytest.fixture()
def client(db):
    session, _owner = db
    app = FastAPI()
    app.include_router(drafts_api.router, prefix="/api/drafts")

    def override():
        yield session

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def test_generate_async_returns_run_and_rejects_empty(client, monkeypatch):
    calls = []

    def fake_start(_db, topic, query_source=""):
        calls.append((topic, query_source))
        return 10, 20, 30

    monkeypatch.setattr(drafts_api.draft_flow, "start_generation", fake_start)
    response = client.post("/api/drafts/generate-async", json={"topic": "目标约束", "query_source": "具体原文"})
    assert response.status_code == 200
    assert response.json() == {"task_id": 10, "draft_id": 20, "run_id": 30}
    assert calls == [("目标约束", "具体原文")]
    assert client.post("/api/drafts/generate-async", json={"topic": "  "}).status_code == 400


def test_latest_run_permissions_empty_and_legacy(client, db):
    session, owner = db
    draft = Draft(creator_id=owner.id, title="旧稿", source="ai")
    session.add(draft)
    session.commit()
    assert client.get(f"/api/drafts/{draft.id}/generation-runs/latest").status_code == 404
    run = GenerationRun(creator_id=owner.id, draft_id=draft.id, topic="旧稿", status="legacy", quality_passed=True)
    session.add(run)
    session.commit()
    response = client.get(f"/api/drafts/{draft.id}/generation-runs/latest")
    assert response.status_code == 200
    assert response.json()["quality_passed"] is False
    assert response.json()["legacy_unverified"] is True
    other = Creator(kind="owner", name="别人", is_current=False)
    session.add(other)
    session.flush()
    draft.creator_id = other.id
    session.commit()
    assert client.get(f"/api/drafts/{draft.id}/generation-runs/latest").status_code == 403


def test_rework_conflict_and_foreign_angle(client, db):
    session, owner = db
    draft = Draft(creator_id=owner.id, title="选题", script="当前正文", source="ai")
    session.add(draft)
    session.commit()
    session.add(BackgroundTask(kind="generate_draft", status="running", payload=json.dumps({"draft_id": draft.id})))
    session.commit()
    assert client.post(f"/api/drafts/{draft.id}/rework", json={}).status_code == 409
    session.query(BackgroundTask).delete()
    run = GenerationRun(creator_id=owner.id, draft_id=draft.id, topic="选题", status="succeeded", angles_json="[]")
    session.add(run)
    session.commit()
    assert client.post(f"/api/drafts/{draft.id}/rework", json={"angle_id": "other"}).status_code == 422
    assert client.post(f"/api/drafts/{draft.id}/discuss", json={}).status_code == 409


def test_rework_snapshots_current_version_before_queue(client, db, monkeypatch):
    session, owner = db
    draft = Draft(creator_id=owner.id, title="生成后标题", script="作者改过", source="ai")
    session.add(draft)
    session.commit()
    run = GenerationRun(creator_id=owner.id, draft_id=draft.id, topic="原始选题", status="succeeded")
    session.add(run)
    session.commit()
    monkeypatch.setattr(drafts_api.draft_flow, "start_task", lambda *_args, **_kwargs: 99)
    response = client.post(f"/api/drafts/{draft.id}/rework", json={})
    assert response.status_code == 200
    assert response.json()["task_id"] == 99
    versions = session.query(DraftVersion).filter(DraftVersion.draft_id == draft.id).all()
    assert len(versions) == 1
    assert versions[0].script == "作者改过"
    assert versions[0].note == "重新生成前"
    new_run = session.query(GenerationRun).order_by(GenerationRun.id.desc()).first()
    assert new_run.topic == "原始选题"


def test_done_edit_becomes_traceable_asset_without_changing_persona(db, monkeypatch):
    session, owner = db
    draft = Draft(creator_id=owner.id, title="稿", original_script="原稿", script="最终稿更口语", source="ai", status="done")
    session.add(draft)
    session.commit()
    snapshot_version(session, draft, source="manual")

    class _Client:
        def chat_json(self, *_args, **_kwargs):
            return {"assets": [{"asset_kind": "expression", "content": "作者偏好直接口语", "context": {}, "quote": "更口语"}]}

    monkeypatch.setattr(generation_feedback.llm_router, "primary_llm", lambda *_args, **_kwargs: _Client())
    result = generation_feedback.learn_from_draft(session, draft)
    assert result["created"] == 1
    asset = session.query(AuthorAsset).one()
    assert asset.status == "active"
    assert validate_asset_evidence(session, asset) is True
    assert session.query(PersonaTag).count() == 0


def test_delete_only_marks_negative_feedback(db):
    session, owner = db
    draft = Draft(creator_id=owner.id, title="稿", script="正文", source="ai", status="deleted")
    session.add(draft)
    session.commit()
    asset = AuthorAsset(
        creator_id=owner.id,
        asset_kind="viewpoint",
        source_kind="asr",
        content="观点",
        content_hash=content_hash(owner.id, "viewpoint", "观点"),
        evidence_refs="[]",
        status="active",
    )
    session.add(asset)
    session.flush()
    run = GenerationRun(
        creator_id=owner.id,
        draft_id=draft.id,
        topic="稿",
        status="succeeded",
        evidence_json=json.dumps({"author_assets": [{"id": asset.id}]}),
    )
    session.add(run)
    session.commit()
    result = generation_feedback.learn_from_draft(session, draft)
    assert result["skipped"] == 1
    assert json.loads(asset.usage_stats)["rejected"] == 1
    assert session.query(AuthorAsset).count() == 1
