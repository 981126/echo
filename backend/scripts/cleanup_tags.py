import json
from app.db import SessionLocal
from app.models.platform import PlatformPost
S = '\u8bdd\u9898'
SKIP = {'douyin','\u6296\u97f3','xiaohongshu','\u5c0f\u7ea2\u4e66','bilibili','B\u7ad9','b\u7ad9','\u89c6\u9891','vlog',S,'tag'}
NORMS = {w.lower() for w in SKIP}
db = SessionLocal()
changed = 0
for p in db.query(PlatformPost).all():
    try:
        tags = json.loads(p.tags or '[]') if isinstance(p.tags, str) else (p.tags or [])
    except Exception:
        continue
    if not isinstance(tags, list):
        continue
    out = []
    for t in tags:
        t = str(t).replace('[' + S + ']', '').replace(']', '').strip()
        if (not t) or (t.lower() in NORMS) or (t in out):
            continue
        out.append(t)
    new = json.dumps(out, ensure_ascii=False)
    if not (new == p.tags):
        p.tags = new
        changed += 1
db.commit()
print('cleaned posts:', changed)
db.close()
