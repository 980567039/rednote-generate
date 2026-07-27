"""
图片生成相关 API 路由

包含功能：
- 批量生成图片（SSE 流式返回）
- 获取图片
- 重试/重新生成单张图片
- 批量重试失败图片
- 获取任务状态
"""

import os
import json
import base64
import logging
from flask import Blueprint, request, jsonify, Response, send_file
from backend.errors import ensure_app_error
from backend.services.image import ActiveGenerationError, get_image_service
from .utils import (
    api_error_response,
    log_request,
    log_error,
    normalize_error_result,
    validation_error,
)

logger = logging.getLogger(__name__)


def create_image_blueprint():
    """创建图片路由蓝图（工厂函数，支持多次调用）"""
    image_bp = Blueprint('image', __name__)

    # ==================== 图片生成 ====================

    @image_bp.route('/generate', methods=['POST'])
    def generate_images():
        """
        批量生成图片（SSE 流式返回）

        请求体：
        - pages: 页面列表（必填）
        - task_id: 任务 ID
        - full_outline: 完整大纲文本
        - user_topic: 用户原始输入主题
        - user_images: base64 编码的用户参考图片列表

        返回：
        SSE 事件流，包含以下事件类型：
        - image: 单张图片生成完成
        - error: 生成错误
        - complete: 全部完成
        """
        try:
            data = request.get_json() or {}
            pages = data.get('pages')
            task_id = data.get('task_id')
            record_id = data.get('record_id')
            force = bool(data.get('force', False))
            full_outline = data.get('full_outline', '')
            user_topic = data.get('user_topic', '')

            # 解析 base64 格式的用户参考图片
            user_images = _parse_base64_images(data.get('user_images', []))

            log_request('/generate', {
                'pages_count': len(pages) if pages else 0,
                'task_id': task_id,
                'record_id': record_id,
                'force': force,
                'user_topic': user_topic[:50] if user_topic else None,
                'user_images': user_images
            })

            if not pages:
                logger.warning("图片生成请求缺少 pages 参数")
                return api_error_response(
                    validation_error("pages 不能为空", "请提供要生成的页面列表数据。"),
                    context={"endpoint": "/api/generate", "record_id": record_id},
                )

            image_service = get_image_service()
            try:
                reservation = image_service.prepare_generation(
                    pages,
                    task_id=task_id,
                    record_id=record_id,
                    force=force,
                )
            except ActiveGenerationError as exc:
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "GENERATION_ALREADY_ACTIVE",
                        "title": "已有图片生成任务",
                        "detail": str(exc),
                        "suggestion": "请等待当前任务完成，或重新连接该任务查看进度。",
                        "status": 409,
                        "retryable": False,
                        "diagnostics": {"task_id": exc.task_id, "record_id": record_id},
                    },
                    "error_message": str(exc),
                    "existing_task_id": exc.task_id,
                    "task_state": exc.state,
                }), 409

            task_id = reservation["task_id"]
            logger.info(f"🖼️  已接受图片生成任务: {task_id}, 共 {len(pages)} 页")

            def generate():
                """SSE 事件生成器"""
                for event in image_service.generate_images(
                    pages, task_id, full_outline,
                    user_images=user_images if user_images else None,
                    user_topic=user_topic,
                    record_id=record_id,
                    force=force,
                    prepared=True,
                    cached=reservation["cached"],
                ):
                    event_type = event["event"]
                    event_data = _normalize_sse_error(
                        event_type,
                        event["data"],
                        {
                            "endpoint": "/api/generate",
                            "task_id": task_id,
                            "record_id": record_id,
                        },
                    )

                    # 格式化为 SSE 格式
                    yield f"event: {event_type}\n"
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                }
            )

        except Exception as e:
            log_error('/generate', e)
            return api_error_response(e, context={"endpoint": "/api/generate"})

    # ==================== 图片获取 ====================

    @image_bp.route('/images/<task_id>/<filename>', methods=['GET'])
    def get_image(task_id, filename):
        """
        获取图片文件

        路径参数：
        - task_id: 任务 ID
        - filename: 文件名

        查询参数：
        - thumbnail: 是否返回缩略图（默认 true）

        返回：
        - 成功：图片文件
        - 失败：JSON 错误信息
        """
        try:
            logger.debug(f"获取图片: {task_id}/{filename}")

            # 检查是否请求缩略图
            thumbnail = request.args.get('thumbnail', 'true').lower() == 'true'

            # 构建 history 目录路径
            history_root = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "history"
            )

            if thumbnail:
                # 尝试返回缩略图
                thumb_filename = f"thumb_{filename}"
                thumb_filepath = os.path.join(history_root, task_id, thumb_filename)

                if os.path.exists(thumb_filepath):
                    return send_file(thumb_filepath, mimetype='image/png')

            # 返回原图
            filepath = os.path.join(history_root, task_id, filename)

            if not os.path.exists(filepath):
                return api_error_response(
                    "图片不存在",
                    status=404,
                    context={"endpoint": "/api/images", "task_id": task_id, "filename": filename},
                )

            return send_file(filepath, mimetype='image/png')

        except Exception as e:
            log_error('/images', e)
            return api_error_response(e, context={"endpoint": "/api/images", "task_id": task_id, "filename": filename})

    # ==================== 重试和重新生成 ====================

    @image_bp.route('/retry', methods=['POST'])
    def retry_single_image():
        """
        重试生成单张失败的图片

        请求体：
        - task_id: 任务 ID（必填）
        - page: 页面信息（必填）
        - use_reference: 是否使用参考图（默认 true）

        返回：
        - success: 是否成功
        - image_url: 新图片 URL
        """
        try:
            data = request.get_json()
            task_id = data.get('task_id')
            page = data.get('page')
            use_reference = data.get('use_reference', True)
            record_id = data.get('record_id')

            log_request('/retry', {
                'task_id': task_id,
                'record_id': record_id,
                'page_index': page.get('index') if page else None
            })

            if not task_id or not page:
                logger.warning("重试请求缺少必要参数")
                return api_error_response(
                    validation_error("task_id 和 page 不能为空", "请提供任务 ID 和页面信息。"),
                    context={"endpoint": "/api/retry", "task_id": task_id, "record_id": record_id},
                )

            logger.info(f"🔄 重试生成图片: task={task_id}, page={page.get('index')}")
            image_service = get_image_service()
            result = image_service.retry_single_image(
                task_id,
                page,
                use_reference,
                record_id=record_id,
            )

            if result["success"]:
                logger.info(f"✅ 图片重试成功: {result.get('image_url')}")
            else:
                logger.error(f"❌ 图片重试失败: {result.get('error')}")
                result = normalize_error_result(
                    result,
                    context={"endpoint": "/api/retry", "task_id": task_id, "record_id": record_id},
                    fallback_status=500,
                )

            return jsonify(result), 200 if result["success"] else result["error"].get("status", 500)

        except Exception as e:
            log_error('/retry', e)
            return api_error_response(e, context={"endpoint": "/api/retry"})

    @image_bp.route('/retry-failed', methods=['POST'])
    def retry_failed_images():
        """
        批量重试失败的图片（SSE 流式返回）

        请求体：
        - task_id: 任务 ID（必填）
        - pages: 要重试的页面列表（必填）

        返回：
        SSE 事件流
        """
        try:
            data = request.get_json()
            task_id = data.get('task_id')
            pages = data.get('pages')
            record_id = data.get('record_id')

            log_request('/retry-failed', {
                'task_id': task_id,
                'record_id': record_id,
                'pages_count': len(pages) if pages else 0
            })

            if not task_id or not pages:
                logger.warning("批量重试请求缺少必要参数")
                return api_error_response(
                    validation_error("task_id 和 pages 不能为空", "请提供任务 ID 和要重试的页面列表。"),
                    context={"endpoint": "/api/retry-failed", "task_id": task_id, "record_id": record_id},
                )

            logger.info(f"🔄 批量重试失败图片: task={task_id}, 共 {len(pages)} 页")
            image_service = get_image_service()

            def generate():
                """SSE 事件生成器"""
                for event in image_service.retry_failed_images(task_id, pages, record_id=record_id):
                    event_type = event["event"]
                    event_data = _normalize_sse_error(
                        event_type,
                        event["data"],
                        {
                            "endpoint": "/api/retry-failed",
                            "task_id": task_id,
                            "record_id": record_id,
                        },
                    )

                    yield f"event: {event_type}\n"
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            return Response(
                generate(),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                }
            )

        except Exception as e:
            log_error('/retry-failed', e)
            return api_error_response(e, context={"endpoint": "/api/retry-failed"})

    @image_bp.route('/regenerate', methods=['POST'])
    def regenerate_image():
        """
        重新生成图片（即使成功的也可以重新生成）

        请求体：
        - task_id: 任务 ID（必填）
        - page: 页面信息（必填）
        - use_reference: 是否使用参考图（默认 true）
        - full_outline: 完整大纲文本（用于上下文）
        - user_topic: 用户原始输入主题
        - revision_request: 本次重绘的补充修改意见（可选）

        返回：
        - success: 是否成功
        - image_url: 新图片 URL
        """
        try:
            data = request.get_json()
            task_id = data.get('task_id')
            page = data.get('page')
            use_reference = data.get('use_reference', True)
            full_outline = data.get('full_outline', '')
            user_topic = data.get('user_topic', '')
            record_id = data.get('record_id')
            revision_request = data.get('revision_request', '')
            if not isinstance(revision_request, str):
                revision_request = ''
            revision_request = revision_request.strip()[:500]

            log_request('/regenerate', {
                'task_id': task_id,
                'record_id': record_id,
                'page_index': page.get('index') if page else None
            })

            if not task_id or not page:
                logger.warning("重新生成请求缺少必要参数")
                return api_error_response(
                    validation_error("task_id 和 page 不能为空", "请提供任务 ID 和页面信息。"),
                    context={"endpoint": "/api/regenerate", "task_id": task_id, "record_id": record_id},
                )

            logger.info(f"🔄 重新生成图片: task={task_id}, page={page.get('index')}")
            image_service = get_image_service()
            result = image_service.regenerate_image(
                task_id, page, use_reference,
                full_outline=full_outline,
                user_topic=user_topic,
                record_id=record_id,
                revision_request=revision_request
            )

            if result["success"]:
                logger.info(f"✅ 图片重新生成成功: {result.get('image_url')}")
            else:
                logger.error(f"❌ 图片重新生成失败: {result.get('error')}")
                result = normalize_error_result(
                    result,
                    context={"endpoint": "/api/regenerate", "task_id": task_id, "record_id": record_id},
                    fallback_status=500,
                )

            return jsonify(result), 200 if result["success"] else result["error"].get("status", 500)

        except Exception as e:
            log_error('/regenerate', e)
            return api_error_response(e, context={"endpoint": "/api/regenerate"})

    # ==================== 任务状态 ====================

    @image_bp.route('/task/<task_id>', methods=['GET'])
    def get_task_state(task_id):
        """
        获取任务状态

        路径参数：
        - task_id: 任务 ID

        返回：
        - success: 是否成功
        - state: 任务状态
          - generated: 已生成的图片
          - failed: 失败的图片
          - has_cover: 是否有封面图
        """
        try:
            image_service = get_image_service()
            state = image_service.get_task_state(task_id)

            if state is None:
                return api_error_response(
                    f"任务不存在：{task_id}",
                    status=404,
                    context={"endpoint": "/api/task", "task_id": task_id},
                )

            return jsonify({
                "success": True,
                "state": state
            }), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/task", "task_id": task_id})

    # ==================== 健康检查 ====================

    @image_bp.route('/health', methods=['GET'])
    def health_check():
        """
        健康检查接口

        返回：
        - success: 服务是否正常
        - message: 状态消息
        """
        return jsonify({
            "success": True,
            "message": "服务正常运行"
        }), 200

    return image_bp


# ==================== 辅助函数 ====================

def _parse_base64_images(images_base64: list) -> list:
    """
    解析 base64 编码的图片列表

    Args:
        images_base64: base64 编码的图片字符串列表

    Returns:
        list: 解码后的图片二进制数据列表
    """
    if not images_base64:
        return []

    images = []
    for img_b64 in images_base64:
        # 移除可能的 data URL 前缀（如 data:image/png;base64,）
        if ',' in img_b64:
            img_b64 = img_b64.split(',')[1]
        images.append(base64.b64decode(img_b64))

    return images


def _normalize_sse_error(event_type: str, data: dict, context: dict) -> dict:
    if event_type != "error":
        return data

    next_data = dict(data)
    if isinstance(next_data.get("error"), dict):
        return next_data

    app_error = ensure_app_error(
        next_data.get("error") or next_data.get("message") or "图片生成失败",
        context=context,
    )
    next_data["error"] = app_error.to_dict()
    next_data["message"] = app_error.to_message()
    next_data["retryable"] = bool(next_data.get("retryable", app_error.retryable))
    return next_data
