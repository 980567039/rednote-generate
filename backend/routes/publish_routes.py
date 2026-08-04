"""本地小红书发布配置、登录与任务 API。"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.errors import AppError
from backend.services.publish import PublishServiceError, get_publish_service
from .utils import api_error_response, validation_error


def _publish_error(error: PublishServiceError, context: dict | None = None):
    return api_error_response(error.app_error, context=context)


def create_publish_blueprint(publish_service=None):
    """创建发布路由蓝图；测试可显式注入隔离的 service。"""
    publish_bp = Blueprint("publish", __name__)
    service = publish_service or get_publish_service()

    @publish_bp.route("/publish/config", methods=["GET"])
    def get_publish_config():
        try:
            return jsonify({"success": True, "config": service.get_config()})
        except Exception as exc:
            return api_error_response(exc, context={"endpoint": "/api/publish/config"})

    @publish_bp.route("/publish/config", methods=["PUT"])
    def put_publish_config():
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return api_error_response(validation_error("请求体必须是 JSON 对象。", "请提交发布配置。"))
            config = service.update_config(data)
            return jsonify({"success": True, "config": config, "message": "发布配置已保存"})
        except PublishServiceError as exc:
            return _publish_error(exc, {"endpoint": "/api/publish/config"})
        except Exception as exc:
            return api_error_response(exc, context={"endpoint": "/api/publish/config"})

    @publish_bp.route("/publish/auth/check", methods=["POST"])
    def check_publish_auth():
        try:
            result = dict(service.auth_check())
            status = int(result.pop("status", 200 if result.get("success") else 502))
            return jsonify(result), status
        except Exception as exc:
            return api_error_response(exc, context={"endpoint": "/api/publish/auth/check"})

    @publish_bp.route("/publish/auth/login", methods=["POST"])
    def start_publish_login():
        try:
            result = dict(service.auth_login())
            status = int(result.pop("status", 200 if result.get("success") else 502))
            return jsonify(result), status
        except Exception as exc:
            return api_error_response(exc, context={"endpoint": "/api/publish/auth/login"})

    @publish_bp.route("/history/<record_id>/publish", methods=["POST"])
    def create_publish_task(record_id: str):
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return api_error_response(validation_error("请求体必须是 JSON 对象。", "请填写发布内容后重试。"))
            task = service.create_publish_task(
                record_id,
                title=data.get("title"),
                copywriting=data.get("copywriting"),
                tags=data.get("tags"),
                mode=data.get("mode"),
                confirm=data.get("confirm"),
            )
            return jsonify({"success": True, "task": task}), 202
        except PublishServiceError as exc:
            return _publish_error(exc, {"endpoint": "/api/history/<record_id>/publish", "record_id": record_id})
        except Exception as exc:
            return api_error_response(exc, context={"endpoint": "/api/history/<record_id>/publish", "record_id": record_id})

    @publish_bp.route("/publish/tasks/<task_id>", methods=["GET"])
    def get_publish_task(task_id: str):
        try:
            task = service.get_task(task_id)
            if not task:
                return api_error_response(
                    AppError(
                        code="NOT_FOUND",
                        title="发布任务不存在",
                        detail=f"找不到发布任务：{task_id}。",
                        suggestion="请返回成品页重新发起发布。",
                        status=404,
                    ),
                    context={"endpoint": "/api/publish/tasks/<task_id>", "task_id": task_id},
                )
            return jsonify({"success": True, "task": task})
        except Exception as exc:
            return api_error_response(exc, context={"endpoint": "/api/publish/tasks/<task_id>", "task_id": task_id})

    @publish_bp.route("/publish/tasks/<task_id>/confirm", methods=["POST"])
    def confirm_publish_task(task_id: str):
        try:
            data = request.get_json(silent=True)
            # 确认按钮是明确的用户操作；为兼容旧前端，空请求体也视为确认，
            # 但创建发布任务仍然必须显式传 confirm=true。
            if data is None:
                data = {}
            if not isinstance(data, dict):
                return api_error_response(validation_error("请求体必须是 JSON 对象。", "请确认后再发布。"))
            task = service.confirm_task(task_id, confirm=data.get("confirm", True))
            return jsonify({"success": True, "task": task}), 202
        except PublishServiceError as exc:
            return _publish_error(exc, {"endpoint": "/api/publish/tasks/<task_id>/confirm", "task_id": task_id})
        except Exception as exc:
            return api_error_response(exc, context={"endpoint": "/api/publish/tasks/<task_id>/confirm", "task_id": task_id})

    @publish_bp.route("/publish/tasks/<task_id>/cancel", methods=["POST"])
    def cancel_publish_task(task_id: str):
        try:
            task = service.cancel_task(task_id)
            return jsonify({"success": True, "task": task, "message": "发布任务已停止"})
        except PublishServiceError as exc:
            return _publish_error(exc, {"endpoint": "/api/publish/tasks/<task_id>/cancel", "task_id": task_id})
        except Exception as exc:
            return api_error_response(exc, context={"endpoint": "/api/publish/tasks/<task_id>/cancel", "task_id": task_id})

    return publish_bp


__all__ = ["create_publish_blueprint"]
