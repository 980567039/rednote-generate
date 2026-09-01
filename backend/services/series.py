"""长期系列合集的本地模板、项目和一致性上下文服务。"""

from __future__ import annotations

import base64
import copy
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_FILE = ROOT / "series_templates.json"
PROJECTS_FILE = ROOT / "series_projects.json"
SERIES_ROOT = ROOT / "series"
MAX_BATCH_ITEMS = 10
MAX_TOPIC_LENGTH = 200
MAX_REFERENCES = 6
MAX_REFERENCE_BYTES = 10 * 1024 * 1024
ALLOWED_REFERENCE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_PAGE_STRUCTURES = {
    "standard": (5, ["cover", "content", "content", "content", "summary"]),
    "comparison_two": (2, ["content", "content"]),
    "comparison_four": (4, ["cover", "content", "content", "summary"]),
    # 精细角色图不是故事分镜：一个子主题只生成一张角色设定/阵容图。
    "character_sheet": (1, ["cover"]),
}
CONTENT_MODES = {"story", "character_sheet"}
MAX_CHARACTER_NAMES = 10
_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clone(value: Any) -> Any:
    return copy.deepcopy(value)


def _read(path: Path, key: str) -> List[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return []
    if isinstance(value, dict):
        value = value.get(key, [])
    return value if isinstance(value, list) else []


def _write(path: Path, key: str, values: List[Dict[str, Any]]) -> None:
    """0600 权限的同目录原子写。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({key: values}, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _templates() -> List[Dict[str, Any]]:
    return _read(TEMPLATES_FILE, "templates")


def _projects() -> List[Dict[str, Any]]:
    return _read(PROJECTS_FILE, "projects")


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，、;；\n]", value) if item.strip()]
    return []


def normalize_content_mode(value: Any) -> str:
    """规范合集子主题的内容方向；旧数据默认沿用剧情小故事。"""
    mode = str(value or "story").strip().lower()
    if mode not in CONTENT_MODES:
        raise ValueError("content_mode 必须为 story 或 character_sheet")
    return mode


def resolve_content_mode(
    value: Any = None,
    template: Optional[Dict[str, Any]] = None,
    context: str = "",
) -> str:
    """解析内容方向，并为早期角色合集数据提供结构化字段缺失兜底。

    新数据会显式保存 ``content_mode``，且显式的 ``story`` 必须优先于
    旧上下文。早期记录没有该字段时，则根据快照的
    ``page_structure.preset`` 或冻结上下文中的角色标记恢复角色模式。
    """
    if value is not None and str(value).strip():
        return normalize_content_mode(value)
    template = template or {}
    stored = template.get("content_mode")
    if stored is not None and str(stored).strip():
        return normalize_content_mode(stored)
    structure = template.get("page_structure") or {}
    if structure.get("preset") == "character_sheet":
        return "character_sheet"
    if "内容方向：精细角色图" in (context or ""):
        return "character_sheet"
    return "story"


def frozen_context_matches_mode(context: str, mode: str) -> bool:
    """判断冻结上下文是否与结构化内容方向一致。

    旧版系列记录可能只保存了人类可读的上下文，没有保存
    ``content_mode``。当调用方后来显式指定了模式时，不能继续复用相反
    方向的冻结文本，否则图片/文案提示词会同时收到两套互相冲突的规则。
    普通故事上下文不一定包含固定的“剧情小故事”字样，因此这里只把
    角色模式的明确标记作为冲突判据。
    """
    if not isinstance(context, str) or not context.strip():
        return False
    is_character_context = "内容方向：精细角色图" in context
    return is_character_context == (normalize_content_mode(mode) == "character_sheet")


def extract_character_names(topic: str) -> List[str]:
    """从角色图主题中提取角色名单；没有明确名单时退化为主题本身一个角色。"""
    value = re.sub(r"\s+", " ", str(topic or "")).strip()
    if not value:
        return ["未命名角色"]
    # 约定优先使用“系列/作品：角色A、角色B”的输入方式，避免把作品名拆成角色。
    match = re.search(r"[：:]", value)
    roster = value[match.end():] if match else ""
    if not roster:
        return [value[:MAX_TOPIC_LENGTH]]
    roster = re.sub(r"^(?:角色|人物|角色名单|角色阵容)\s*[:：]?\s*", "", roster, flags=re.IGNORECASE)
    names = [re.sub(r"^[\-•·\d.、)）]+\s*", "", part).strip() for part in re.split(r"[、,，;；\n]+", roster)]
    names = [name for name in names if name]
    # 兼容“路飞和索隆”这种自然输入，但不拆开包含“和”字的完整角色名。
    if len(names) == 1 and "和" in names[0]:
        names = [part.strip() for part in re.split(r"\s*和\s*", names[0]) if part.strip()]
    return names[:MAX_CHARACTER_NAMES] or [value[:MAX_TOPIC_LENGTH]]


def character_page_structure(topic: str) -> Dict[str, Any]:
    names = extract_character_names(topic)
    return {
        "preset": "character_sheet",
        "page_count": len(names),
    }


def _validate_topics(topics: Any, *, allow_empty: bool = True) -> List[str]:
    if not isinstance(topics, list) or any(not isinstance(topic, str) for topic in topics):
        raise ValueError("topics 必须是字符串数组")
    if len(topics) > MAX_BATCH_ITEMS:
        raise ValueError(f"单次最多添加 {MAX_BATCH_ITEMS} 个主题")
    normalized: List[str] = []
    seen = set()
    for raw in topics:
        topic = re.sub(r"\s+", " ", raw).strip()
        if not topic:
            raise ValueError("主题不能为空")
        if len(topic) > MAX_TOPIC_LENGTH:
            raise ValueError(f"单个主题不能超过 {MAX_TOPIC_LENGTH} 个字符")
        key = topic.casefold()
        if key not in seen:
            normalized.append(topic)
            seen.add(key)
    if not allow_empty and not normalized:
        raise ValueError("请至少提供一个主题")
    return normalized


def _page_structure(payload: Dict[str, Any]) -> Dict[str, Any]:
    structure = payload.get("page_structure") if isinstance(payload.get("page_structure"), dict) else {}
    preset = str(structure.get("preset") or payload.get("preset") or "standard")
    if preset not in ALLOWED_PAGE_STRUCTURES:
        raise ValueError("page_structure.preset 不受支持")
    expected_count = ALLOWED_PAGE_STRUCTURES[preset][0]
    try:
        page_count = int(structure.get("page_count") or payload.get("page_count") or expected_count)
    except (TypeError, ValueError):
        raise ValueError("page_structure.page_count 必须是整数")
    if page_count != expected_count:
        raise ValueError(f"页面结构 {preset} 必须使用 {expected_count} 页")
    return {"preset": preset, "page_count": page_count}


def _rule_snapshot(template: Dict[str, Any]) -> Dict[str, Any]:
    """条目只快照影响模型输出的规则，避免模板更新污染旧条目。"""
    fields = (
        "id", "name", "description", "visual_style", "palette", "composition",
        "character_bible", "copy_tone", "prohibited_elements", "page_structure",
        "ip_notice", "reference_images", "revision",
    )
    return _clone({field: template.get(field) for field in fields})


def normalize_template(
    payload: Dict[str, Any],
    template_id: Optional[str] = None,
    *,
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("模板必须是 JSON 对象")
    required = ("name", "visual_style", "palette", "composition", "copy_tone")
    values = {field: str(payload.get(field) or "").strip() for field in required}
    if any(not values[field] for field in required):
        raise ValueError("name、visual_style、palette、composition、copy_tone 不能为空")
    references = payload.get("reference_images", [])
    if not isinstance(references, list) or len(references) > MAX_REFERENCES:
        raise ValueError(f"reference_images 最多 {MAX_REFERENCES} 张")
    if any(not isinstance(value, str) for value in references):
        raise ValueError("reference_images 必须是字符串数组")
    now = _now()
    return {
        "id": template_id or f"template_{uuid.uuid4().hex[:12]}",
        "name": values["name"][:100],
        "description": str(payload.get("description") or "").strip()[:1000],
        "visual_style": values["visual_style"][:2000],
        "palette": values["palette"][:1000],
        "composition": values["composition"][:2000],
        "character_bible": str(payload.get("character_bible") or "").strip()[:4000],
        "copy_tone": values["copy_tone"][:2000],
        "prohibited_elements": _as_list(payload.get("prohibited_elements"))[:50],
        "page_structure": _page_structure(payload),
        "ip_notice": str(payload.get("ip_notice") or "默认生成原创角色与原创世界观；涉及第三方 IP 时需确认授权与平台规则。").strip()[:1000],
        "reference_images": list(references),
        "revision": int((previous or {}).get("revision", 0)) + 1,
        "created_at": (previous or {}).get("created_at") or now,
        "updated_at": now,
    }


def list_templates() -> List[Dict[str, Any]]:
    with _lock:
        return _clone(_templates())


def get_template(template_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        template = next((row for row in _templates() if row.get("id") == template_id), None)
        return _clone(template) if template else None


def _reference_dir(template_id: str) -> Path:
    if not re.fullmatch(r"template_[a-f0-9]{12}|[A-Za-z0-9_-]{1,100}", str(template_id)):
        raise ValueError("模板 ID 无效")
    path = (SERIES_ROOT / str(template_id) / "references").resolve()
    root = SERIES_ROOT.resolve()
    if os.path.commonpath([str(root), str(path)]) != str(root):
        raise ValueError("参考图路径无效")
    return path


def reference_path(template_id: str, filename: str, *, require_exists: bool = True) -> Path:
    if not isinstance(filename, str) or filename != Path(filename).name:
        raise ValueError("参考图文件名无效")
    path = (_reference_dir(template_id) / filename).resolve()
    directory = _reference_dir(template_id)
    if os.path.commonpath([str(directory), str(path)]) != str(directory):
        raise ValueError("参考图路径越界")
    if path.suffix.lower() not in ALLOWED_REFERENCE_EXTENSIONS:
        raise ValueError("参考图格式不受支持")
    if require_exists and not path.is_file():
        raise FileNotFoundError("参考图不存在")
    return path


def _store_reference(template_id: str, content: bytes, extension: str) -> str:
    extension = extension.lower()
    if extension not in ALLOWED_REFERENCE_EXTENSIONS:
        raise ValueError("参考图仅支持 PNG、JPG、JPEG 或 WEBP")
    if not content or len(content) > MAX_REFERENCE_BYTES:
        raise ValueError("单张参考图必须小于 10 MB")
    directory = _reference_dir(template_id)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"reference-{uuid.uuid4().hex[:12]}{extension}"
    path = reference_path(template_id, filename, require_exists=False)
    fd, temporary = tempfile.mkstemp(prefix=".reference-", dir=str(directory))
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return f"/api/series/templates/{template_id}/references/{filename}"


def _materialize_references(template: Dict[str, Any]) -> Dict[str, Any]:
    output: List[str] = []
    for value in template.get("reference_images", []):
        if value.startswith("data:"):
            match = re.fullmatch(r"data:([^;]+);base64,(.+)", value, re.S)
            if not match:
                raise ValueError("参考图 data URL 无效")
            try:
                content = base64.b64decode(match.group(2), validate=True)
            except (ValueError, base64.binascii.Error):
                raise ValueError("参考图 base64 无效")
            extension = mimetypes.guess_extension(match.group(1)) or ""
            if extension == ".jpe":
                extension = ".jpg"
            output.append(_store_reference(template["id"], content, extension))
        else:
            marker = f"/api/series/templates/{template['id']}/references/"
            if not value.startswith(marker):
                raise ValueError("reference_images 只能引用当前模板的本地参考图")
            reference_path(template["id"], value[len(marker):])
            output.append(value)
    template["reference_images"] = output
    return template


def create_template(payload: Dict[str, Any]) -> Dict[str, Any]:
    with _lock:
        template = normalize_template(payload)
        try:
            template = _materialize_references(template)
        except Exception:
            shutil.rmtree(SERIES_ROOT / template["id"], ignore_errors=True)
            raise
        templates = _templates()
        templates.insert(0, template)
        _write(TEMPLATES_FILE, "templates", templates)
        return _clone(template)


def update_template(template_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _lock:
        templates = _templates()
        for index, previous in enumerate(templates):
            if previous.get("id") != template_id:
                continue
            merged = _clone(previous)
            merged.update(payload)
            template = normalize_template(merged, template_id, previous=previous)
            template = _materialize_references(template)
            templates[index] = template
            _write(TEMPLATES_FILE, "templates", templates)
            return _clone(template)
    return None


def add_reference_images(template_id: str, uploads: Iterable[tuple[str, bytes]]) -> Dict[str, Any]:
    template = get_template(template_id)
    if not template:
        raise KeyError("系列模板不存在")
    uploads = list(uploads)
    if not uploads:
        raise ValueError("请上传至少一张参考图")
    if len(template.get("reference_images", [])) + len(uploads) > MAX_REFERENCES:
        raise ValueError(f"系列参考图总数最多 {MAX_REFERENCES} 张")
    urls = list(template.get("reference_images", []))
    created: List[Path] = []
    try:
        for filename, content in uploads:
            url = _store_reference(template_id, content, Path(filename).suffix)
            urls.append(url)
            created.append(reference_path(template_id, url.rsplit("/", 1)[-1]))
        updated = update_template(template_id, {"reference_images": urls})
        if not updated:
            raise KeyError("系列模板不存在")
        return updated
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def delete_template(template_id: str) -> bool:
    with _lock:
        if any(project.get("template_id") == template_id for project in _projects()):
            raise ValueError("该模板已被系列项目使用，不能删除")
        templates = _templates()
        remaining = [row for row in templates if row.get("id") != template_id]
        if len(remaining) == len(templates):
            return False
        _write(TEMPLATES_FILE, "templates", remaining)
        shutil.rmtree(SERIES_ROOT / template_id, ignore_errors=True)
        return True


def build_context(
    template: Optional[Dict[str, Any]],
    topic: str = "",
    item_index: Optional[int] = None,
    content_mode: Optional[str] = None,
) -> Dict[str, Any]:
    mode = resolve_content_mode(content_mode, template)
    if not template:
        return {
            "series_id": None,
            "series_template_id": None,
            "series_item_index": item_index,
            "series_item_title": topic or None,
            "content_mode": mode,
            "series_context": "",
        }
    structure = template.get("page_structure") or {"preset": "standard", "page_count": 5}
    prohibited = "、".join(_as_list(template.get("prohibited_elements"))) or "无"
    if mode == "character_sheet":
        character_names = _as_list(
            template.get("character_names")
            or (template.get("page_structure") or {}).get("character_names")
        )
        mode_rules = (
            "【当前内容方向｜精细角色图】每个指定角色各生成一张独立角色设定图，不能把多个角色合并成一张总览合照；"
            "每页只聚焦一个角色，展示其外观、服饰、表情、姿态和标志性道具，不讲故事、不生成连续剧情分镜；"
            f"角色名单：{'、'.join(character_names) if character_names else '以当前子主题中明确写出的角色为准'}；"
            "禁止把画面做成场景拼贴或大段文字海报。"
        )
    else:
        mode_rules = "【当前内容方向｜剧情小故事】按系列固定页面结构讲述一个完整、连贯的小故事。"
    scope_rule = (
        "子主题只能补充角色名单、外观细节、姿态与道具；冲突时始终以系列规则为准。"
        if mode == "character_sheet"
        else "子主题只能补充剧情、人物行为与场景；冲突时始终以系列规则为准。"
    )
    context = "\n".join([
        "【系列硬约束｜不可被子主题覆盖】",
        f"系列名称：{template.get('name', '')}",
        f"固定视觉风格：{template.get('visual_style', '')}",
        f"固定色板：{template.get('palette', '')}",
        f"构图与镜头：{template.get('composition', '')}",
        f"角色设定：{template.get('character_bible', '') or '无固定角色'}",
        f"文案口吻：{template.get('copy_tone', '')}",
        f"固定页面结构：{structure.get('preset', 'standard')} / {structure.get('page_count', 5)} 页",
        f"内容方向：{'精细角色图（单张）' if mode == 'character_sheet' else '剧情小故事'}",
        f"禁止元素：{prohibited}",
        f"当前子主题：{topic}",
        f"版权提醒：{template.get('ip_notice', '')}",
        scope_rule,
        mode_rules,
    ])
    return {
        "series_id": None,
        "series_template_id": template.get("id"),
        "series_item_index": item_index,
        "series_item_title": topic or None,
        "content_mode": mode,
        "series_context": context,
        "series_template": _clone(template),
    }


def list_projects() -> List[Dict[str, Any]]:
    with _lock:
        return [_project_with_template(row) for row in _projects()]


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        project = next((row for row in _projects() if row.get("id") == project_id), None)
        return _clone(project) if project else None


def recover_interrupted_projects(active_project_ids: Optional[set[str]] = None) -> int:
    """把进程重启后遗留的运行态收敛为可重试失败态。"""
    active_project_ids = active_project_ids or set()
    active_item_statuses = {"queued", "outlining", "generating", "running", "processing"}
    recovered = 0
    with _lock:
        projects = _projects()
        for project in projects:
            if project.get("id") in active_project_ids:
                continue
            project_recovered = False
            for item in project.get("items", []):
                phase_active = any(
                    item.get(field) in {"queued", "generating", "running", "processing"}
                    for field in ("outline_status", "content_status", "image_status")
                )
                if item.get("status") not in active_item_statuses and not phase_active:
                    continue
                item["status"] = "failed"
                for field in ("outline_status", "content_status", "image_status"):
                    if item.get(field) in {"queued", "generating", "running", "processing"}:
                        item[field] = "failed"
                item["error"] = "服务重启后检测到上次任务未完成，已停止该任务，请重试。"
                item["updated_at"] = _now()
                project_recovered = True
                recovered += 1
            if project_recovered:
                project["status"] = "partial"
                project["updated_at"] = _now()
        if recovered:
            _write(PROJECTS_FILE, "projects", projects)
    return recovered


def _project_with_template(project: Dict[str, Any]) -> Dict[str, Any]:
    result = _clone(project)
    result["template"] = get_template(project.get("template_id", ""))
    result["item_count"] = len(result.get("items", []))
    status_counts: Dict[str, int] = {}
    for item in result.get("items", []):
        status = str(item.get("status") or "draft")
        status_counts[status] = status_counts.get(status, 0) + 1
    result["status_counts"] = status_counts
    return result


def project_with_template(project: Dict[str, Any]) -> Dict[str, Any]:
    return _project_with_template(project)


def _make_item(
    template: Dict[str, Any],
    topic: str,
    index: int,
    topic_source: str,
    ip_acknowledged: bool = False,
    content_mode: str = "story",
) -> Dict[str, Any]:
    mode = normalize_content_mode(content_mode)
    snapshot = _rule_snapshot(template)
    snapshot["content_mode"] = mode
    character_names: List[str] = []
    if mode == "character_sheet":
        role_structure = character_page_structure(topic)
        character_names = extract_character_names(topic)
        snapshot["page_structure"] = role_structure
        snapshot["character_names"] = character_names
    context_data = build_context(snapshot, topic, index, mode)
    context = context_data["series_context"]
    return {
        "id": f"item_{uuid.uuid4().hex[:12]}",
        "index": index,
        "topic": topic,
        "topic_source": topic_source,
        "ip_acknowledged": ip_acknowledged,
        "content_mode": mode,
        "character_names": character_names,
        "record_id": None,
        "outline": "",
        "pages": [],
        "status": "draft",
        "outline_status": "pending",
        "content_status": "pending",
        "image_status": "pending",
        "error": None,
        "progress": {"current": 0, "total": snapshot["page_structure"]["page_count"], "percent": 0},
        "template_revision": snapshot["revision"],
        "template_snapshot": snapshot,
        "series_context_snapshot": context,
        "created_at": _now(),
        "updated_at": _now(),
    }


def _normalize_topic_source(value: Any) -> str:
    value = str(value or "user")
    if value not in {"user", "system", "user_modified_system"}:
        raise ValueError("topic_source 必须为 user、system 或 user_modified_system")
    return value


def create_project(
    template_id: str,
    topics: Any = None,
    topic_source: str = "user",
    name: str = "",
    allow_third_party_ip: bool = False,
    content_mode: str = "story",
) -> Dict[str, Any]:
    template = get_template(template_id)
    if not template:
        raise ValueError("系列模板不存在")
    topics = [] if topics is None else _validate_topics(topics)
    source = _normalize_topic_source(topic_source)
    mode = normalize_content_mode(content_mode)
    if not isinstance(allow_third_party_ip, bool):
        raise ValueError("allow_third_party_ip 必须是布尔值")
    project_name = re.sub(r"\s+", " ", str(name or template.get("name") or "未命名合集")).strip()
    if not project_name or len(project_name) > 100:
        raise ValueError("合集名称必须为 1-100 个字符")
    now = _now()
    items = [
        _make_item(template, topic, index, source, allow_third_party_ip, mode)
        for index, topic in enumerate(topics)
    ]
    project = {
        "id": f"series_{uuid.uuid4().hex[:12]}",
        "name": project_name,
        "template_id": template_id,
        "template_revision": template["revision"],
        "topics": [item["topic"] for item in items],
        "items": items,
        "status": "draft",
        "allow_third_party_ip": allow_third_party_ip,
        "content_mode": mode,
        "progress": {"current": 0, "total": len(items), "percent": 0},
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        projects = _projects()
        projects.insert(0, project)
        _write(PROJECTS_FILE, "projects", projects)
    return _project_with_template(project)


def save_project(project: Dict[str, Any]) -> Dict[str, Any]:
    value = _clone(project)
    value.pop("template", None)
    value["topics"] = [item.get("topic", "") for item in value.get("items", [])]
    value["updated_at"] = _now()
    with _lock:
        projects = _projects()
        for index, previous in enumerate(projects):
            if previous.get("id") == value.get("id"):
                projects[index] = value
                _write(PROJECTS_FILE, "projects", projects)
                return _project_with_template(value)
    raise KeyError("系列项目不存在")


def append_project_items(
    project_id: str,
    topics: Any,
    topic_source: str = "user",
    ip_acknowledged: bool = False,
    content_mode: str = "story",
) -> Dict[str, Any]:
    clean = _validate_topics(topics, allow_empty=False)
    source = _normalize_topic_source(topic_source)
    mode = normalize_content_mode(content_mode)
    if not isinstance(ip_acknowledged, bool):
        raise ValueError("ip_acknowledged 必须是布尔值")
    project = get_project(project_id)
    if not project:
        raise KeyError("系列项目不存在")
    template = get_template(project["template_id"])
    if not template:
        raise ValueError("系列模板不存在")
    existing = {re.sub(r"\s+", " ", str(item.get("topic", ""))).strip().casefold() for item in project.get("items", [])}
    added = []
    duplicates = []
    for topic in clean:
        if topic.casefold() in existing:
            duplicates.append(topic)
            continue
        item = _make_item(template, topic, len(project["items"]), source, ip_acknowledged, mode)
        project["items"].append(item)
        added.append(item)
        existing.add(topic.casefold())
    project["progress"] = {
        "current": sum(1 for item in project["items"] if item.get("status") in {"completed", "failed"}),
        "total": len(project["items"]),
        "percent": 0,
    }
    project["progress"]["percent"] = round(
        project["progress"]["current"] * 100 / max(1, project["progress"]["total"]), 1
    )
    if added:
        project["status"] = "draft"
    saved = save_project(project)
    return {"project": saved, "items": _clone(added), "duplicates": duplicates}


def list_project_items(
    project_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
    query: str = "",
    status: str = "",
) -> Dict[str, Any]:
    project = get_project(project_id)
    if not project:
        raise KeyError("系列项目不存在")
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    query_key = str(query or "").strip().casefold()
    status = str(status or "").strip()
    rows = []
    for item in project.get("items", []):
        if query_key and query_key not in str(item.get("topic", "")).casefold():
            continue
        status_values = {str(item.get(key, "")) for key in ("status", "outline_status", "content_status", "image_status")}
        if status and status not in status_values:
            continue
        rows.append(item)
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": _clone(rows[start:start + page_size]),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
        "project": _project_with_template(project),
    }


def get_project_item(project: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    item = next((row for row in project.get("items", []) if row.get("id") == item_id), None)
    if not item:
        raise KeyError("系列子主题不存在")
    return item


def update_item(project: Dict[str, Any], item_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    item = get_project_item(project, item_id)
    current_mode = resolve_content_mode(
        item.get("content_mode"),
        item.get("template_snapshot"),
        item.get("series_context_snapshot", ""),
    )
    requested_mode = (
        normalize_content_mode(payload.get("content_mode"))
        if "content_mode" in payload and payload.get("content_mode") is not None
        and str(payload.get("content_mode")).strip()
        else current_mode
    )
    if requested_mode != current_mode:
        if item.get("record_id") or item.get("status") not in {"draft", "failed"}:
            raise ValueError("已开始生成的子主题不能切换内容方向")
        item["content_mode"] = requested_mode
        snapshot = _clone(item.get("template_snapshot") or get_template(project["template_id"]))
        if not snapshot:
            raise ValueError("系列模板不存在")
        snapshot["content_mode"] = requested_mode
        snapshot["page_structure"] = (
            character_page_structure(item.get("topic", ""))
            if requested_mode == "character_sheet"
            else (get_template(project["template_id"]) or {}).get("page_structure", {"preset": "standard", "page_count": 5})
        )
        item["character_names"] = list(snapshot["page_structure"].get("character_names", []))
        if requested_mode == "character_sheet":
            item["character_names"] = extract_character_names(item.get("topic", ""))
            snapshot["character_names"] = list(item["character_names"])
        else:
            snapshot.pop("character_names", None)
        item["template_snapshot"] = snapshot
        item["template_revision"] = snapshot.get("revision")
        item["series_context_snapshot"] = build_context(snapshot, item.get("topic", ""), item.get("index"), requested_mode)["series_context"]
        item["progress"] = {"current": 0, "total": snapshot["page_structure"]["page_count"], "percent": 0}
        item.update({"outline": "", "pages": [], "outline_status": "pending", "content_status": "pending", "image_status": "pending", "status": "draft", "error": None})
    if "topic" in payload:
        topic = _validate_topics([payload["topic"]], allow_empty=False)[0]
        topic_key = re.sub(r"\s+", " ", topic).strip().casefold()
        duplicate = next((row for row in project["items"] if row["id"] != item_id and re.sub(r"\s+", " ", row["topic"]).strip().casefold() == topic_key), None)
        if duplicate:
            raise ValueError("项目中已存在相同主题")
        if topic != item["topic"]:
            item["topic"] = topic
            item["topic_source"] = "user_modified_system" if item.get("topic_source") == "system" else "user"
            snapshot = item.get("template_snapshot") or get_template(project["template_id"])
            item["template_snapshot"] = snapshot
            if requested_mode == "character_sheet":
                snapshot = _clone(snapshot)
                snapshot["page_structure"] = character_page_structure(topic)
                snapshot["character_names"] = extract_character_names(topic)
                item["template_snapshot"] = snapshot
                item["character_names"] = list(snapshot["character_names"])
            item["series_context_snapshot"] = build_context(snapshot, topic, item["index"], item.get("content_mode"))["series_context"]
            item.update({"outline": "", "pages": [], "outline_status": "pending", "content_status": "pending", "image_status": "pending", "status": "draft", "error": None})
    if "outline" in payload:
        item["outline"] = str(payload.get("outline") or "").strip()
    if "pages" in payload:
        errors = validate_pages(payload.get("pages"), item["template_snapshot"])
        if errors:
            raise ValueError("；".join(errors))
        item["pages"] = _clone(payload["pages"])
        item["outline_status"] = "ready"
        item["status"] = "outline_ready"
        item["error"] = None
    item["updated_at"] = _now()
    return save_project(project)


def delete_project_item(project_id: str, item_id: str) -> Dict[str, Any]:
    """从合集移除一个子主题；独立历史记录和图片目录不做破坏性删除。"""
    project = get_project(project_id)
    if not project:
        raise KeyError("系列项目不存在")
    item = get_project_item(project, item_id)
    if item.get("status") in {"queued", "outlining", "generating", "running", "processing"}:
        raise ValueError("该子主题正在生成，完成或停止任务后才能删除")
    removed = _clone(item)
    remaining = [row for row in project.get("items", []) if row.get("id") != item_id]
    # 列表序号只属于当前合集视图，删除后重新排列；历史记录中的原始 index 保持不变。
    for index, row in enumerate(remaining):
        row["index"] = index
    project["items"] = remaining
    project["topics"] = [row.get("topic", "") for row in remaining]
    total = len(remaining)
    processed = sum(1 for row in remaining if row.get("status") in {"completed", "failed"})
    completed = sum(1 for row in remaining if row.get("status") == "completed")
    project["progress"] = {
        "current": processed,
        "total": total,
        "percent": round(processed * 100 / max(1, total), 1),
    }
    if not remaining:
        project["status"] = "draft"
    elif completed == total:
        project["status"] = "completed"
    elif processed == total:
        project["status"] = "partial" if completed else "failed"
    elif any(row.get("status") in {"queued", "outlining", "generating", "running", "processing"} for row in remaining):
        project["status"] = "generating"
    elif any(row.get("status") == "confirmed" for row in remaining):
        project["status"] = "confirmed"
    elif any(row.get("status") == "outline_ready" for row in remaining):
        project["status"] = "outline_ready"
    else:
        project["status"] = "draft"
    save_project(project)
    return removed


def select_items(project: Dict[str, Any], item_ids: Any = None, *, eligible_statuses: Optional[set[str]] = None) -> List[Dict[str, Any]]:
    if item_ids is None:
        selected = [item for item in project.get("items", []) if not eligible_statuses or item.get("status") in eligible_statuses][:MAX_BATCH_ITEMS]
    else:
        if not isinstance(item_ids, list) or any(not isinstance(value, str) for value in item_ids):
            raise ValueError("item_ids 必须是字符串数组")
        if len(item_ids) > MAX_BATCH_ITEMS:
            raise ValueError(f"单次最多处理 {MAX_BATCH_ITEMS} 个子主题")
        wanted = list(dict.fromkeys(item_ids))
        mapping = {item["id"]: item for item in project.get("items", [])}
        missing = [item_id for item_id in wanted if item_id not in mapping]
        if missing:
            raise KeyError(f"系列子主题不存在：{missing[0]}")
        selected = [mapping[item_id] for item_id in wanted]
        invalid = [item for item in selected if eligible_statuses and item.get("status") not in eligible_statuses]
        if invalid:
            raise ValueError(f"子主题当前状态不可执行该操作：{invalid[0].get('topic')}")
    return selected


def validate_pages(pages: Any, template: Dict[str, Any]) -> List[str]:
    structure = template.get("page_structure") or {"preset": "standard", "page_count": 5}
    if structure.get("preset") == "character_sheet":
        try:
            expected_count = max(1, min(MAX_CHARACTER_NAMES, int(structure.get("page_count") or 1)))
        except (TypeError, ValueError):
            expected_count = 1
        expected_types = list(structure.get("page_types") or (["cover"] + (["content"] * max(0, expected_count - 1))))
        if len(expected_types) != expected_count:
            expected_types = ["cover"] + (["content"] * max(0, expected_count - 1))
    else:
        expected_count, expected_types = ALLOWED_PAGE_STRUCTURES.get(structure.get("preset", "standard"), ALLOWED_PAGE_STRUCTURES["standard"])
    if not isinstance(pages, list) or len(pages) != expected_count:
        return [f"页面数量必须为 {expected_count} 页"]
    errors = []
    actual_types = []
    text_parts = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or not str(page.get("content") or "").strip():
            errors.append(f"第 {index + 1} 页内容不能为空")
            actual_types.append("")
            continue
        actual_types.append(str(page.get("type") or "content"))
        text_parts.append(str(page.get("content")))
    if actual_types != expected_types:
        errors.append(f"页面类型必须按 {structure.get('preset', 'standard')} 结构排列")
    joined = " ".join(text_parts).casefold()
    for term in _as_list(template.get("prohibited_elements")):
        if _contains_prohibited_element(joined, term):
            errors.append(f"大纲包含系列禁止元素：{term}")
    return errors


def validate_content(content: Dict[str, Any], template: Dict[str, Any]) -> List[str]:
    if not isinstance(content, dict):
        return ["文案返回格式不正确"]
    text = " ".join([
        *[str(value) for value in content.get("titles", [])],
        str(content.get("copywriting") or ""),
        *[str(value) for value in content.get("tags", [])],
    ]).casefold()
    return [f"文案包含系列禁止元素：{term}" for term in _as_list(template.get("prohibited_elements")) if _contains_prohibited_element(text, term)]


def _contains_prohibited_element(text: str, term: str) -> bool:
    """只拦截实际出现的禁用元素，忽略“禁止/不要出现 X”的规则说明。"""
    normalized = str(text or "").casefold()
    needle = str(term or "").strip().casefold()
    if not needle:
        return False
    start = 0
    negative_prefix = re.compile(
        r"(?:禁止元素|禁止|请勿|切勿|切忌|勿|不要|不得|不可|避免|去除|去掉|不添加|不含|不|无|without|without\s+any|no)"
        r"[^。！？\n]{0,16}$",
        re.IGNORECASE,
    )
    while True:
        index = normalized.find(needle, start)
        if index < 0:
            return False
        prefix = normalized[max(0, index - 24):index]
        if not negative_prefix.search(prefix):
            return True
        start = index + len(needle)


def read_reference_bytes(template_snapshot: Dict[str, Any]) -> List[bytes]:
    result = []
    template_id = str(template_snapshot.get("id") or "")
    marker = f"/api/series/templates/{template_id}/references/"
    for url in template_snapshot.get("reference_images", []):
        if not isinstance(url, str) or not url.startswith(marker):
            continue
        result.append(reference_path(template_id, url[len(marker):]).read_bytes())
    return result


def topic_suggestions(project_id: str, allow_third_party_ip: bool = False) -> List[Dict[str, Any]]:
    project = get_project(project_id)
    if not project:
        raise KeyError("系列项目不存在")
    template = get_template(project["template_id"])
    if not template:
        raise ValueError("系列模板不存在")
    name = project.get("name") or template.get("name") or "这个系列"
    existing = {
        re.sub(r"\s+", " ", str(item.get("topic") or "")).strip().casefold()
        for item in project.get("items", [])
    }
    patterns = [
        ("第一次接触时最容易忽略的 3 件事", "用新人视角建立系列入口"),
        ("一个常见误区的完整拆解", "以反差和纠错增强收藏价值"),
        ("可直接照做的实战清单", "提供明确步骤和行动抓手"),
        ("从入门到进阶的关键分水岭", "承接系列成长路径"),
        ("7 天实践后的真实变化", "用连续记录形成长期追更感"),
        ("幕后设定与创作手记", "补充系列世界观与制作过程"),
        ("读者最常问的 5 个问题", "聚合高频疑问形成互动内容"),
        ("如果把主角放进反常识的一天", "用意外情境扩展剧情空间"),
        ("一次失败尝试带来的新发现", "用真实挫折增强共鸣"),
        ("只保留一个关键道具会发生什么", "用单一变量形成鲜明记忆点"),
        ("同一件事的三种不同结局", "通过分支叙事提高互动感"),
        ("普通一天里最值得记录的瞬间", "从日常细节持续扩展系列"),
    ]
    result = []
    target_originals = 4 if allow_third_party_ip else 5
    issue = 1
    while len(result) < target_originals:
        pattern, brief = patterns[(issue - 1) % len(patterns)]
        cycle = (issue - 1) // len(patterns)
        suffix = f"（第 {cycle + 1} 期）" if cycle else ""
        title = f"{name}｜{pattern}{suffix}"
        issue += 1
        if title.casefold() in existing:
            continue
        result.append({
            "topic": title, "reason": brief, "uses_ip": False,
            "title": title, "brief": brief, "ip_related": False,
        })
        existing.add(title.casefold())
    # 开关仅放宽用户明确指定的第三方 IP，不主动编造品牌或角色。
    if allow_third_party_ip and len(result) < 5:
        ip_issue = 1
        title = f"{name}｜用户指定 IP 的同人灵感实验"
        while title.casefold() in existing:
            ip_issue += 1
            title = f"{name}｜用户指定 IP 的同人灵感实验（第 {ip_issue} 期）"
        brief = "仅在已有授权或合理使用范围内创作"
        result.append({
            "topic": title, "reason": brief, "uses_ip": True,
            "title": title, "brief": brief, "ip_related": True,
        })
    return result[:5]


def series_context_from_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """现有 outline/content/image/retry API 共用的可选上下文解析器。"""
    payload = payload or {}
    project_id = payload.get("series_project_id") or payload.get("series_id")
    item_id = payload.get("series_item_id")
    template_id = payload.get("series_template_id")
    if project_id and item_id:
        project = get_project(str(project_id))
        if not project:
            raise ValueError("系列项目不存在")
        item = get_project_item(project, str(item_id))
        snapshot = item.get("template_snapshot") or get_template(project["template_id"])
        mode = resolve_content_mode(
            item.get("content_mode"),
            snapshot,
            item.get("series_context_snapshot", ""),
        )
        frozen_context = item.get("series_context_snapshot") or ""
        context = (
            frozen_context
            if frozen_context_matches_mode(frozen_context, mode)
            else build_context(snapshot, item.get("topic", ""), item.get("index"), mode)["series_context"]
        )
        return {
            "series_id": project["id"],
            "series_project_id": project["id"],
            "series_item_id": item["id"],
            "series_template_id": snapshot.get("id") if snapshot else project["template_id"],
            "series_item_index": item.get("index"),
            "series_item_title": item.get("topic"),
            "content_mode": mode,
            # Rebuild legacy items with their explicit mode.  Without this
            # argument a character-sheet item whose frozen context is absent
            # would be reconstructed as a story item.
            "series_context": context,
            "series_template": _clone(snapshot),
        }
    template = get_template(str(template_id)) if template_id else None
    resolved_mode = resolve_content_mode(
        payload.get("content_mode"),
        template,
        "",
    )
    context = build_context(
        template,
        payload.get("series_item_title") or payload.get("topic") or "",
        payload.get("series_item_index"),
        resolved_mode,
    )
    context.update({"series_id": project_id, "series_project_id": project_id, "series_item_id": item_id})
    return context
