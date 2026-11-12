"""JCR 공식 지표 조회 (선택 기능).

환경변수 JCR_LOOKUP_URL(예: http://jcr-hub:8000)이 있을 때만 그 주소의 /api/lookup 에 묻는다.
주소가 없거나 응답이 없으면 조용히 빈 값 — 봇의 원래 동작에는 영향 없음.
JCR 자료 자체는 이 저장소에 담지 않는다(기관 구독 자료).
"""
import json
import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)
_URL = os.environ.get("JCR_LOOKUP_URL", "").strip().rstrip("/")
_cache: dict = {}


def lookup(issn: str = "", name: str = "") -> dict | None:
    if not _URL or not (issn or name):
        return None
    key = (issn, name)
    if key in _cache:
        return _cache[key]
    res = None
    try:
        q = urllib.parse.urlencode({"issn": issn or "", "name": name or ""})
        with urllib.request.urlopen(f"{_URL}/api/lookup?{q}", timeout=5) as r:
            data = json.load(r)
        if data.get("found"):
            res = {k: data.get(k) for k in ("jif", "best_quartile", "best_category", "label", "source", "kci")}
        elif data.get("kci"):
            res = {"label": data["kci"].get("status") or "KCI", "source": "KCI", "kci": data["kci"]}
    except Exception as e:  # 조회 실패는 봇 동작에 영향 주지 않음
        logger.debug(f"JCR 조회 생략: {type(e).__name__}")
    _cache[key] = res
    return res


def label(paper: dict) -> str:
    j = paper.get("jcr") or {}
    return j.get("label") or ""
