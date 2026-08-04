"""
内容生成相关 API 路由

包含功能：
- 生成标题、文案、标签
"""

import time
import logging
from flask import Blueprint, request, jsonify
from backend.services.content import get_content_service
from backend.services.history import get_history_service
from backend.services.series import build_context, get_template, series_context_from_payload
from .utils import (
    api_error_response,
    log_request,
    log_error,
    normalize_error_result,
    validation_error,
)

logger = logging.getLogger(__name__)


def create_content_blueprint():
    """创建内容生成路由蓝图（工厂函数，支持多次调用）"""
    content_bp = Blueprint('content', __name__)

    @content_bp.route('/content', methods=['POST'])
    def generate_content():
        """
        生成标题、文案、标签

        请求格式（application/json）：
        - topic: 主题文本
        - outline: 大纲内容

        返回：
        - success: 是否成功
        - titles: 标题列表（3个备选）
        - copywriting: 文案正文
        - tags: 标签列表
        """
        start_time = time.time()

        try:
            data = request.get_json()
            topic = data.get('topic', '')
            outline = data.get('outline', '')
            series_template_id = data.get('series_template_id')
            series_item_index = data.get('series_item_index')
            series_item_title = data.get('series_item_title')
            series_kwargs = {
                "series_id": data.get("series_id"),
                "series_template_id": series_template_id,
                "series_item_index": series_item_index,
                "series_item_title": series_item_title,
                "content_mode": data.get("content_mode"),
            }
            record = get_history_service().get_record(data.get("record_id")) if data.get("record_id") else None
            snapshot = (record or {}).get("series_template_snapshot")
            if snapshot:
                series_kwargs.update({
                    "series_id": record.get("series_id"),
                    "series_project_id": record.get("series_project_id") or record.get("series_id"),
                    "series_item_id": record.get("series_item_id"),
                    "series_template_id": snapshot.get("id"),
                    "series_item_index": record.get("series_item_index"),
                    "series_item_title": record.get("series_item_title") or topic,
                    "content_mode": record.get("series_content_mode", snapshot.get("content_mode", "story")),
                    "series_context": record.get("series_context_snapshot") or build_context(snapshot, topic, record.get("series_item_index"), record.get("series_content_mode", snapshot.get("content_mode", "story")))["series_context"],
                    "series_template": snapshot,
                })
            elif data.get("series_project_id") and data.get("series_item_id"):
                series_kwargs.update(series_context_from_payload(data))
            else:
                template = get_template(series_template_id) if series_template_id else None
                if template:
                    series_kwargs.update(build_context(template, series_item_title or topic, series_item_index, data.get("content_mode", "story")))

            log_request('/content', {'topic': topic[:50] if topic else '', 'outline_length': len(outline)})

            # 验证必填参数
            if not topic:
                logger.warning("内容生成请求缺少 topic 参数")
                return api_error_response(
                    validation_error("topic 不能为空", "请输入主题内容。"),
                    context={"endpoint": "/api/content"},
                )

            if not outline:
                logger.warning("内容生成请求缺少 outline 参数")
                return api_error_response(
                    validation_error("outline 不能为空", "请先生成大纲。"),
                    context={"endpoint": "/api/content"},
                )

            # 调用内容生成服务
            logger.info(f"🔄 开始生成内容，主题: {topic[:50]}...")
            content_service = get_content_service()
            result = content_service.generate_content(topic, outline, **series_kwargs)

            # 记录结果
            elapsed = time.time() - start_time
            if result["success"]:
                logger.info(f"✅ 内容生成成功，耗时 {elapsed:.2f}s")
                return jsonify(result), 200
            else:
                logger.error(f"❌ 内容生成失败: {result.get('error', '未知错误')}")
                result = normalize_error_result(
                    result,
                    context={"endpoint": "/api/content"},
                    fallback_status=500,
                )
                return jsonify(result), result["error"].get("status", 500)

        except Exception as e:
            log_error('/content', e)
            return api_error_response(e, context={"endpoint": "/api/content"})

    return content_bp
