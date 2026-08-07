"""长期系列合集模板、条目和生成 API。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request, send_file

from backend.services import series as series_service
from backend.services.content import get_content_service
from backend.services.history import get_history_service
from backend.services.image import get_image_service
from backend.services.outline import get_outline_service
from .utils import api_error_response, validation_error

logger = logging.getLogger(__name__)
_active_projects: set[str] = set()
_active_lock = threading.RLock()


def _ok(status: int = 200, **payload):
    return jsonify({"success": True, **payload}), status


def _error(message: str, status: int = 400):
    return api_error_response(
        validation_error(message, message),
        context={"endpoint": "/api/series"},
        status=status,
    )


def _project_or_error(project_id: str):
    project = series_service.get_project(project_id)
    return (project, None) if project else (None, _error("系列项目不存在", 404))


def _active_project_error(project_id: str):
    if project_id in _active_projects:
        return _error("该合集已有任务正在执行，请等待当前批次结束后再修改", 409)
    return None


def _item_or_error(project: Dict[str, Any], item_id: str):
    try:
        return series_service.get_project_item(project, item_id), None
    except KeyError as exc:
        return None, _error(str(exc), 404)


def _context(project: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = item.get("template_snapshot") or series_service.get_template(project["template_id"])
    content_mode = series_service.normalize_content_mode(item.get("content_mode", "story"))
    return {
        "series_id": project["id"],
        "series_project_id": project["id"],
        "series_item_id": item["id"],
        "series_template_id": snapshot.get("id") if snapshot else project["template_id"],
        "series_item_index": item.get("index"),
        "series_item_title": item.get("topic"),
        "content_mode": content_mode,
        "series_context": item.get("series_context_snapshot") or series_service.build_context(snapshot, item.get("topic", ""), item.get("index"))["series_context"],
        "series_template": snapshot,
    }


def _save_item_error(project: Dict[str, Any], item: Dict[str, Any], phase: str, exc: Exception) -> None:
    item["status"] = "failed"
    item[f"{phase}_status"] = "failed"
    item["error"] = str(exc)
    item["updated_at"] = series_service._now()
    series_service.save_project(project)


def _generate_outline(project: Dict[str, Any], item: Dict[str, Any], outline_service=None) -> bool:
    item.update({"status": "outlining", "outline_status": "generating", "error": None, "updated_at": series_service._now()})
    series_service.save_project(project)
    snapshot = item["template_snapshot"]
    try:
        mode = series_service.normalize_content_mode(item.get("content_mode", "story"))
        if mode == "character_sheet":
            # 角色图不需要模型先编造故事；每个角色生成一个独立页面和独立图片。
            names = item.get("character_names") or series_service.extract_character_names(item["topic"])
            item["character_names"] = names[:series_service.MAX_CHARACTER_NAMES]
            pages = [{
                "index": index,
                "type": "cover" if index == 0 else "content",
                "content": (
                    f"[{'封面' if index == 0 else '内容'}]\n精细角色设定图：{name}\n"
                    f"所属主题：{item['topic']}\n"
                    "本页只展示这一名角色，保持清晰的发型、服饰、面部特征、表情、姿态和标志性道具；"
                    "采用系列固定像素风与色板，单张 3:4 竖版构图；不讲连续故事，不与其他角色合并成总览合照，"
                    "不添加大段文字。"
                ),
            } for index, name in enumerate(item["character_names"])]
            outline_text = "\n\n<page>\n\n".join(page["content"] for page in pages)
        else:
            references = series_service.read_reference_bytes(snapshot)
            service = outline_service or get_outline_service()
            result = service.generate_outline(item["topic"], references or None, **_context(project, item))
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "大纲生成失败")
            pages = result.get("pages") or []
            outline_text = str(result.get("outline") or "")
        errors = series_service.validate_pages(pages, snapshot)
        if errors:
            raise ValueError("；".join(errors))
        item.update({
            "outline": outline_text,
            "pages": pages,
            "status": "outline_ready",
            "outline_status": "ready",
            "content_status": "pending",
            "image_status": "pending",
            "error": None,
            "progress": {"current": 0, "total": len(pages), "percent": 0},
            "updated_at": series_service._now(),
        })
        series_service.save_project(project)
        return True
    except Exception as exc:
        logger.exception("系列大纲生成失败: project=%s item=%s", project.get("id"), item.get("id"))
        _save_item_error(project, item, "outline", exc)
        return False


def _confirm_item(project: Dict[str, Any], item: Dict[str, Any]) -> Optional[str]:
    errors = series_service.validate_pages(item.get("pages"), item["template_snapshot"])
    if errors:
        item["error"] = "；".join(errors)
        series_service.save_project(project)
        return item["error"]
    item.update({"outline_status": "confirmed", "status": "confirmed", "error": None, "updated_at": series_service._now()})
    # 条目级确认也要同步项目状态，否则列表页会继续把仅有一篇的合集显示成
    # “大纲待确认”，虽然条目已经可以进入生成阶段。
    if any(row.get("outline_status") == "confirmed" for row in project.get("items", [])):
        project["status"] = "confirmed"
    series_service.save_project(project)
    return None


def _fallback_character_content(item: Dict[str, Any]) -> Dict[str, Any]:
    """角色图模式的文案兜底，避免文本模型格式异常阻塞图片生成。"""
    topic = str(item.get("topic") or "像素角色")
    names = [str(name).strip() for name in (item.get("character_names") or []) if str(name).strip()]
    subject = "、".join(names) or topic
    count = len(names) or len(item.get("pages") or []) or 1
    return {
        "success": True,
        "titles": [
            f"{topic}｜{count}张8-bit像素角色图",
            f"像素角色设定图：{subject}",
            f"{subject}的精细像素素材合集",
        ],
        "copywriting": (
            f"本组为{topic}的精细像素角色设定图，共{count}张。"
            f"每页独立展示一名角色：{subject}。"
            "画面统一采用系列固定像素风与色板，重点保留角色的外观、服饰、表情、姿态和标志性道具，"
            "不讲连续剧情，方便逐张查看、保存和制作。"
        ),
        "tags": ["像素画", "8bit", "角色设定图", "像素风素材", "创作参考"],
    }


def _update_project_progress(project: Dict[str, Any]) -> None:
    items = project.get("items", [])
    done = sum(1 for item in items if item.get("status") == "completed")
    processed = sum(1 for item in items if item.get("status") in {"completed", "failed"})
    project["progress"] = {
        "current": processed,
        "total": len(items),
        "percent": round(processed * 100 / max(1, len(items)), 1),
    }
    if items and done == len(items):
        project["status"] = "completed"
    elif processed and processed == len(items):
        project["status"] = "partial" if done else "failed"
    elif processed:
        project["status"] = "partial"
    else:
        project["status"] = "draft"
    series_service.save_project(project)


def _settle_background_failure(project_id: str, item_ids: List[str], exc: Exception) -> None:
    project = series_service.get_project(project_id)
    if not project:
        return
    wanted = set(item_ids)
    for item in project.get("items", []):
        if item.get("id") not in wanted:
            continue
        if item.get("status") in {"queued", "outlining", "generating", "running", "processing"}:
            item["status"] = "failed"
        for field in ("outline_status", "content_status", "image_status"):
            if item.get(field) in {"queued", "generating", "running", "processing"}:
                item[field] = "failed"
        item["error"] = str(exc)
        item["updated_at"] = series_service._now()
    _update_project_progress(project)


def _generate_item(project: Dict[str, Any], item: Dict[str, Any], history, content_service, image_service) -> bool:
    if item.get("outline_status") != "confirmed":
        _save_item_error(project, item, "image", ValueError("请先确认该子主题大纲"))
        return False
    snapshot = item["template_snapshot"]
    context = _context(project, item)
    item.update({
        "status": "generating",
        "content_status": "generating",
        "image_status": "pending",
        "error": None,
        "image_errors": {},
        "failed_indices": [],
        "progress": {"current": 0, "total": len(item.get("pages", [])), "percent": 0},
    })
    series_service.save_project(project)
    try:
        record_id = item.get("record_id")
        if not record_id:
            record_id = history.create_record(
                item["topic"],
                {"raw": item.get("outline", ""), "pages": item.get("pages", [])},
                series_id=project["id"],
                series_project_id=project["id"],
                series_template_id=snapshot.get("id"),
                series_item_index=item.get("index"),
                series_item_title=item.get("topic"),
                series_item_id=item.get("id"),
                series_template_revision=item.get("template_revision"),
                series_template_snapshot=snapshot,
                series_context_snapshot=item.get("series_context_snapshot"),
                series_topic_source=item.get("topic_source"),
                series_content_mode=item.get("content_mode", "story"),
            )
            item["record_id"] = record_id
            series_service.save_project(project)

        content = content_service.generate_content(item["topic"], item.get("outline", ""), **context)
        if not content.get("success"):
            if series_service.normalize_content_mode(item.get("content_mode", "story")) == "character_sheet":
                # 图片和文案是两个独立产物；角色图文案接口格式异常时，
                # 使用确定性兜底文案继续生成图片，避免整篇作品被错误标记为“图片失败”。
                logger.warning(
                    "角色图文案生成失败，使用兜底文案继续生图: project=%s item=%s error=%s",
                    project.get("id"), item.get("id"), content.get("error"),
                )
                content = _fallback_character_content(item)
            else:
                raise RuntimeError(content.get("error") or "成品文案生成失败")
        content_errors = series_service.validate_content(content, snapshot)
        if content_errors:
            raise ValueError("；".join(content_errors))
        history.update_record(record_id, content={
            "titles": content.get("titles") or [],
            "copywriting": content.get("copywriting") or "",
            "tags": content.get("tags") or [],
            "status": "done",
        })
        item["content_status"] = "completed"
        item["image_status"] = "generating"
        series_service.save_project(project)

        references = series_service.read_reference_bytes(snapshot)
        reservation = image_service.prepare_generation(item["pages"], record_id=record_id, force=True, **context)
        task_id = reservation["task_id"]
        final = None
        for event in image_service.generate_images(
            item["pages"],
            task_id,
            item.get("outline", ""),
            user_images=references or None,
            user_topic=item["topic"],
            record_id=record_id,
            force=True,
            prepared=True,
            cached=reservation.get("cached", False),
            **context,
        ):
            if event.get("event") == "complete":
                current = int(item.get("progress", {}).get("current", 0)) + 1
                total = len(item.get("pages", []))
                item["progress"] = {"current": current, "total": total, "percent": round(current * 100 / max(1, total), 1)}
                series_service.save_project(project)
            if event.get("event") == "error":
                data = event.get("data") or {}
                index = data.get("index")
                if isinstance(index, int):
                    failure = data.get("error") or data.get("message") or "该页图片生成失败"
                    item.setdefault("image_errors", {})[str(index)] = failure
                    item.setdefault("failed_indices", []).append(index)
                    item["failed_indices"] = sorted(set(item["failed_indices"]))
                    # 历史记录同步保存逐页错误，刷新或服务重启后仍能看到原因。
                    history.update_record(record_id, images={"errors": {str(index): failure}})
                    series_service.save_project(project)
            if event.get("event") == "finish":
                final = event.get("data") or {}
        if not final or not final.get("success"):
            status = (final or {}).get("status", "failed")
            item["image_status"] = "partial" if status == "partial" else "failed"
            final_errors = (final or {}).get("failed_errors") or {}
            for index, failure in final_errors.items():
                item.setdefault("image_errors", {}).setdefault(str(index), failure)
            item["failed_indices"] = sorted({
                *[int(index) for index in ((final or {}).get("failed_indices") or []) if str(index).isdigit()],
                *[int(index) for index in item.get("image_errors", {}) if str(index).isdigit()],
            })
            raise RuntimeError((final or {}).get("error") or "图片生成未全部完成")
        item.update({
            "status": "completed",
            "image_status": "completed",
            "error": None,
            "image_errors": {},
            "failed_indices": [],
            "progress": {"current": len(item["pages"]), "total": len(item["pages"]), "percent": 100},
            "updated_at": series_service._now(),
        })
        series_service.save_project(project)
        return True
    except Exception as exc:
        logger.exception("系列子作品生成失败: project=%s item=%s", project.get("id"), item.get("id"))
        item["status"] = "failed"
        if item.get("content_status") == "generating":
            item["content_status"] = "failed"
        if item.get("image_status") == "generating":
            item["image_status"] = "failed"
        item["error"] = str(exc)
        item["updated_at"] = series_service._now()
        series_service.save_project(project)
        return False


def _run_generation(project_id: str, item_ids: List[str]) -> None:
    try:
        project = series_service.get_project(project_id)
        if not project:
            return
        selected = series_service.select_items(project, item_ids)
        project["status"] = "generating"
        series_service.save_project(project)
        history = get_history_service()
        content_service = get_content_service()
        image_service = get_image_service()
        # 单项目内严格串行；某一项失败后继续下一项。
        for item in selected:
            _generate_item(project, item, history, content_service, image_service)
        _update_project_progress(project)
    except Exception as exc:
        logger.exception("系列后台生成任务异常: project=%s", project_id)
        _settle_background_failure(project_id, item_ids, exc)
    finally:
        with _active_lock:
            _active_projects.discard(project_id)


def _run_retry_failed_item(project_id: str, item_id: str) -> None:
    """只补生成系列子作品缺失的图片，不重新生成已成功页面。"""
    try:
        project = series_service.get_project(project_id)
        if not project:
            return
        item = series_service.get_project_item(project, item_id)
        record_id = item.get("record_id")
        history = get_history_service()
        record = history.get_record(record_id, sync_images=True) if record_id else None
        if not record:
            raise ValueError("该子主题没有可恢复的历史成品")
        task_id = (record.get("images") or {}).get("task_id")
        if not task_id:
            raise ValueError("该子主题没有图片任务记录")
        generated = (record.get("images") or {}).get("generated") or []
        pages = [
            page for page in (record.get("outline") or {}).get("pages", [])
            if not (isinstance(page.get("index"), int) and page["index"] < len(generated) and generated[page["index"]])
        ]
        if not pages:
            item.update({
                "status": "completed",
                "image_status": "completed",
                "error": None,
                "image_errors": {},
                "failed_indices": [],
                "progress": {"current": len(generated), "total": len(record.get("outline", {}).get("pages", [])), "percent": 100},
                "updated_at": series_service._now(),
            })
            _update_project_progress(project)
            return

        snapshot = item.get("template_snapshot") or series_service.get_template(project["template_id"])
        references = series_service.read_reference_bytes(snapshot) if snapshot else []
        item.setdefault("image_errors", {})
        for page in pages:
            item["image_errors"].setdefault(str(page["index"]), "该页图片生成失败，正在等待补全。")
        item["failed_indices"] = sorted(page["index"] for page in pages)
        item["progress"] = {
            "current": sum(1 for filename in generated if filename),
            "total": len(record.get("outline", {}).get("pages", [])),
            "percent": round(sum(1 for filename in generated if filename) * 100 / max(1, len(record.get("outline", {}).get("pages", []))), 1),
        }
        series_service.save_project(project)

        image_service = get_image_service()
        for event in image_service.retry_failed_images(
            task_id,
            pages,
            record_id=record_id,
            series_context=item.get("series_context_snapshot") or _context(project, item).get("series_context", ""),
            full_outline=item.get("outline", ""),
            user_topic=item.get("topic", ""),
            user_images=references or None,
        ):
            data = event.get("data") or {}
            index = data.get("index")
            if event.get("event") == "complete" and isinstance(index, int):
                item.get("image_errors", {}).pop(str(index), None)
                item["failed_indices"] = [value for value in item.get("failed_indices", []) if value != index]
                current_record = history.get_record(record_id, sync_images=True) or record
                current_generated = (current_record.get("images") or {}).get("generated") or []
                total = len((current_record.get("outline") or {}).get("pages", []))
                item["progress"] = {"current": sum(1 for filename in current_generated if filename), "total": total, "percent": round(sum(1 for filename in current_generated if filename) * 100 / max(1, total), 1)}
                series_service.save_project(project)
            elif event.get("event") == "error" and isinstance(index, int):
                item.setdefault("image_errors", {})[str(index)] = data.get("error") or data.get("message") or "该页图片补全失败"
                if index not in item.setdefault("failed_indices", []):
                    item["failed_indices"].append(index)
                item["failed_indices"] = sorted(set(item["failed_indices"]))
                series_service.save_project(project)

        current_record = history.get_record(record_id, sync_images=True) or record
        current_generated = (current_record.get("images") or {}).get("generated") or []
        total = len((current_record.get("outline") or {}).get("pages", []))
        missing = [page["index"] for page in (current_record.get("outline") or {}).get("pages", []) if not (page["index"] < len(current_generated) and current_generated[page["index"]])]
        item["failed_indices"] = missing
        item["progress"] = {"current": total - len(missing), "total": total, "percent": round((total - len(missing)) * 100 / max(1, total), 1)}
        if missing:
            item["status"] = "failed"
            item["image_status"] = "partial" if current_generated else "failed"
            item["error"] = f"仍有 {len(missing)} 张图片未补全"
        else:
            item.update({"status": "completed", "image_status": "completed", "error": None, "image_errors": {}})
        item["updated_at"] = series_service._now()
        _update_project_progress(project)
    except Exception as exc:
        logger.exception("系列失败图片补全异常: project=%s item=%s", project_id, item_id)
        project = series_service.get_project(project_id)
        if project:
            try:
                item = series_service.get_project_item(project, item_id)
                item.update({"status": "failed", "image_status": "failed", "error": str(exc), "updated_at": series_service._now()})
                series_service.save_project(project)
            except Exception:
                logger.exception("保存系列失败图片补全状态失败: project=%s item=%s", project_id, item_id)
    finally:
        with _active_lock:
            _active_projects.discard(project_id)


def _run_outline_generation(project_id: str, item_ids: List[str]) -> None:
    try:
        project = series_service.get_project(project_id)
        if not project:
            return
        selected = series_service.select_items(project, item_ids)
        project["status"] = "outlining"
        series_service.save_project(project)
        # 精细角色图使用确定性的单页大纲，不需要初始化文本模型；只有故事模式才加载服务。
        service = None
        if any(series_service.normalize_content_mode(item.get("content_mode", "story")) == "story" for item in selected):
            service = get_outline_service()
        for item in selected:
            _generate_outline(project, item, service)
        if any(item.get("outline_status") == "ready" for item in project.get("items", [])):
            project["status"] = "outline_ready"
        elif any(item.get("outline_status") == "confirmed" for item in project.get("items", [])):
            project["status"] = "confirmed"
        else:
            project["status"] = "draft"
        series_service.save_project(project)
    except Exception as exc:
        logger.exception("系列后台大纲任务异常: project=%s", project_id)
        _settle_background_failure(project_id, item_ids, exc)
    finally:
        with _active_lock:
            _active_projects.discard(project_id)


def _start_outline_generation(project: Dict[str, Any], items: List[Dict[str, Any]]):
    if not items:
        raise ValueError("没有可生成大纲的子主题")
    project_id = project["id"]
    with _active_lock:
        if project_id in _active_projects:
            raise RuntimeError("该系列项目已有任务正在执行")
        _active_projects.add(project_id)
        for item in items:
            item.update({"status": "queued", "outline_status": "queued", "error": None})
        project["status"] = "outlining"
        series_service.save_project(project)
    thread = threading.Thread(
        target=_run_outline_generation,
        args=(project_id, [item["id"] for item in items]),
        name=f"series-outline-{project_id}",
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        with _active_lock:
            _active_projects.discard(project_id)
        raise
    return series_service.project_with_template(project)


def _start_generation(project: Dict[str, Any], items: List[Dict[str, Any]]):
    project_id = project["id"]
    with _active_lock:
        if project_id in _active_projects:
            raise RuntimeError("该系列项目已有生成任务正在执行")
        _active_projects.add(project_id)
        for item in items:
            item.update({"status": "queued", "error": None})
        project["status"] = "queued"
        series_service.save_project(project)
    thread = threading.Thread(
        target=_run_generation,
        args=(project_id, [item["id"] for item in items]),
        name=f"series-{project_id}",
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        with _active_lock:
            _active_projects.discard(project_id)
        raise
    return series_service.project_with_template(project)


def create_series_blueprint():
    recovered = series_service.recover_interrupted_projects(set(_active_projects))
    if recovered:
        logger.warning("已恢复 %s 个因服务重启中断的系列子任务", recovered)
    blueprint = Blueprint("series", __name__)

    @blueprint.get("/series/templates")
    def list_templates():
        return _ok(templates=series_service.list_templates())

    @blueprint.post("/series/templates")
    def create_template():
        try:
            return _ok(201, template=series_service.create_template(request.get_json(silent=True) or {}))
        except Exception as exc:
            return _error(str(exc))

    @blueprint.get("/series/templates/<template_id>")
    def get_template(template_id: str):
        template = series_service.get_template(template_id)
        return _ok(template=template) if template else _error("系列模板不存在", 404)

    @blueprint.put("/series/templates/<template_id>")
    def update_template(template_id: str):
        try:
            template = series_service.update_template(template_id, request.get_json(silent=True) or {})
            return _ok(template=template) if template else _error("系列模板不存在", 404)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.delete("/series/templates/<template_id>")
    def delete_template(template_id: str):
        try:
            return _ok(message="系列模板已删除") if series_service.delete_template(template_id) else _error("系列模板不存在", 404)
        except Exception as exc:
            return _error(str(exc), 409)

    @blueprint.post("/series/templates/<template_id>/references")
    def upload_references(template_id: str):
        try:
            uploads = []
            for file in request.files.getlist("images"):
                if file and file.filename:
                    uploads.append((file.filename, file.read(series_service.MAX_REFERENCE_BYTES + 1)))
            return _ok(template=series_service.add_reference_images(template_id, uploads))
        except KeyError as exc:
            return _error(str(exc), 404)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.get("/series/templates/<template_id>/references/<filename>")
    def get_reference(template_id: str, filename: str):
        try:
            return send_file(series_service.reference_path(template_id, filename))
        except (ValueError, FileNotFoundError):
            return _error("参考图不存在", 404)

    @blueprint.get("/series/projects")
    def list_projects():
        return _ok(projects=series_service.list_projects())

    @blueprint.post("/series/projects")
    def create_project():
        payload = request.get_json(silent=True) or {}
        try:
            project = series_service.create_project(
                payload.get("template_id", ""),
                payload.get("topics", []),
                payload.get("topic_source", "user"),
                payload.get("name", ""),
                payload.get("allow_third_party_ip", False),
                payload.get("content_mode", "story"),
            )
            return _ok(201, project=project)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.get("/series/projects/<project_id>")
    def get_project(project_id: str):
        project, error = _project_or_error(project_id)
        return error or _ok(project=series_service.project_with_template(project))

    @blueprint.put("/series/projects/<project_id>")
    def update_project(project_id: str):
        project, error = _project_or_error(project_id)
        if error:
            return error
        payload = request.get_json(silent=True) or {}
        try:
            if "name" in payload:
                name = " ".join(str(payload.get("name") or "").split())
                if not name or len(name) > 100:
                    raise ValueError("合集名称必须为 1-100 个字符")
                project["name"] = name
            return _ok(project=series_service.save_project(project))
        except Exception as exc:
            return _error(str(exc))

    @blueprint.get("/series/projects/<project_id>/items")
    def get_items(project_id: str):
        try:
            result = series_service.list_project_items(
                project_id,
                page=request.args.get("page", 1),
                page_size=request.args.get("page_size", 20),
                query=request.args.get("q", ""),
                status=request.args.get("status", ""),
            )
            # 同时保留 pagination 对象与扁平字段，兼容现有工作台读取方式。
            pagination = result.get("pagination") or {}
            return _ok(
                **result,
                page=pagination.get("page", 1),
                page_size=pagination.get("page_size", 20),
                total=pagination.get("total", 0),
                total_pages=pagination.get("total_pages", 0),
            )
        except KeyError as exc:
            return _error(str(exc), 404)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.post("/series/projects/<project_id>/items")
    def append_items(project_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            with _active_lock:
                active_error = _active_project_error(project_id)
                if active_error:
                    return active_error
                result = series_service.append_project_items(
                    project_id,
                    payload.get("topics"),
                    payload.get("topic_source", "user"),
                    payload.get("ip_acknowledged", False),
                    payload.get("content_mode", "story"),
                )
            return _ok(201, **result)
        except KeyError as exc:
            return _error(str(exc), 404)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.post("/series/projects/<project_id>/topic-suggestions")
    def suggest_topics(project_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            allow_ip = payload.get("allow_third_party_ip", False)
            if not isinstance(allow_ip, bool):
                raise ValueError("allow_third_party_ip 必须是布尔值")
            project = series_service.get_project(project_id)
            if not project:
                raise KeyError("系列项目不存在")
            template = series_service.get_template(project["template_id"])
            if not template:
                raise ValueError("系列模板不存在")
            try:
                generated = get_content_service().generate_series_topic_suggestions(
                    series_service.build_context(template)["series_context"] + f"\n当前合集名称：{project.get('name', '')}",
                    [item.get("topic", "") for item in project.get("items", [])],
                    allow_ip,
                )
                suggestions = [{
                    **item,
                    "title": item["topic"],
                    "brief": item.get("reason", ""),
                    "ip_related": bool(item.get("uses_ip", False)),
                } for item in generated]
                source = "model"
                warning = None
            except Exception as exc:
                logger.warning("系列主题模型推荐失败，使用本地候选: project=%s error=%s", project_id, exc)
                suggestions = series_service.topic_suggestions(project_id, allow_ip)
                source = "fallback"
                warning = "模型推荐暂时不可用，已提供本地候选，可编辑后再加入合集。"
            return _ok(
                suggestions=suggestions,
                allow_third_party_ip=allow_ip,
                source=source,
                warning=warning,
            )
        except KeyError as exc:
            return _error(str(exc), 404)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.put("/series/projects/<project_id>/items/<item_id>")
    def update_item(project_id: str, item_id: str):
        try:
            with _active_lock:
                active_error = _active_project_error(project_id)
                if active_error:
                    return active_error
                project, error = _project_or_error(project_id)
                if error:
                    return error
                saved = series_service.update_item(project, item_id, request.get_json(silent=True) or {})
            return _ok(project=saved, item=series_service.get_project_item(saved, item_id))
        except KeyError as exc:
            return _error(str(exc), 404)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.delete("/series/projects/<project_id>/items/<item_id>")
    def delete_item(project_id: str, item_id: str):
        try:
            with _active_lock:
                active_error = _active_project_error(project_id)
                if active_error:
                    return active_error
                removed = series_service.delete_project_item(project_id, item_id)
                project = series_service.get_project(project_id)
            return _ok(
                project=series_service.project_with_template(project),
                deleted_item=removed,
                message="子主题已从合集移除；对应历史成品仍保留。",
            )
        except KeyError as exc:
            return _error(str(exc), 404)
        except Exception as exc:
            return _error(str(exc), 409 if "正在生成" in str(exc) else 400)

    @blueprint.post("/series/projects/<project_id>/items/<item_id>/outline")
    def item_outline(project_id: str, item_id: str):
        try:
            with _active_lock:
                active_error = _active_project_error(project_id)
                if active_error:
                    return active_error
                project, error = _project_or_error(project_id)
                if error:
                    return error
                item, error = _item_or_error(project, item_id)
                if error:
                    return error
                if item.get("status") in {"completed", "queued", "outlining", "generating"}:
                    return _error("子主题当前状态不能重新生成大纲")
                queued = _start_outline_generation(project, [item])
            return _ok(202, project=queued, item=series_service.get_project_item(queued, item_id), message="大纲生成已开始")
        except RuntimeError as exc:
            return _error(str(exc), 409)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.post("/series/projects/<project_id>/items/<item_id>/confirm")
    def item_confirm(project_id: str, item_id: str):
        payload = request.get_json(silent=True) or {}
        if payload.get("confirm", True) is not True:
            return _error("confirm 必须为 true")
        with _active_lock:
            active_error = _active_project_error(project_id)
            if active_error:
                return active_error
            project, error = _project_or_error(project_id)
            if error:
                return error
            item, error = _item_or_error(project, item_id)
            if error:
                return error
            failure = _confirm_item(project, item)
            saved = series_service.get_project(project_id)
        return _ok(project=series_service.project_with_template(saved), item=series_service.get_project_item(saved, item_id), failures=[] if not failure else [{"item_id": item_id, "error": failure}])

    @blueprint.post("/series/projects/<project_id>/items/<item_id>/generate")
    def item_generate(project_id: str, item_id: str):
        try:
            with _active_lock:
                active_error = _active_project_error(project_id)
                if active_error:
                    return active_error
                project, error = _project_or_error(project_id)
                if error:
                    return error
                item, error = _item_or_error(project, item_id)
                if error:
                    return error
                if item.get("outline_status") != "confirmed":
                    return _error("请先确认该子主题大纲")
                queued = _start_generation(project, [item])
            return _ok(202, project=queued, item=item, message="子作品生成已开始")
        except RuntimeError as exc:
            return _error(str(exc), 409)

    @blueprint.post("/series/projects/<project_id>/items/<item_id>/retry-failed")
    def item_retry_failed(project_id: str, item_id: str):
        try:
            with _active_lock:
                active_error = _active_project_error(project_id)
                if active_error:
                    return active_error
                project, error = _project_or_error(project_id)
                if error:
                    return error
                item, error = _item_or_error(project, item_id)
                if error:
                    return error
                if not item.get("record_id"):
                    return _error("该子主题还没有历史成品，无法补全图片")
                record = get_history_service().get_record(item["record_id"])
                if not record or not (record.get("images") or {}).get("task_id"):
                    return _error("该子主题还没有图片任务，当前失败发生在文案或大纲阶段，请先修复后重新生成")
                if item.get("status") in {"queued", "outlining", "generating", "running", "processing"}:
                    return _error("该子主题已有图片任务正在执行，请等待完成", 409)
                _active_projects.add(project_id)
                item.update({"status": "generating", "image_status": "generating", "error": None})
                project["status"] = "generating"
                series_service.save_project(project)
            thread = threading.Thread(
                target=_run_retry_failed_item,
                args=(project_id, item_id),
                name=f"series-retry-{project_id}-{item_id}",
                daemon=True,
            )
            try:
                thread.start()
            except Exception:
                with _active_lock:
                    _active_projects.discard(project_id)
                raise
            queued = series_service.get_project(project_id)
            return _ok(202, project=series_service.project_with_template(queued), item=series_service.get_project_item(queued, item_id), message="失败图片补全已开始")
        except RuntimeError as exc:
            return _error(str(exc), 409)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.post("/series/projects/<project_id>/outlines")
    def bulk_outlines(project_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            with _active_lock:
                active_error = _active_project_error(project_id)
                if active_error:
                    return active_error
                project, error = _project_or_error(project_id)
                if error:
                    return error
                items = series_service.select_items(project, payload.get("item_ids"), eligible_statuses={"draft", "failed", "outline_ready"})
                queued = _start_outline_generation(project, items)
            return _ok(202, project=queued, items=items, message="批量大纲生成已开始")
        except KeyError as exc:
            return _error(str(exc), 404)
        except RuntimeError as exc:
            return _error(str(exc), 409)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.post("/series/projects/<project_id>/confirm")
    def bulk_confirm(project_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            with _active_lock:
                active_error = _active_project_error(project_id)
                if active_error:
                    return active_error
                project, error = _project_or_error(project_id)
                if error:
                    return error
                # 兼容旧审核页直接提交编辑后的 items。
                updates = {row.get("id"): row for row in payload.get("items", []) if isinstance(row, dict)}
                for item_id, update in updates.items():
                    series_service.update_item(project, item_id, update)
                    project = series_service.get_project(project_id)
                if "item_ids" in payload:
                    item_ids = payload["item_ids"]
                elif updates:
                    item_ids = list(updates)
                else:
                    item_ids = None
                items = series_service.select_items(project, item_ids, eligible_statuses={"outline_ready", "confirmed"})
                failures = []
                for item in items:
                    failure = _confirm_item(project, item)
                    if failure:
                        failures.append({"item_id": item["id"], "error": failure})
                project["status"] = "confirmed" if any(item.get("outline_status") == "confirmed" for item in project["items"]) else "outline_ready"
                saved = series_service.save_project(project)
            return _ok(project=saved, items=items, failures=failures)
        except KeyError as exc:
            return _error(str(exc), 404)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.post("/series/projects/<project_id>/generate")
    def bulk_generate(project_id: str):
        payload = request.get_json(silent=True) or {}
        try:
            with _active_lock:
                active_error = _active_project_error(project_id)
                if active_error:
                    return active_error
                project, error = _project_or_error(project_id)
                if error:
                    return error
                items = series_service.select_items(project, payload.get("item_ids"), eligible_statuses={"confirmed", "failed"})
                if not items:
                    return _error("没有可生成的已确认子主题")
                not_confirmed = [item["id"] for item in items if item.get("outline_status") != "confirmed"]
                if not_confirmed:
                    return _error(f"子主题尚未确认：{not_confirmed[0]}")
                queued = _start_generation(project, items)
            return _ok(202, project=queued, items=items, message="系列批量生成已开始")
        except KeyError as exc:
            return _error(str(exc), 404)
        except RuntimeError as exc:
            return _error(str(exc), 409)
        except Exception as exc:
            return _error(str(exc))

    @blueprint.get("/series/projects/<project_id>/tasks")
    def get_tasks(project_id: str):
        project, error = _project_or_error(project_id)
        if error:
            return error
        tasks = [{
            "id": item["id"],
            "record_id": item.get("record_id"),
            "status": item.get("status"),
            "outline_status": item.get("outline_status"),
            "content_status": item.get("content_status"),
            "image_status": item.get("image_status"),
            "progress": item.get("progress"),
            "error": item.get("error"),
        } for item in project.get("items", [])]
        return _ok(project=series_service.project_with_template(project), tasks=tasks)

    return blueprint


__all__ = ["create_series_blueprint"]
