"""
历史记录服务

负责管理绘本生成历史记录的存储、查询、更新和删除。
支持草稿、生成中、完成等多种状态流转。
"""

import os
import json
import uuid
import logging
import tempfile
from threading import RLock
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
from enum import Enum

from backend.services.history_image_merger import HistoryImageMerger

logger = logging.getLogger(__name__)


class RecordStatus:
    """历史记录状态常量"""
    DRAFT = "draft"          # 草稿：已创建大纲，未开始生成
    GENERATING = "generating"  # 生成中：正在生成图片
    PARTIAL = "partial"       # 部分完成：有部分图片生成
    COMPLETED = "completed"   # 已完成：所有图片已生成
    ERROR = "error"          # 错误：生成过程中出现错误


class ContentStatus:
    """成品文案生成状态常量。"""

    IDLE = "idle"
    GENERATING = "generating"
    DONE = "done"
    ERROR = "error"
    VALUES = {IDLE, GENERATING, DONE, ERROR}


class HistoryService:
    def __init__(self):
        """
        初始化历史记录服务

        创建历史记录存储目录和索引文件
        """
        # 历史记录存储目录（项目根目录/history）
        self.history_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "history"
        )
        os.makedirs(self.history_dir, exist_ok=True)

        # 索引文件路径
        self.index_file = os.path.join(self.history_dir, "index.json")
        # 单个图片任务会以多个 worker 并发回写历史记录。用可重入锁把
        # 读-改-写收敛为一个临界区，避免后一张图片覆盖前一张的文件名。
        self._lock = RLock()
        self._init_index()
        self._recover_interrupted_generations()

    def _ensure_lock(self) -> RLock:
        """兼容测试及旧实例的延迟初始化。"""
        if not hasattr(self, "_lock"):
            self._lock = RLock()
        return self._lock

    @staticmethod
    def _atomic_write_json(path: str, data: Dict) -> None:
        """写入完整 JSON 后再原子替换，避免中途退出留下半个文件。"""
        directory = os.path.dirname(path)
        fd, temporary_path = tempfile.mkstemp(prefix=".app-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
        except Exception:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            raise

    def _init_index(self) -> None:
        """
        初始化索引文件

        如果索引文件不存在，则创建一个空索引
        """
        if not os.path.exists(self.index_file):
            self._atomic_write_json(self.index_file, {"records": []})

    def _load_index(self) -> Dict:
        """
        加载索引文件

        Returns:
            Dict: 索引数据，包含 records 列表
        """
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"records": []}

    def _save_index(self, index: Dict) -> None:
        """
        保存索引文件

        Args:
            index: 索引数据
        """
        self._atomic_write_json(self.index_file, index)

    def _get_record_path(self, record_id: str) -> str:
        """
        获取历史记录文件路径

        Args:
            record_id: 记录 ID

        Returns:
            str: 记录文件的完整路径
        """
        return os.path.join(self.history_dir, f"{record_id}.json")

    @staticmethod
    def _empty_content() -> Dict[str, Any]:
        """返回互不共享引用的安全成品文案默认值。"""
        return {
            "titles": [],
            "copywriting": "",
            "tags": [],
            "status": ContentStatus.IDLE,
        }

    @classmethod
    def _normalize_content(cls, content: Any) -> Dict[str, Any]:
        """兼容没有 content 或字段不完整的旧历史记录。"""
        if not isinstance(content, dict):
            return cls._empty_content()

        titles = content.get("titles", [])
        tags = content.get("tags", [])
        copywriting = content.get("copywriting", "")

        normalized = {
            "titles": (
                [item for item in titles if isinstance(item, str)]
                if isinstance(titles, list)
                else []
            ),
            "copywriting": copywriting if isinstance(copywriting, str) else "",
            "tags": (
                [item for item in tags if isinstance(item, str)]
                if isinstance(tags, list)
                else []
            ),
        }

        status = content.get("status")
        if status not in ContentStatus.VALUES:
            has_generated_content = bool(
                normalized["titles"]
                or normalized["copywriting"]
                or normalized["tags"]
            )
            status = ContentStatus.DONE if has_generated_content else ContentStatus.IDLE
        normalized["status"] = status

        error = content.get("error")
        if isinstance(error, str) and error:
            normalized["error"] = error

        return normalized

    def _recover_interrupted_generations(self) -> None:
        """服务重启后收敛遗留的 generating 记录，不自动重提上游请求。"""
        with self._ensure_lock():
            index = self._load_index()
            interrupted = [
                item.get("id") for item in index.get("records", [])
                if item.get("status") == RecordStatus.GENERATING and item.get("id")
            ]

            for record_id in interrupted:
                record = self.get_record(record_id)
                if not record:
                    continue
                task_id = record.get("images", {}).get("task_id")
                total_count = len(record.get("outline", {}).get("pages", []))
                generated = record.get("images", {}).get("generated", [])
                if task_id:
                    generated = HistoryImageMerger.merge_many(
                        generated,
                        HistoryImageMerger.files_by_index(self.history_dir, task_id),
                        total_count,
                    )

                recovered_status = (
                    HistoryImageMerger.compute_status(generated, total_count)
                    if HistoryImageMerger.has_images(generated)
                    else RecordStatus.ERROR
                )
                self.update_record(
                    record_id,
                    images={"task_id": task_id, "generated": generated},
                    status=recovered_status,
                    thumbnail=HistoryImageMerger.first_image(generated),
                )
                logger.warning(
                    "服务重启后已收敛未完成图片任务: record=%s task=%s status=%s",
                    record_id,
                    task_id,
                    recovered_status,
                )

    def create_record(
        self,
        topic: str,
        outline: Dict,
        task_id: Optional[str] = None,
        series_id: Optional[str] = None,
        series_project_id: Optional[str] = None,
        series_template_id: Optional[str] = None,
        series_item_index: Optional[int] = None,
        series_item_title: Optional[str] = None,
        series_item_id: Optional[str] = None,
        series_template_revision: Optional[int] = None,
        series_template_snapshot: Optional[Dict[str, Any]] = None,
        series_context_snapshot: Optional[str] = None,
        series_topic_source: Optional[str] = None,
        series_content_mode: Optional[str] = None,
    ) -> str:
        """
        创建新的历史记录

        初始状态为 draft（草稿），表示大纲已创建但尚未开始生成图片。

        Args:
            topic: 绘本主题/标题
            outline: 大纲内容，包含 pages 数组等信息
            task_id: 关联的生成任务 ID（可选）

        Returns:
            str: 新创建的记录 ID（UUID 格式）

        状态流转：
            新建 -> draft（草稿状态）
        """
        with self._ensure_lock():
            # 生成唯一记录 ID
            record_id = str(uuid.uuid4())
            now = datetime.now().isoformat()

            # 创建完整的记录对象
            record = {
                "id": record_id,
                "title": topic,
                "created_at": now,
                "updated_at": now,
                "outline": outline,  # 保存完整的大纲数据
                "images": {
                    "task_id": task_id,
                    "generated": []  # 初始无生成图片
                },
                "content": self._empty_content(),
                "status": RecordStatus.DRAFT,  # 初始状态：草稿
                "thumbnail": None  # 初始无缩略图
            }
            # 系列元数据是可选的；旧历史记录和自由创作不需要迁移。
            if series_id is not None:
                record["series_id"] = series_id
            if series_project_id is not None:
                record["series_project_id"] = series_project_id
            if series_template_id is not None:
                record["series_template_id"] = series_template_id
            if series_item_index is not None:
                record["series_item_index"] = series_item_index
            if series_item_title is not None:
                record["series_item_title"] = series_item_title
            if series_item_id is not None:
                record["series_item_id"] = series_item_id
            if series_template_revision is not None:
                record["series_template_revision"] = series_template_revision
            if series_template_snapshot is not None:
                record["series_template_snapshot"] = series_template_snapshot
            if series_context_snapshot is not None:
                record["series_context_snapshot"] = series_context_snapshot
            if series_topic_source is not None:
                record["series_topic_source"] = series_topic_source
            if series_content_mode is not None:
                record["series_content_mode"] = series_content_mode

            # 保存完整记录到独立文件
            record_path = self._get_record_path(record_id)
            self._atomic_write_json(record_path, record)

            # 更新索引（用于快速列表查询）
            index = self._load_index()
            index_entry = {
                "id": record_id,
                "title": topic,
                "created_at": now,
                "updated_at": now,
                "status": RecordStatus.DRAFT,  # 索引中也记录状态
                "thumbnail": None,
                "page_count": len(outline.get("pages", [])),  # 预期页数
                "task_id": task_id
            }
            if series_id is not None:
                index_entry.update({
                    "series_id": series_id,
                    "series_project_id": series_project_id,
                    "series_template_id": series_template_id,
                    "series_item_index": series_item_index,
                    "series_item_title": series_item_title,
                    "series_item_id": series_item_id,
                    "series_template_revision": series_template_revision,
                    "series_content_mode": series_content_mode,
                })
            index["records"].insert(0, index_entry)
            self._save_index(index)

            return record_id

    def get_record(self, record_id: str, sync_images: bool = False) -> Optional[Dict]:
        """
        获取历史记录详情

        Args:
            record_id: 记录 ID

        Returns:
            Optional[Dict]: 记录详情，如果不存在则返回 None

        返回数据包含：
            - id: 记录 ID
            - title: 标题
            - created_at: 创建时间
            - updated_at: 更新时间
            - outline: 大纲内容
            - images: 图片信息（task_id 和 generated 列表）
            - status: 当前状态
            - thumbnail: 缩略图文件名
        """
        record_path = self._get_record_path(record_id)

        if not os.path.exists(record_path):
            return None

        try:
            with open(record_path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except Exception:
            return None

        # 旧版本记录没有 content；读取时补齐，调用方无需区分数据版本。
        record["content"] = self._normalize_content(record.get("content"))

        if sync_images:
            synced = self.sync_record_images(record_id, record)
            if synced.get("success") and synced.get("updated"):
                return self.get_record(record_id, sync_images=False)

        return record

    def record_exists(self, record_id: str) -> bool:
        """
        检查历史记录是否存在

        Args:
            record_id: 记录 ID

        Returns:
            bool: 记录是否存在
        """
        record_path = self._get_record_path(record_id)
        return os.path.exists(record_path)

    def update_record(
        self,
        record_id: str,
        outline: Optional[Dict] = None,
        images: Optional[Dict] = None,
        status: Optional[str] = None,
        thumbnail: Optional[str] = None,
        content: Optional[Dict] = None
    ) -> bool:
        """
        更新历史记录

        支持部分更新，只更新提供的字段。
        每次更新都会自动刷新 updated_at 时间戳。

        Args:
            record_id: 记录 ID
            outline: 大纲内容（可选，用于修改大纲）
            images: 图片信息（可选，包含 task_id 和 generated 列表）
            status: 状态（可选）
            thumbnail: 缩略图文件名（可选）
            content: 成品文案（可选，包含 titles、copywriting、tags 和 status）

        Returns:
            bool: 更新是否成功，记录不存在时返回 False

        状态流转说明：
            draft -> generating: 开始生成图片
            generating -> partial: 部分图片生成完成
            generating -> completed: 所有图片生成完成
            generating -> error: 生成过程出错
            partial -> generating: 继续生成剩余图片
            partial -> completed: 剩余图片生成完成
        """
        with self._ensure_lock():
            # 获取现有记录
            record = self.get_record(record_id)
            if not record:
                return False

            # 更新时间戳
            now = datetime.now().isoformat()
            record["updated_at"] = now

            # 更新大纲内容（支持修改大纲）
            if outline is not None:
                record["outline"] = outline

            # 更新图片信息
            if images is not None:
                record["images"] = self._merge_safe_images(record.get("images"), images)

            # content 支持嵌套部分更新；路由层负责拒绝非法类型。
            if content is not None:
                merged_content = self._normalize_content(record.get("content"))
                merged_content.update(content)
                record["content"] = self._normalize_content(merged_content)

            # 更新状态（状态流转）
            if status is not None:
                record["status"] = self._protect_status(record.get("status"), status, record)

            # 更新缩略图
            if thumbnail is not None:
                record["thumbnail"] = thumbnail

            # 保存完整记录
            record_path = self._get_record_path(record_id)
            self._atomic_write_json(record_path, record)

            # 同步更新索引
            index = self._load_index()
            for idx_record in index["records"]:
                if idx_record["id"] == record_id:
                    idx_record["updated_at"] = now

                    # 更新状态
                    idx_record["status"] = record.get("status", idx_record.get("status"))

                    # 更新缩略图
                    idx_record["thumbnail"] = record.get("thumbnail")

                    # 更新页数（如果大纲被修改）
                    if outline:
                        idx_record["page_count"] = len(outline.get("pages", []))

                    # 更新任务 ID
                    if record.get("images", {}).get("task_id"):
                        idx_record["task_id"] = record.get("images", {}).get("task_id")

                    break

            self._save_index(index)
            return True

    def merge_generated_image(
        self,
        record_id: str,
        task_id: str,
        page_index: int,
        filename: str,
        total_count: Optional[int] = None
    ) -> bool:
        """按页面索引合并单张已生成图片。"""
        with self._ensure_lock():
            record = self.get_record(record_id)
            if not record:
                return False

            # 图片 worker 可能在用户重新生成、或编辑页数并开启新任务后才返回。
            # 历史记录只接受当前绑定任务的逐页结果，避免旧任务的迟到结果把
            # 新任务的图片列表、缩略图和状态覆盖掉。
            active_task_id = (record.get("images") or {}).get("task_id")
            if active_task_id and active_task_id != task_id:
                logger.warning(
                    "忽略过期任务图片回写: record=%s task=%s active=%s index=%s",
                    record_id,
                    task_id,
                    active_task_id,
                    page_index,
                )
                return False

            if total_count is None:
                total_count = len(record.get("outline", {}).get("pages", []))

            existing_images = record.get("images") or {}
            generated = HistoryImageMerger.merge_generated(
                existing_images.get("generated"),
                page_index,
                filename,
                total_count,
            )
            status = HistoryImageMerger.compute_status(generated, total_count)
            thumbnail = HistoryImageMerger.first_image(generated)

            return self.update_record(
                record_id,
                images={
                    "task_id": task_id,
                    "generated": generated,
                },
                status=status,
                thumbnail=thumbnail,
            )

    def begin_generation(self, record_id: str, task_id: str) -> bool:
        """在上游请求开始前绑定任务，让刷新后的页面可以重新找到它。"""
        record = self.get_record(record_id)
        if not record:
            return False
        images = record.get("images") or {}
        # 绑定新任务代表开始一轮全新的生成，旧任务图片不能跟随到新任务。
        # 同一任务的断线续传/失败重试则继续保留已生成页。
        is_new_task = bool(images.get("task_id") and images.get("task_id") != task_id)
        return self.update_record(
            record_id,
            images={
                "task_id": task_id,
                "generated": [] if is_new_task else images.get("generated") or [],
            },
            status=RecordStatus.GENERATING,
        )

    def finish_generation(self, record_id: str, task_id: str, status: str) -> bool:
        """将历史记录收敛到任务终态，同时保留逐页落盘的图片。"""
        record = self.get_record(record_id)
        if not record:
            return False
        images = record.get("images") or {}
        # 旧任务迟到的终态不能覆盖该记录后来绑定的新任务。
        if images.get("task_id") != task_id:
            logger.warning(
                "忽略过期任务终态: record=%s task=%s active=%s",
                record_id,
                task_id,
                images.get("task_id"),
            )
            return False
        return self.update_record(record_id, status=status)

    def sync_record_images(self, record_id: str, record: Optional[Dict] = None) -> Dict[str, Any]:
        """从任务目录扫描图片并合并回历史记录。"""
        if record is None:
            record = self.get_record(record_id)
        if not record:
            return {"success": False, "error": "历史记录不存在"}

        task_id = record.get("images", {}).get("task_id")
        if not task_id:
            return {"success": True, "updated": False}

        files_by_index = HistoryImageMerger.files_by_index(self.history_dir, task_id)
        if not files_by_index:
            return {"success": True, "updated": False}

        total_count = len(record.get("outline", {}).get("pages", []))
        existing_generated = record.get("images", {}).get("generated", [])
        generated = HistoryImageMerger.merge_many(
            existing_generated,
            files_by_index,
            total_count,
        )
        status = HistoryImageMerger.compute_status(generated, total_count)
        thumbnail = HistoryImageMerger.first_image(generated)

        if (
            generated == existing_generated
            and record.get("status") == status
            and record.get("thumbnail") == thumbnail
        ):
            return {"success": True, "updated": False}

        updated = self.update_record(
            record_id,
            images={
                "task_id": task_id,
                "generated": generated,
            },
            status=status,
            thumbnail=thumbnail,
        )
        return {
            "success": updated,
            "updated": updated,
            "record_id": record_id,
            "task_id": task_id,
            "images": generated,
            "status": status,
        }

    def _merge_safe_images(self, current_images: Optional[Dict], incoming_images: Dict) -> Dict:
        current = dict(current_images or {})
        incoming = dict(incoming_images or {})

        current_generated = current.get("generated") or []
        incoming_generated = incoming.get("generated")

        # 显式绑定一个不同的新任务且传入空列表，表示开始一次全新生成。
        # 此时必须清空旧任务的图片；否则编辑页数或 force 重生成会继续显示
        # 已经不属于当前任务的文件名。
        starts_new_task = bool(
            incoming.get("task_id")
            and incoming.get("task_id") != current.get("task_id")
            and isinstance(incoming_generated, list)
            and not incoming_generated
        )

        if (
            not starts_new_task
            and
            isinstance(incoming_generated, list)
            and not HistoryImageMerger.has_images(incoming_generated)
            and HistoryImageMerger.has_images(current_generated)
        ):
            incoming["generated"] = current_generated

        if not incoming.get("task_id") and current.get("task_id"):
            incoming["task_id"] = current.get("task_id")

        return {
            "task_id": incoming.get("task_id"),
            "generated": [item or "" for item in incoming.get("generated", current_generated)],
        }

    def _protect_status(self, current_status: Optional[str], incoming_status: str, record: Dict) -> str:
        if (
            incoming_status == RecordStatus.GENERATING
            and current_status == RecordStatus.COMPLETED
            and HistoryImageMerger.has_images(record.get("images", {}).get("generated"))
        ):
            logger.info("忽略历史状态回退: %s -> %s", current_status, incoming_status)
            return current_status
        return incoming_status

    def delete_record(self, record_id: str) -> bool:
        """
        删除历史记录

        会同时删除：
        1. 记录 JSON 文件
        2. 关联的任务图片目录
        3. 索引中的记录

        Args:
            record_id: 记录 ID

        Returns:
            bool: 删除是否成功，记录不存在时返回 False
        """
        record = self.get_record(record_id)
        if not record:
            return False

        # 删除关联的任务图片目录
        if record.get("images") and record["images"].get("task_id"):
            task_id = record["images"]["task_id"]
            task_dir = os.path.join(self.history_dir, task_id)
            if os.path.exists(task_dir) and os.path.isdir(task_dir):
                try:
                    import shutil
                    shutil.rmtree(task_dir)
                    print(f"已删除任务目录: {task_dir}")
                except Exception as e:
                    print(f"删除任务目录失败: {task_dir}, {e}")

        # 删除记录 JSON 文件
        record_path = self._get_record_path(record_id)
        try:
            os.remove(record_path)
        except Exception:
            return False

        # 从索引中移除
        index = self._load_index()
        index["records"] = [r for r in index["records"] if r["id"] != record_id]
        self._save_index(index)

        return True

    def list_records(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None
    ) -> Dict:
        """
        分页获取历史记录列表

        Args:
            page: 页码，从 1 开始
            page_size: 每页记录数
            status: 状态过滤（可选），支持：draft/generating/partial/completed/error

        Returns:
            Dict: 分页结果
                - records: 当前页的记录列表
                - total: 总记录数
                - page: 当前页码
                - page_size: 每页大小
                - total_pages: 总页数
        """
        index = self._load_index()
        records = index.get("records", [])

        # 按状态过滤
        if status:
            records = [r for r in records if r.get("status") == status]

        # 分页计算
        total = len(records)
        start = (page - 1) * page_size
        end = start + page_size
        page_records = records[start:end]

        return {
            "records": page_records,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }

    def search_records(self, keyword: str) -> List[Dict]:
        """
        根据关键词搜索历史记录

        Args:
            keyword: 搜索关键词（不区分大小写）

        Returns:
            List[Dict]: 匹配的记录列表（按创建时间倒序）
        """
        index = self._load_index()
        records = index.get("records", [])

        # 不区分大小写的标题搜索
        keyword_lower = keyword.lower()
        results = [
            r for r in records
            if keyword_lower in r.get("title", "").lower()
        ]

        return results

    def get_statistics(self) -> Dict:
        """
        获取历史记录统计信息

        Returns:
            Dict: 统计数据
                - total: 总记录数
                - by_status: 各状态的记录数
                    - draft: 草稿数
                    - generating: 生成中数
                    - partial: 部分完成数
                    - completed: 已完成数
                    - error: 错误数
        """
        index = self._load_index()
        records = index.get("records", [])

        total = len(records)
        status_count = {}

        # 统计各状态的记录数
        for record in records:
            status = record.get("status", RecordStatus.DRAFT)
            status_count[status] = status_count.get(status, 0) + 1

        return {
            "total": total,
            "by_status": status_count
        }

    def scan_and_sync_task_images(self, task_id: str) -> Dict[str, Any]:
        """
        扫描任务文件夹，同步图片列表

        根据实际生成的图片数量自动更新记录状态：
        - 无图片 -> draft（草稿）
        - 部分图片 -> partial（部分完成）
        - 全部图片 -> completed（已完成）

        Args:
            task_id: 任务 ID

        Returns:
            Dict[str, Any]: 扫描结果
                - success: 是否成功
                - record_id: 关联的记录 ID
                - task_id: 任务 ID
                - images_count: 图片数量
                - images: 图片文件名列表
                - status: 更新后的状态
                - error: 错误信息（失败时）
        """
        task_dir = os.path.join(self.history_dir, task_id)

        if not os.path.exists(task_dir) or not os.path.isdir(task_dir):
            return {
                "success": False,
                "error": f"任务目录不存在: {task_id}"
            }

        try:
            files_by_index = HistoryImageMerger.files_by_index(self.history_dir, task_id)
            image_files = list(files_by_index.values())

            # 查找关联的历史记录
            index = self._load_index()
            record_id = None
            for rec in index.get("records", []):
                # 通过遍历所有记录，找到 task_id 匹配的记录
                record_detail = self.get_record(rec["id"])
                if record_detail and record_detail.get("images", {}).get("task_id") == task_id:
                    record_id = rec["id"]
                    break

            if record_id:
                # 更新历史记录
                record = self.get_record(record_id)
                if record:
                    expected_count = len(record.get("outline", {}).get("pages", []))
                    existing_generated = record.get("images", {}).get("generated", [])
                    merged_images = HistoryImageMerger.merge_many(
                        existing_generated,
                        files_by_index,
                        expected_count,
                    )
                    status = HistoryImageMerger.compute_status(merged_images, expected_count)

                    # 更新图片列表和状态
                    self.update_record(
                        record_id,
                        images={
                            "task_id": task_id,
                            "generated": merged_images
                        },
                        status=status,
                        thumbnail=HistoryImageMerger.first_image(merged_images)
                    )

                    return {
                        "success": True,
                        "record_id": record_id,
                        "task_id": task_id,
                        "images_count": len(image_files),
                        "images": merged_images,
                        "status": status
                    }

            # 没有关联的记录，返回扫描结果
            return {
                "success": True,
                "task_id": task_id,
                "images_count": len(image_files),
                "images": image_files,
                "no_record": True
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"扫描任务失败: {str(e)}"
            }

    def scan_all_tasks(self) -> Dict[str, Any]:
        """
        扫描所有任务文件夹，同步图片列表

        批量扫描 history 目录下的所有任务文件夹，
        同步图片列表并更新记录状态。

        Returns:
            Dict[str, Any]: 扫描结果统计
                - success: 是否成功
                - total_tasks: 扫描的任务总数
                - synced: 成功同步的任务数
                - failed: 失败的任务数
                - orphan_tasks: 孤立任务列表（有图片但无记录）
                - results: 详细结果列表
                - error: 错误信息（失败时）
        """
        if not os.path.exists(self.history_dir):
            return {
                "success": False,
                "error": "历史记录目录不存在"
            }

        try:
            synced_count = 0
            failed_count = 0
            orphan_tasks = []  # 没有关联记录的任务
            results = []

            # 遍历 history 目录
            for item in os.listdir(self.history_dir):
                item_path = os.path.join(self.history_dir, item)

                # 只处理目录（任务文件夹）
                if not os.path.isdir(item_path):
                    continue

                # 假设任务文件夹名就是 task_id
                task_id = item

                # 扫描并同步
                result = self.scan_and_sync_task_images(task_id)
                results.append(result)

                if result.get("success"):
                    if result.get("no_record"):
                        orphan_tasks.append(task_id)
                    else:
                        synced_count += 1
                else:
                    failed_count += 1

            return {
                "success": True,
                "total_tasks": len(results),
                "synced": synced_count,
                "failed": failed_count,
                "orphan_tasks": orphan_tasks,
                "results": results
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"扫描所有任务失败: {str(e)}"
            }


_service_instance = None


def get_history_service() -> HistoryService:
    """
    获取历史记录服务实例（单例模式）

    Returns:
        HistoryService: 历史记录服务实例
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = HistoryService()
    return _service_instance
