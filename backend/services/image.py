"""图片生成服务"""
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, Any, Generator, List, Optional, Tuple
from backend.config import Config
from backend.errors import ensure_app_error
from backend.generators.factory import ImageGeneratorFactory
from backend.generators.image_provider_policy import ImageProviderPolicy
from backend.services.history import get_history_service
from backend.services.history_image_merger import HistoryImageMerger
from backend.services.image_rate_limiter import ImageRateLimiter
from backend.utils.image_compressor import compress_image

logger = logging.getLogger(__name__)


ACTIVE_TASK_STATUSES = {"queued", "running"}
SYSTEMIC_ERROR_CODES = {
    "AUTH_OR_PERMISSION",
    "ENDPOINT_METHOD_MISMATCH",
    "INVALID_REQUEST",
    "MODEL_ENDPOINT_MISMATCH",
    "MODEL_NOT_FOUND",
    "NETWORK_ERROR",
    "NETWORK_FAKE_IP_TLS",
    "NETWORK_TIMEOUT",
    "PROXY_UNAVAILABLE",
    "RATE_LIMITED",
    "UPSTREAM_PARAM_UNSUPPORTED",
    "UPSTREAM_CONNECTION_CLOSED",
    "UPSTREAM_UNAVAILABLE",
}


class ActiveGenerationError(RuntimeError):
    """同一历史记录已经有活动任务。"""

    def __init__(self, task_id: str, state: Dict[str, Any]):
        super().__init__(f"该记录已有图片生成任务：{task_id}")
        self.task_id = task_id
        self.state = state


class ImageService:
    """图片生成服务类"""

    def __init__(self, provider_name: str = None):
        """
        初始化图片生成服务

        Args:
            provider_name: 服务商名称，如果为None则使用配置文件中的激活服务商
        """
        logger.debug("初始化 ImageService...")

        # 获取服务商配置
        if provider_name is None:
            provider_name = Config.get_active_image_provider()

        logger.info(f"使用图片服务商: {provider_name}")
        provider_config = Config.get_image_provider_config(provider_name)

        # 创建生成器实例
        provider_type = provider_config.get('type', provider_name)
        logger.debug(f"创建生成器: type={provider_type}")
        self.generator = ImageGeneratorFactory.create(provider_type, provider_config)

        # 保存配置信息
        self.provider_name = provider_name
        self.provider_config = provider_config
        self.policy = ImageProviderPolicy.from_config(
            provider_config,
            default_model=provider_config.get('model', 'default-model'),
        )
        self.worker_count = self.policy.worker_count
        self.rate_limiter = ImageRateLimiter(
            max_concurrent=self.worker_count,
            interval_seconds=self.policy.request_interval_seconds,
        )
        self.history_service = get_history_service()

        # 检查是否启用短 prompt 模式
        self.use_short_prompt = provider_config.get('short_prompt', False)

        # 加载提示词模板
        self.prompt_template = self._load_prompt_template()
        self.prompt_template_short = self._load_prompt_template(short=True)

        # 历史记录根目录
        self.history_root_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "history"
        )
        os.makedirs(self.history_root_dir, exist_ok=True)

        # 存储任务状态（用于重试）
        self._task_states: Dict[str, Dict] = {}
        self._task_lock = threading.RLock()

        logger.info(f"ImageService 初始化完成: provider={provider_name}, type={provider_type}")

    @staticmethod
    def _count_generated(generated_images: List[str]) -> int:
        return sum(1 for filename in generated_images if filename)

    @staticmethod
    def _remember_generated(generated_images: List[str], index: int, filename: str, total: int):
        target_len = max(len(generated_images), total, index + 1)
        while len(generated_images) < target_len:
            generated_images.append("")
        generated_images[index] = filename

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_runtime_state(self):
        """兼容测试中通过 __new__ 构造的轻量服务实例。"""
        if not hasattr(self, "_task_states"):
            self._task_states = {}
        if not hasattr(self, "_task_lock"):
            self._task_lock = threading.RLock()

    def _safe_task_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        generated = dict(state.get("generated") or {})
        failed = dict(state.get("failed") or {})
        return {
            "task_id": state.get("task_id"),
            "record_id": state.get("record_id"),
            "status": state.get("status"),
            "phase": state.get("phase"),
            "current_index": state.get("current_index"),
            "attempt": state.get("attempt", 0),
            "total": state.get("total", 0),
            "completed": len(generated),
            "failed_count": len(failed),
            "generated": generated,
            "failed": failed,
            "failed_indices": sorted(failed),
            "error": state.get("error"),
            "created_at": state.get("created_at"),
            "started_at": state.get("started_at"),
            "updated_at": state.get("updated_at"),
            "finished_at": state.get("finished_at"),
            "has_cover": state.get("cover_image") is not None,
        }

    def prepare_generation(
        self,
        pages: list,
        task_id: Optional[str] = None,
        record_id: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """原子预留任务 ID，并在任何上游调用前绑定历史记录。"""
        self._ensure_runtime_state()

        record = None
        if record_id:
            record = self.history_service.get_record(record_id, sync_images=True)
            images = (record or {}).get("images") or {}
            generated = images.get("generated") or []
            if not force and images.get("task_id") and HistoryImageMerger.has_images(generated):
                return {
                    "task_id": images["task_id"],
                    "record_id": record_id,
                    "cached": True,
                    "reused": True,
                }

        with self._task_lock:
            if record_id:
                for active_id, active_state in self._task_states.items():
                    if (
                        active_state.get("record_id") == record_id
                        and active_state.get("status") in ACTIVE_TASK_STATUSES
                    ):
                        raise ActiveGenerationError(
                            active_id,
                            self._safe_task_state(active_state),
                        )

            # force 表示当前大纲（尤其是编辑页数后）必须作为一次新的图片任务
            # 执行。绝不能复用旧任务目录，否则旧图片会混进新的页数和结果中。
            if force:
                task_id = f"task_{uuid.uuid4().hex[:8]}"
            elif task_id is None and record:
                task_id = (record.get("images") or {}).get("task_id")
            if task_id is None or (
                task_id in self._task_states
                and self._task_states[task_id].get("status") in ACTIVE_TASK_STATUSES
            ):
                task_id = f"task_{uuid.uuid4().hex[:8]}"

            now = self._now()
            # 新任务从空图片列表开始；缓存复用路径已经在上方提前返回。
            existing_generated = [] if force else (
                ((record or {}).get("images") or {}).get("generated") or []
            )
            self._task_states[task_id] = {
                "task_id": task_id,
                "record_id": record_id,
                "status": "queued",
                "phase": "accepted",
                "current_index": None,
                "attempt": 0,
                "total": len(pages),
                "pages": pages,
                "generated": {
                    index: filename
                    for index, filename in enumerate(existing_generated)
                    if filename
                },
                "failed": {},
                "cover_image": None,
                "full_outline": "",
                "user_images": None,
                "user_topic": "",
                "error": None,
                "created_at": now,
                "started_at": None,
                "updated_at": now,
                "finished_at": None,
            }

        if record_id:
            self.history_service.begin_generation(record_id, task_id)

        return {
            "task_id": task_id,
            "record_id": record_id,
            "cached": False,
            "reused": False,
        }

    def _update_task(self, task_id: str, **changes):
        self._ensure_runtime_state()
        with self._task_lock:
            state = self._task_states.get(task_id)
            if not state:
                return
            state.update(changes)
            state["updated_at"] = self._now()

    def _mark_attempt(self, task_id: str, index: int, phase: str, attempt: int = 1):
        self._update_task(
            task_id,
            status="running",
            phase=phase,
            current_index=index,
            attempt=attempt,
        )

    def _load_prompt_template(self, short: bool = False) -> str:
        """加载 Prompt 模板"""
        filename = "image_prompt_short.txt" if short else "image_prompt.txt"
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts",
            filename
        )
        if not os.path.exists(prompt_path):
            # 如果短模板不存在，返回空字符串
            return ""
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    def _save_image(self, image_data: bytes, filename: str, task_dir: str) -> str:
        """
        保存图片到本地，同时生成缩略图

        Args:
            image_data: 图片二进制数据
            filename: 文件名
            task_dir: 任务目录（必须由调用任务显式传入）

        Returns:
            保存的文件路径
        """
        if task_dir is None:
            raise ValueError("任务目录未设置")

        # 保存原图
        filepath = os.path.join(task_dir, filename)
        with open(filepath, "wb") as f:
            f.write(image_data)

        # 生成缩略图（50KB左右）
        thumbnail_data = compress_image(image_data, max_size_kb=50)
        thumbnail_filename = f"thumb_{filename}"
        thumbnail_path = os.path.join(task_dir, thumbnail_filename)
        with open(thumbnail_path, "wb") as f:
            f.write(thumbnail_data)

        return filepath

    def _generate_single_image(
        self,
        page: Dict,
        task_id: str,
        reference_image: Optional[bytes] = None,
        retry_count: int = 0,
        full_outline: str = "",
        user_images: Optional[List[bytes]] = None,
        user_topic: str = "",
        record_id: Optional[str] = None,
        total_count: Optional[int] = None,
        task_dir: Optional[str] = None,
        phase: str = "content",
    ) -> Tuple[int, bool, Optional[str], Optional[str]]:
        """
        生成单张图片（带自动重试）

        Args:
            page: 页面数据
            task_id: 任务ID
            reference_image: 参考图片（封面图）
            retry_count: 当前重试次数
            full_outline: 完整的大纲文本
            user_images: 用户上传的参考图片列表
            user_topic: 用户原始输入

        Returns:
            (index, success, filename, error_message)
        """
        index = page["index"]
        page_type = page["type"]
        page_content = page["content"]

        try:
            if task_dir is None:
                raise ValueError("任务目录未设置")
            self._mark_attempt(task_id, index, phase, retry_count + 1)
            logger.debug(f"生成图片 [{index}]: type={page_type}")

            # 根据配置选择模板（短 prompt 或完整 prompt）
            if self.use_short_prompt and self.prompt_template_short:
                # 短 prompt 模式：只包含页面类型和内容
                prompt = self.prompt_template_short.format(
                    page_content=page_content,
                    page_type=page_type
                )
                logger.debug(f"  使用短 prompt 模式 ({len(prompt)} 字符)")
            else:
                # 完整 prompt 模式：包含大纲和用户需求
                prompt = self.prompt_template.format(
                    page_content=page_content,
                    page_type=page_type,
                    full_outline=full_outline,
                    user_topic=user_topic if user_topic else "未提供"
                )

            # 调用生成器生成图片。所有路径共用 limiter，避免批量和重试打爆上游。
            with self.rate_limiter.acquire():
                if self.provider_config.get('type') == 'google_genai':
                    logger.debug(f"  使用 Google GenAI 生成器")
                    image_data = self.generator.generate_image(
                        prompt=prompt,
                        aspect_ratio=self.provider_config.get('default_aspect_ratio', '3:4'),
                        temperature=self.provider_config.get('temperature', 1.0),
                        model=self.provider_config.get('model', 'gemini-3-pro-image-preview'),
                        reference_image=reference_image,
                    )
                elif self.provider_config.get('type') == 'image_api':
                    logger.debug(f"  使用 Image API 生成器")
                    # Image API 支持多张参考图片
                    # 组合参考图片：用户上传的图片 + 封面图
                    reference_images = []
                    if user_images:
                        reference_images.extend(user_images)
                    if reference_image:
                        reference_images.append(reference_image)

                    image_data = self.generator.generate_image(
                        prompt=prompt,
                        aspect_ratio=self.provider_config.get('default_aspect_ratio', '3:4'),
                        temperature=self.provider_config.get('temperature', 1.0),
                        model=self.provider_config.get('model', 'nano-banana-2'),
                        reference_images=reference_images if reference_images else None,
                    )
                else:
                    logger.debug(f"  使用 OpenAI 兼容生成器")
                    image_data = self.generator.generate_image(
                        prompt=prompt,
                        size=self.provider_config.get('default_size', '1024x1024'),
                        model=self.provider_config.get('model'),
                        quality=self.provider_config.get('quality', 'standard'),
                    )

            # 保存图片。任务目录沿调用链显式传递，避免并发任务串写。
            filename = f"{index}.png"
            self._save_image(image_data, filename, task_dir)
            logger.info(f"✅ 图片 [{index}] 生成成功: {filename}")

            if record_id:
                self.history_service.merge_generated_image(
                    record_id,
                    task_id,
                    index,
                    filename,
                    total_count=total_count,
                )

            return (index, True, filename, None)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ 图片 [{index}] 生成失败: {error_msg[:200]}")
            return (index, False, None, error_msg)

    def generate_images(
        self,
        pages: list,
        task_id: str = None,
        full_outline: str = "",
        user_images: Optional[List[bytes]] = None,
        user_topic: str = "",
        record_id: Optional[str] = None,
        force: bool = False,
        prepared: bool = False,
        cached: bool = False,
    ) -> Generator[Dict[str, Any], None, None]:
        """安全包装生成流，确保断流和内部异常也写入任务终态。"""
        if not prepared:
            reservation = self.prepare_generation(pages, task_id, record_id, force)
            task_id = reservation["task_id"]
            cached = reservation["cached"]
            prepared = True

        try:
            yield from self._generate_images_impl(
                pages,
                task_id,
                full_outline,
                user_images,
                user_topic,
                record_id,
                force,
                prepared,
                cached,
            )
        except GeneratorExit:
            self._settle_aborted_task(task_id, record_id, "interrupted", "客户端连接已中断")
            raise
        except Exception as exc:
            logger.exception("图片任务内部异常: task_id=%s", task_id)
            app_error = ensure_app_error(exc, context={"task_id": task_id, "phase": "internal"})
            self._settle_aborted_task(task_id, record_id, "failed", app_error.to_dict())
            yield {
                "event": "error",
                "data": {
                    "status": "error",
                    "message": app_error.to_message(),
                    "error": app_error.to_dict(),
                    "retryable": app_error.retryable,
                    "phase": "internal",
                },
            }
            state = self.get_task_state(task_id) or {}
            yield {
                "event": "finish",
                "data": {
                    "success": False,
                    "status": state.get("status", "failed"),
                    "task_id": task_id,
                    "images": [],
                    "total": len(pages),
                    "completed": state.get("completed", 0),
                    "failed": state.get("failed_count", len(pages)),
                    "failed_indices": state.get("failed_indices", []),
                },
            }

    def _settle_aborted_task(
        self,
        task_id: str,
        record_id: Optional[str],
        status: str,
        error: Any,
    ):
        state = self.get_task_state(task_id) or {}
        completed = state.get("completed", 0)
        self._update_task(
            task_id,
            status=status if not completed else "partial",
            phase=status,
            current_index=None,
            error=error,
            finished_at=self._now(),
        )
        if record_id:
            self.history_service.finish_generation(
                record_id,
                task_id,
                "partial" if completed else "error",
            )

    def _generate_images_impl(
        self,
        pages: list,
        task_id: str = None,
        full_outline: str = "",
        user_images: Optional[List[bytes]] = None,
        user_topic: str = "",
        record_id: Optional[str] = None,
        force: bool = False,
        prepared: bool = False,
        cached: bool = False,
    ) -> Generator[Dict[str, Any], None, None]:
        """生成图片，并用真实任务状态驱动 SSE。"""
        if not prepared:
            reservation = self.prepare_generation(pages, task_id, record_id, force)
            task_id = reservation["task_id"]
            cached = reservation["cached"]

        yield {
            "event": "accepted",
            "data": {
                "task_id": task_id,
                "record_id": record_id,
                "status": "queued" if not cached else "completed",
                "phase": "accepted",
                "reused": bool(cached),
            },
        }

        if cached:
            for event in self.get_cached_generation_events(record_id, pages):
                yield event
            return

        task_dir = os.path.join(self.history_root_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        total = len(pages)
        compressed_user_images = (
            [compress_image(img, max_size_kb=200) for img in user_images]
            if user_images else None
        )
        started_at = self._now()
        self._update_task(
            task_id,
            status="running",
            phase="cover",
            started_at=started_at,
            full_outline=full_outline,
            user_images=compressed_user_images,
            user_topic=user_topic,
        )
        logger.info("开始图片生成任务: task_id=%s, pages=%s", task_id, total)

        state = self._task_states[task_id]
        generated_images = [""] * total
        for index, filename in (state.get("generated") or {}).items():
            self._remember_generated(generated_images, index, filename, total)
        failed_pages: List[Dict] = []
        cover_image_data = None

        cover_page = next((page for page in pages if page.get("type") == "cover"), None)
        other_pages = [page for page in pages if page is not cover_page]
        if cover_page is None and pages:
            cover_page, other_pages = pages[0], pages[1:]

        if cover_page:
            yield {
                "event": "progress",
                "data": {
                    "index": cover_page["index"],
                    "status": "generating",
                    "message": "正在生成封面...",
                    "current": 1,
                    "total": total,
                    "phase": "cover",
                    "attempt": 1,
                },
            }
            result = self._generate_single_image(
                cover_page,
                task_id,
                reference_image=None,
                full_outline=full_outline,
                user_images=compressed_user_images,
                user_topic=user_topic,
                record_id=record_id,
                total_count=total,
                task_dir=task_dir,
                phase="cover",
            )
            index, success, filename, error = result
            if success:
                self._remember_generated(generated_images, index, filename, total)
                state["generated"][index] = filename
                cover_path = os.path.join(task_dir, filename)
                with open(cover_path, "rb") as image_file:
                    cover_image_data = compress_image(image_file.read(), max_size_kb=200)
                state["cover_image"] = cover_image_data
                self._update_task(task_id, phase="content", current_index=index)
                yield {
                    "event": "complete",
                    "data": {
                        "index": index,
                        "status": "done",
                        "image_url": f"/api/images/{task_id}/{filename}",
                        "phase": "cover",
                    },
                }
            else:
                failed_pages.append(cover_page)
                state["failed"][index] = error
                app_error = ensure_app_error(error, context={"task_id": task_id, "phase": "cover"})
                self._update_task(task_id, error=app_error.to_dict())
                yield {
                    "event": "error",
                    "data": {
                        "index": index,
                        "status": "error",
                        "message": error,
                        "retryable": app_error.retryable,
                        "phase": "cover",
                    },
                }

                # 认证、配置、网络、限流等系统性错误对后续页面同样成立，立即熔断。
                if app_error.code in SYSTEMIC_ERROR_CODES:
                    for page in other_pages:
                        failed_pages.append(page)
                        state["failed"][page["index"]] = f"封面生成失败，已停止剩余页面：{error}"
                        yield {
                            "event": "error",
                            "data": {
                                "index": page["index"],
                                "status": "error",
                                "message": "封面遇到系统性错误，已停止剩余页面生成",
                                "retryable": app_error.retryable,
                                "phase": "circuit_breaker",
                                "cause_index": index,
                            },
                        }
                    other_pages = []
                    self._update_task(task_id, phase="circuit_breaker")

        if other_pages:
            yield {
                "event": "progress",
                "data": {
                    "status": "batch_start",
                    "message": f"开始生成 {len(other_pages)} 页内容...",
                    "current": self._count_generated(generated_images),
                    "total": total,
                    "phase": "content",
                },
            }

            def generate_page(page: Dict):
                return self._generate_single_image(
                    page,
                    task_id,
                    cover_image_data,
                    0,
                    full_outline,
                    compressed_user_images,
                    user_topic,
                    record_id,
                    total,
                    task_dir,
                    "content",
                )

            if self.worker_count > 1:
                with ThreadPoolExecutor(max_workers=self.worker_count) as executor:
                    future_to_page = {executor.submit(generate_page, page): page for page in other_pages}
                    results = ((future_to_page[future], future.result()) for future in as_completed(future_to_page))
                    for page, result in results:
                        yield self._generation_result_event(
                            task_id, page, result, generated_images, failed_pages, total
                        )
            else:
                for page in other_pages:
                    yield {
                        "event": "progress",
                        "data": {
                            "index": page["index"],
                            "status": "generating",
                            "current": self._count_generated(generated_images) + 1,
                            "total": total,
                            "phase": "content",
                            "attempt": 1,
                        },
                    }
                    yield self._generation_result_event(
                        task_id, page, generate_page(page), generated_images, failed_pages, total
                    )

        completed = self._count_generated(generated_images)
        failed_indices = sorted({page["index"] for page in failed_pages})
        if completed == total:
            task_status, history_status = "completed", "completed"
        elif completed:
            task_status, history_status = "partial", "partial"
        else:
            task_status, history_status = "failed", "error"
        finished_at = self._now()
        self._update_task(
            task_id,
            status=task_status,
            phase="finished",
            current_index=None,
            finished_at=finished_at,
        )
        if record_id:
            self.history_service.finish_generation(record_id, task_id, history_status)

        yield {
            "event": "finish",
            "data": {
                "success": task_status == "completed",
                "status": task_status,
                "task_id": task_id,
                "images": generated_images,
                "total": total,
                "completed": completed,
                "failed": len(failed_indices),
                "failed_indices": failed_indices,
            },
        }

    def _generation_result_event(
        self,
        task_id: str,
        page: Dict,
        result: Tuple[int, bool, Optional[str], Optional[str]],
        generated_images: List[str],
        failed_pages: List[Dict],
        total: int,
    ) -> Dict[str, Any]:
        index, success, filename, error = result
        state = self._task_states[task_id]
        if success:
            self._remember_generated(generated_images, index, filename, total)
            state["generated"][index] = filename
            state["failed"].pop(index, None)
            self._update_task(task_id, phase="content", current_index=index)
            return {
                "event": "complete",
                "data": {
                    "index": index,
                    "status": "done",
                    "image_url": f"/api/images/{task_id}/{filename}",
                    "phase": "content",
                },
            }
        failed_pages.append(page)
        state["failed"][index] = error
        app_error = ensure_app_error(error, context={"task_id": task_id, "phase": "content"})
        self._update_task(task_id, error=app_error.to_dict())
        return {
            "event": "error",
            "data": {
                "index": index,
                "status": "error",
                "message": error,
                "retryable": app_error.retryable,
                "phase": "content",
            },
        }

    def get_cached_generation_events(self, record_id: str, pages: list) -> List[Dict[str, Any]]:
        record = self.history_service.get_record(record_id, sync_images=True)
        if not record:
            return []

        images = record.get("images") or {}
        task_id = images.get("task_id")
        generated = images.get("generated") or []
        if not task_id or not HistoryImageMerger.has_images(generated):
            return []

        total = len(pages)
        completed = 0
        failed_indices = []
        events: List[Dict[str, Any]] = []

        for page in pages:
            index = page.get("index")
            filename = generated[index] if isinstance(index, int) and index < len(generated) else ""
            if filename:
                completed += 1
                events.append({
                    "event": "complete",
                    "data": {
                        "index": index,
                        "status": "done",
                        "image_url": f"/api/images/{task_id}/{filename}",
                        "phase": "cached",
                        "cached": True,
                    }
                })
            else:
                failed_indices.append(index)
                events.append({
                    "event": "error",
                    "data": {
                        "index": index,
                        "status": "error",
                        "message": "历史记录中缺少该页图片，可手动补全",
                        "retryable": True,
                        "phase": "cached",
                        "cached": True,
                    }
                })

        events.append({
            "event": "finish",
            "data": {
                "success": len(failed_indices) == 0,
                "task_id": task_id,
                "images": generated,
                "total": total,
                "completed": completed,
                "failed": len(failed_indices),
                "failed_indices": failed_indices,
                "cached": True,
            }
        })
        return events

    def retry_single_image(
        self,
        task_id: str,
        page: Dict,
        use_reference: bool = True,
        full_outline: str = "",
        user_topic: str = "",
        record_id: Optional[str] = None,
        revision_request: str = ""
    ) -> Dict[str, Any]:
        """
        重试生成单张图片

        Args:
            task_id: 任务ID
            page: 页面数据
            use_reference: 是否使用封面作为参考
            full_outline: 完整大纲文本（从前端传入）
            user_topic: 用户原始输入（从前端传入）

        Returns:
            生成结果
        """
        task_dir = os.path.join(self.history_root_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)

        reference_image = None
        user_images = None

        # 首先尝试从任务状态中获取上下文
        if task_id in self._task_states:
            task_state = self._task_states[task_id]
            if use_reference:
                reference_image = task_state.get("cover_image")
            # 如果没有传入上下文，则使用任务状态中的
            if not full_outline:
                full_outline = task_state.get("full_outline", "")
            if not user_topic:
                user_topic = task_state.get("user_topic", "")
            user_images = task_state.get("user_images")

        # 如果任务状态中没有封面图，尝试从文件系统加载
        if use_reference and reference_image is None:
            cover_path = os.path.join(task_dir, "0.png")
            if os.path.exists(cover_path):
                with open(cover_path, "rb") as f:
                    cover_data = f.read()
                # 压缩封面图到 200KB
                reference_image = compress_image(cover_data, max_size_kb=200)

        total_count = None
        if task_id in self._task_states:
            total_count = len(self._task_states[task_id].get("pages", []))

        page_for_generation = dict(page)
        if revision_request:
            original_content = str(page_for_generation.get("content", ""))
            page_for_generation["content"] = (
                f"{original_content}\n\n【本次重绘修改意见】{revision_request}\n"
                "请在保留本页核心信息的前提下，优先落实以上修改意见。"
            )

        self._update_task(task_id, status="running", phase="retry", finished_at=None)
        index, success, filename, error = self._generate_single_image(
            page_for_generation,
            task_id,
            reference_image,
            0,
            full_outline,
            user_images,
            user_topic,
            record_id,
            total_count,
            task_dir,
            "retry",
        )

        if success:
            if task_id in self._task_states:
                self._task_states[task_id]["generated"][index] = filename
                if index in self._task_states[task_id]["failed"]:
                    del self._task_states[task_id]["failed"][index]

            self._settle_retry_task(task_id, record_id)
            return {
                "success": True,
                "index": index,
                "image_url": f"/api/images/{task_id}/{filename}"
            }
        else:
            if task_id in self._task_states:
                self._task_states[task_id]["failed"][index] = error
            self._settle_retry_task(task_id, record_id)
            return {
                "success": False,
                "index": index,
                "error": error,
                "retryable": True
            }

    def retry_failed_images(
        self,
        task_id: str,
        pages: List[Dict],
        record_id: Optional[str] = None
    ) -> Generator[Dict[str, Any], None, None]:
        """
        批量重试失败的图片

        Args:
            task_id: 任务ID
            pages: 需要重试的页面列表

        Yields:
            进度事件
        """
        task_dir = os.path.join(self.history_root_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        self._update_task(task_id, status="running", phase="retry", finished_at=None)

        # 获取参考图和上下文
        reference_image = None
        user_images = None
        user_topic = ""
        if task_id in self._task_states:
            task_state = self._task_states[task_id]
            reference_image = task_state.get("cover_image")
            user_images = task_state.get("user_images")
            user_topic = task_state.get("user_topic", "")

        if reference_image is None:
            cover_path = os.path.join(self.history_root_dir, task_id, "0.png")
            if os.path.exists(cover_path):
                with open(cover_path, "rb") as f:
                    reference_image = compress_image(f.read(), max_size_kb=200)

        total = len(pages)
        success_count = 0
        failed_count = 0

        yield {
            "event": "retry_start",
            "data": {
                "total": total,
                "message": f"开始重试 {total} 张失败的图片"
            }
        }

        # 从任务状态中获取完整大纲
        full_outline = ""
        if task_id in self._task_states:
            full_outline = self._task_states[task_id].get("full_outline", "")
        total_count = None
        if task_id in self._task_states:
            total_count = len(self._task_states[task_id].get("pages", []))
        if record_id:
            record = self.history_service.get_record(record_id)
            if record:
                total_count = total_count or len(record.get("outline", {}).get("pages", []))

        def handle_result(page: Dict, result: Tuple[int, bool, Optional[str], Optional[str]]):
            nonlocal success_count, failed_count
            index, success, filename, error = result
            if success:
                success_count += 1
                if task_id in self._task_states:
                    self._task_states[task_id]["generated"][index] = filename
                    if index in self._task_states[task_id]["failed"]:
                        del self._task_states[task_id]["failed"][index]
                return {
                    "event": "complete",
                    "data": {
                        "index": index,
                        "status": "done",
                        "image_url": f"/api/images/{task_id}/{filename}"
                    }
                }

            failed_count += 1
            return {
                "event": "error",
                "data": {
                    "index": index,
                    "status": "error",
                    "message": error,
                    "retryable": True
                }
            }

        if self.worker_count > 1:
            with ThreadPoolExecutor(max_workers=self.worker_count) as executor:
                future_to_page = {
                    executor.submit(
                        self._generate_single_image,
                        page,
                        task_id,
                        reference_image,
                        0,
                        full_outline,
                        user_images,
                        user_topic,
                        record_id,
                        total_count,
                        task_dir,
                        "retry",
                    ): page
                    for page in pages
                }

                for future in as_completed(future_to_page):
                    page = future_to_page[future]
                    try:
                        yield handle_result(page, future.result())
                    except Exception as e:
                        failed_count += 1
                        yield {
                            "event": "error",
                            "data": {
                                "index": page["index"],
                                "status": "error",
                                "message": str(e),
                                "retryable": True
                            }
                        }
        else:
            for page in pages:
                result = self._generate_single_image(
                    page,
                    task_id,
                    reference_image,
                    0,
                    full_outline,
                    user_images,
                    user_topic,
                    record_id,
                    total_count,
                    task_dir,
                    "retry",
                )
                yield handle_result(page, result)

        self._settle_retry_task(task_id, record_id)
        yield {
            "event": "retry_finish",
            "data": {
                "success": failed_count == 0,
                "total": total,
                "completed": success_count,
                "failed": failed_count
            }
        }

    def _settle_retry_task(self, task_id: str, record_id: Optional[str]):
        """重试结束后恢复可靠终态，避免任务永久停留在 running。"""
        if task_id not in self._task_states:
            return
        state = self._task_states[task_id]
        completed = len(state.get("generated") or {})
        total = state.get("total") or len(state.get("pages") or [])
        if total and completed >= total:
            task_status, history_status = "completed", "completed"
        elif completed:
            task_status, history_status = "partial", "partial"
        else:
            task_status, history_status = "failed", "error"
        self._update_task(
            task_id,
            status=task_status,
            phase="finished",
            current_index=None,
            finished_at=self._now(),
        )
        if record_id:
            self.history_service.finish_generation(record_id, task_id, history_status)

    def regenerate_image(
        self,
        task_id: str,
        page: Dict,
        use_reference: bool = True,
        full_outline: str = "",
        user_topic: str = "",
        record_id: Optional[str] = None,
        revision_request: str = ""
    ) -> Dict[str, Any]:
        """
        重新生成图片（用户手动触发，即使成功的也可以重新生成）

        Args:
            task_id: 任务ID
            page: 页面数据
            use_reference: 是否使用封面作为参考
            full_outline: 完整大纲文本
            user_topic: 用户原始输入
            revision_request: 本次重绘的补充修改意见

        Returns:
            生成结果
        """
        return self.retry_single_image(
            task_id, page, use_reference,
            full_outline=full_outline,
            user_topic=user_topic,
            record_id=record_id,
            revision_request=revision_request
        )

    def get_image_path(self, task_id: str, filename: str) -> str:
        """
        获取图片完整路径

        Args:
            task_id: 任务ID
            filename: 文件名

        Returns:
            完整路径
        """
        task_dir = os.path.join(self.history_root_dir, task_id)
        return os.path.join(task_dir, filename)

    def get_task_state(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        self._ensure_runtime_state()
        with self._task_lock:
            state = self._task_states.get(task_id)
            return self._safe_task_state(state) if state else None

    def cleanup_task(self, task_id: str):
        """清理任务状态（释放内存）"""
        if task_id in self._task_states:
            del self._task_states[task_id]


# 全局服务实例
_service_instance = None

def get_image_service() -> ImageService:
    """获取全局图片生成服务实例"""
    global _service_instance
    if _service_instance is None:
        _service_instance = ImageService()
    return _service_instance

def reset_image_service():
    """重置全局服务实例（配置更新后调用）"""
    global _service_instance
    _service_instance = None
