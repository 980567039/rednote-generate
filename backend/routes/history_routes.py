"""
历史记录相关 API 路由

包含功能：
- 创建/获取/更新/删除历史记录 (CRUD)
- 搜索历史记录
- 获取统计信息
- 扫描和同步任务图片
- 打包下载图片
"""

import os
import io
import zipfile
import logging
import re
from flask import Blueprint, request, jsonify, send_file
from backend.services.history import ContentStatus, get_history_service
from .utils import api_error_response, normalize_error_result, validation_error

logger = logging.getLogger(__name__)


def _validate_content_payload(content):
    """校验历史记录中的成品文案字段，返回可读的错误详情或 None。"""
    if not isinstance(content, dict):
        return "content 必须是对象"

    if "titles" in content:
        titles = content["titles"]
        if not isinstance(titles, list) or any(not isinstance(item, str) for item in titles):
            return "content.titles 必须是字符串列表"

    if "copywriting" in content and not isinstance(content["copywriting"], str):
        return "content.copywriting 必须是字符串"

    if "tags" in content:
        tags = content["tags"]
        if not isinstance(tags, list) or any(not isinstance(item, str) for item in tags):
            return "content.tags 必须是字符串列表"

    if "status" in content and content["status"] not in ContentStatus.VALUES:
        return "content.status 必须是 idle、generating、done 或 error"

    if "error" in content and content["error"] is not None and not isinstance(content["error"], str):
        return "content.error 必须是字符串"

    return None


def create_history_blueprint():
    """创建历史记录路由蓝图（工厂函数，支持多次调用）"""
    history_bp = Blueprint('history', __name__)

    # ==================== CRUD 操作 ====================

    @history_bp.route('/history', methods=['POST'])
    def create_history():
        """
        创建历史记录（草稿）

        在用户生成大纲后立即调用，创建一个草稿状态的历史记录。
        初始状态为 draft，表示大纲已创建但尚未开始生成图片。

        请求体：
        - topic: 主题标题（必填）
        - outline: 大纲内容（必填），包含 pages 数组等
        - task_id: 关联的任务 ID（可选）

        返回：
        - success: 是否成功
        - record_id: 新创建的记录 ID（UUID 格式）

        状态流转：
            新建 -> draft（草稿状态）

        示例请求：
        {
            "topic": "小猫的冒险",
            "outline": {
                "title": "小猫的冒险",
                "pages": [
                    {"page": 1, "content": "..."},
                    {"page": 2, "content": "..."}
                ]
            },
            "task_id": "abc123"
        }
        """
        try:
            data = request.get_json()
            topic = data.get('topic')
            outline = data.get('outline')
            task_id = data.get('task_id')
            series_id = data.get('series_id')
            series_template_id = data.get('series_template_id')
            series_item_index = data.get('series_item_index')
            series_item_title = data.get('series_item_title')

            if not topic or not outline:
                return api_error_response(
                    validation_error("topic 和 outline 不能为空", "请提供主题和大纲内容。"),
                    context={"endpoint": "/api/history"},
                )

            history_service = get_history_service()
            record_id = history_service.create_record(
                topic, outline, task_id,
                series_id=series_id,
                series_project_id=data.get('series_project_id'),
                series_template_id=series_template_id,
                series_item_index=series_item_index,
                series_item_title=series_item_title,
                series_item_id=data.get('series_item_id'),
                series_topic_source=data.get('series_topic_source'),
                series_content_mode=data.get('content_mode') or data.get('series_content_mode'),
            )

            return jsonify({
                "success": True,
                "record_id": record_id
            }), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history"})

    @history_bp.route('/history', methods=['GET'])
    def list_history():
        """
        获取历史记录列表（分页）

        查询参数：
        - page: 页码（默认 1）
        - page_size: 每页数量（默认 20）
        - status: 状态过滤（可选：all/completed/draft）

        返回：
        - success: 是否成功
        - records: 记录列表
        - total: 总数
        - total_pages: 总页数
        """
        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 20))
            status = request.args.get('status')

            history_service = get_history_service()
            result = history_service.list_records(page, page_size, status)

            return jsonify({
                "success": True,
                **result
            }), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history"})

    @history_bp.route('/history/<record_id>', methods=['GET'])
    def get_history(record_id):
        """
        获取历史记录详情

        路径参数：
        - record_id: 记录 ID

        返回：
        - success: 是否成功
        - record: 完整的记录数据
        """
        try:
            history_service = get_history_service()
            record = history_service.get_record(record_id, sync_images=True)

            if not record:
                return api_error_response(
                    f"历史记录不存在：{record_id}",
                    status=404,
                    context={"endpoint": "/api/history/<id>", "record_id": record_id},
                )

            return jsonify({
                "success": True,
                "record": record
            }), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history/<id>", "record_id": record_id})

    @history_bp.route('/history/<record_id>/exists', methods=['GET'])
    def check_history_exists(record_id):
        """
        检查历史记录是否存在

        用于前端在开始生成前检查草稿记录是否已创建。

        路径参数：
        - record_id: 记录 ID

        返回：
        - exists: 记录是否存在（boolean）
        """
        try:
            history_service = get_history_service()
            exists = history_service.record_exists(record_id)

            return jsonify({
                "exists": exists
            }), 200

        except Exception as e:
            payload, status_code = api_error_response(e, context={"endpoint": "/api/history/<id>/exists", "record_id": record_id})
            payload_json = payload.get_json()
            payload_json["exists"] = False
            return jsonify(payload_json), status_code

    @history_bp.route('/history/<record_id>', methods=['PUT'])
    def update_history(record_id):
        """
        更新历史记录

        支持部分更新，只更新提供的字段。
        每次更新都会自动刷新 updated_at 时间戳。

        路径参数：
        - record_id: 记录 ID

        请求体（均为可选）：
        - outline: 大纲内容（支持修改大纲）
        - images: 图片信息 { task_id, generated: [] }
        - content: 成品文案 { titles: [], copywriting: "", tags: [], status: "done" }
        - status: 状态（draft/generating/partial/completed/error）
        - thumbnail: 缩略图文件名

        返回：
        - success: 是否成功

        状态流转说明：
            draft -> generating: 开始生成图片
            generating -> partial: 部分图片生成完成
            generating -> completed: 所有图片生成完成
            generating -> error: 生成过程出错
            partial -> generating: 继续生成剩余图片
            partial -> completed: 剩余图片生成完成

        示例请求（更新状态为生成中）：
        {
            "status": "generating"
        }

        示例请求（更新图片列表）：
        {
            "images": {
                "task_id": "abc123",
                "generated": ["0.png", "1.png"]
            },
            "status": "partial",
            "thumbnail": "0.png"
        }
        """
        try:
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return api_error_response(
                    validation_error("请求体必须是 JSON 对象", "请检查提交的数据格式。"),
                    context={"endpoint": "/api/history/<id>", "record_id": record_id},
                )
            outline = data.get('outline')
            images = data.get('images')
            content = data.get('content')
            status = data.get('status')
            thumbnail = data.get('thumbnail')

            if 'content' in data:
                content_error = _validate_content_payload(content)
                if content_error:
                    return api_error_response(
                        validation_error(content_error, "请按 titles、copywriting、tags 和 status 的类型提交。"),
                        context={"endpoint": "/api/history/<id>", "record_id": record_id},
                    )

            history_service = get_history_service()
            success = history_service.update_record(
                record_id,
                outline=outline,
                images=images,
                content=content,
                status=status,
                thumbnail=thumbnail
            )

            if not success:
                return api_error_response(
                    f"更新历史记录失败：{record_id}",
                    status=404,
                    context={"endpoint": "/api/history/<id>", "record_id": record_id},
                )

            return jsonify({
                "success": True
            }), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history/<id>", "record_id": record_id})

    @history_bp.route('/history/<record_id>/pattern-pages', methods=['POST'])
    def append_pattern_page(record_id):
        """接收 Perler 母版；只有调用方明确确认后才会写入历史。"""
        try:
            request_id = (request.form.get('request_id') or '').strip()
            if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', request_id):
                return api_error_response(
                    validation_error("request_id 无效", "请重新发起拼豆图纸交接。"),
                    context={"endpoint": "/api/history/<id>/pattern-pages", "record_id": record_id},
                )

            pattern_file = request.files.get('pattern')
            if not pattern_file or not pattern_file.filename:
                return api_error_response(
                    validation_error("缺少 pattern 文件", "请先从 Perler 回传 PNG 母版。"),
                    context={"endpoint": "/api/history/<id>/pattern-pages", "record_id": record_id},
                )
            image_data = pattern_file.read(20 * 1024 * 1024 + 1)
            if len(image_data) > 20 * 1024 * 1024:
                return api_error_response(
                    validation_error("拼豆图纸文件超过 20MB", "请缩小母版后再试。"),
                    context={"endpoint": "/api/history/<id>/pattern-pages", "record_id": record_id},
                )

            def read_optional_file(field_name, label, max_bytes):
                upload = request.files.get(field_name)
                if not upload or not upload.filename:
                    return None
                data = upload.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ValueError(f"{label}文件超过 {max_bytes // (1024 * 1024)}MB")
                return data

            beads_data = read_optional_file('beads', '拼豆实物效果图', 10 * 1024 * 1024)
            ironed_data = read_optional_file('ironed', '熨烫成品效果图', 10 * 1024 * 1024)

            def form_int(name, default):
                raw = request.form.get(name)
                return default if raw in (None, '') else int(raw)

            result = get_history_service().append_pattern_image(
                record_id=record_id,
                request_id=request_id,
                image_data=image_data,
                source_image_index=form_int('source_image_index', 0),
                columns=form_int('columns', 104),
                rows=form_int('rows', 104),
                used_colors=form_int('used_colors', 40),
                beads_data=beads_data,
                ironed_data=ironed_data,
            )
            response_payload = {
                "success": True,
                "appended": result["appended"],
                "page_index": result["page_index"],
                "filename": result["filename"],
                "record": result["record"],
            }
            if result.get("outputs"):
                response_payload["outputs"] = result["outputs"]
            return jsonify(response_payload), 200
        except (TypeError, ValueError) as exc:
            return api_error_response(
                validation_error(str(exc), "拼豆图纸参数或文件无效。"),
                context={"endpoint": "/api/history/<id>/pattern-pages", "record_id": record_id},
            )
        except FileNotFoundError as exc:
            return api_error_response(str(exc), status=404, context={"endpoint": "/api/history/<id>/pattern-pages", "record_id": record_id})
        except Exception as exc:
            return api_error_response(exc, context={"endpoint": "/api/history/<id>/pattern-pages", "record_id": record_id})

    @history_bp.route('/history/<record_id>', methods=['DELETE'])
    def delete_history(record_id):
        """
        删除历史记录

        路径参数：
        - record_id: 记录 ID

        返回：
        - success: 是否成功
        """
        try:
            history_service = get_history_service()
            success = history_service.delete_record(record_id)

            if not success:
                return api_error_response(
                    f"删除历史记录失败：{record_id}",
                    status=404,
                    context={"endpoint": "/api/history/<id>", "record_id": record_id},
                )

            return jsonify({
                "success": True
            }), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history/<id>", "record_id": record_id})

    # ==================== 搜索和统计 ====================

    @history_bp.route('/history/search', methods=['GET'])
    def search_history():
        """
        搜索历史记录

        查询参数：
        - keyword: 搜索关键词（必填）

        返回：
        - success: 是否成功
        - records: 匹配的记录列表
        """
        try:
            keyword = request.args.get('keyword', '')

            if not keyword:
                return api_error_response(
                    validation_error("keyword 不能为空", "请输入搜索关键词。"),
                    context={"endpoint": "/api/history/search"},
                )

            history_service = get_history_service()
            results = history_service.search_records(keyword)

            return jsonify({
                "success": True,
                "records": results
            }), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history/search"})

    @history_bp.route('/history/stats', methods=['GET'])
    def get_history_stats():
        """
        获取历史记录统计信息

        返回：
        - success: 是否成功
        - total: 总记录数
        - by_status: 按状态分组的统计
        """
        try:
            history_service = get_history_service()
            stats = history_service.get_statistics()

            return jsonify({
                "success": True,
                **stats
            }), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history/stats"})

    # ==================== 扫描和同步 ====================

    @history_bp.route('/history/scan/<task_id>', methods=['GET'])
    def scan_task(task_id):
        """
        扫描单个任务并同步图片列表

        路径参数：
        - task_id: 任务 ID

        返回：
        - success: 是否成功
        - images: 同步后的图片列表
        """
        try:
            history_service = get_history_service()
            result = history_service.scan_and_sync_task_images(task_id)

            if not result.get("success"):
                result = normalize_error_result(
                    result,
                    context={"endpoint": "/api/history/scan/<task_id>", "task_id": task_id},
                    fallback_status=404,
                )
                return jsonify(result), result["error"].get("status", 404)

            return jsonify(result), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history/scan/<task_id>", "task_id": task_id})

    @history_bp.route('/history/scan-all', methods=['POST'])
    def scan_all_tasks():
        """
        扫描所有任务并同步图片列表

        返回：
        - success: 是否成功
        - total_tasks: 扫描的任务总数
        - synced: 成功同步的任务数
        - failed: 失败的任务数
        - orphan_tasks: 孤立任务列表（有图片但无记录）
        """
        try:
            history_service = get_history_service()
            result = history_service.scan_all_tasks()

            if not result.get("success"):
                result = normalize_error_result(
                    result,
                    context={"endpoint": "/api/history/scan-all"},
                    fallback_status=500,
                )
                return jsonify(result), result["error"].get("status", 500)

            return jsonify(result), 200

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history/scan-all"})

    # ==================== 下载功能 ====================

    @history_bp.route('/history/<record_id>/download', methods=['GET'])
    def download_history_zip(record_id):
        """
        下载历史记录的所有图片为 ZIP 文件

        路径参数：
        - record_id: 记录 ID

        返回：
        - 成功：ZIP 文件下载
        - 失败：JSON 错误信息
        """
        try:
            history_service = get_history_service()
            record = history_service.get_record(record_id)

            if not record:
                return api_error_response(
                    f"历史记录不存在：{record_id}",
                    status=404,
                    context={"endpoint": "/api/history/<id>/download", "record_id": record_id},
                )

            task_id = record.get('images', {}).get('task_id')
            if not task_id:
                return api_error_response(
                    "该记录没有关联的任务图片",
                    status=404,
                    context={"endpoint": "/api/history/<id>/download", "record_id": record_id},
                )

            # 获取任务目录
            task_dir = os.path.join(history_service.history_dir, task_id)
            if not os.path.exists(task_dir):
                return api_error_response(
                    f"任务目录不存在：{task_id}",
                    status=404,
                    context={"endpoint": "/api/history/<id>/download", "record_id": record_id, "task_id": task_id},
                )

            # 创建内存中的 ZIP 文件
            zip_buffer = _create_images_zip(task_dir)

            # 生成安全的下载文件名
            title = record.get('title', 'images')
            safe_title = _sanitize_filename(title)
            filename = f"{safe_title}.zip"

            return send_file(
                zip_buffer,
                mimetype='application/zip',
                as_attachment=True,
                download_name=filename
            )

        except Exception as e:
            return api_error_response(e, context={"endpoint": "/api/history/<id>/download", "record_id": record_id})

    return history_bp


def _create_images_zip(task_dir: str) -> io.BytesIO:
    """
    创建包含所有图片的 ZIP 文件

    Args:
        task_dir: 任务目录路径

    Returns:
        io.BytesIO: 内存中的 ZIP 文件
    """
    memory_file = io.BytesIO()

    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 遍历任务目录中的所有图片（排除缩略图）
        for filename in os.listdir(task_dir):
            # 跳过缩略图文件
            if filename.startswith('thumb_'):
                continue

            if filename.endswith(('.png', '.jpg', '.jpeg')):
                file_path = os.path.join(task_dir, filename)

                # 生成归档文件名（page_N.png 格式）
                try:
                    index = int(filename.split('.')[0])
                    archive_name = f"page_{index + 1}.png"
                except ValueError:
                    archive_name = filename

                zf.write(file_path, archive_name)

    # 将指针移到开始位置
    memory_file.seek(0)
    return memory_file


def _sanitize_filename(title: str) -> str:
    """
    清理文件名中的非法字符

    Args:
        title: 原始标题

    Returns:
        str: 安全的文件名
    """
    # 只保留字母、数字、空格、连字符和下划线
    safe_title = "".join(
        c for c in title
        if c.isalnum() or c in (' ', '-', '_', '\u4e00-\u9fff')
    ).strip()

    return safe_title if safe_title else 'images'
