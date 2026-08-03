"""本地小红书发布任务服务。

发布器本身是基于 Chrome CDP 的第三方 CLI，因此这里只负责安全地准备参数、
维护任务状态以及把 CLI 放到单独的后台线程中运行。浏览器不会在导入模块时
启动，只有真正提交发布任务后才会调用第三方脚本。
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

from backend.errors import AppError
from backend.services.history import get_history_service

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "account": "",
    "port": 9222,
    "headless": False,
    "default_mode": "preview",
}

TERMINAL_STATUSES = {"published", "submitted", "failed", "unknown", "auth_required"}
ACTIVE_STATUSES = {
    "queued",
    "validating",
    "opening_browser",
    "uploading",
    "filling",
    "ready_for_review",
    "submitting",
}
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
NOTE_URL_RE = re.compile(
    r"https?://(?:www\.)?xiaohongshu\.com/explore/[A-Za-z0-9_-]+(?:\?[^\s]+)?",
    re.IGNORECASE,
)


class PublishServiceError(Exception):
    """可直接转换成统一 API 错误的服务异常。"""

    def __init__(self, code: str, title: str, detail: str, suggestion: str, status: int = 400):
        self.app_error = AppError(
            code=code,
            title=title,
            detail=detail,
            suggestion=suggestion,
            status=status,
            retryable=False,
        )
        super().__init__(detail)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, value: Any, *, mode: int = 0o600, yaml_format: bool = False) -> None:
    """在同一目录中原子写入配置/任务文件，并收紧权限。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if yaml_format:
                yaml.safe_dump(value, handle, allow_unicode=True, sort_keys=False)
            else:
                json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, mode)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle) or {}
        return value if isinstance(value, dict) else {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("读取小红书发布配置失败，将使用默认值: %s", exc)
        return {}


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle) or {}
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取小红书发布任务失败，将使用空任务列表: %s", exc)
        return {}


def _title_weight(text: str) -> int:
    """小红书标题长度：中文及中文/全角标点按 2，其他字符按 1。"""
    return sum(
        2
        if (
            "\u4e00" <= char <= "\u9fff"
            or "\u3000" <= char <= "\u303f"
            or "\uff00" <= char <= "\uffef"
        )
        else 1
        for char in text
    )


class PublishService:
    """管理配置及单 worker 发布队列。"""

    def __init__(
        self,
        *,
        history_service=None,
        project_root: str | os.PathLike[str] | None = None,
        config_path: str | os.PathLike[str] | None = None,
        tasks_path: str | os.PathLike[str] | None = None,
        publisher_dir: str | os.PathLike[str] | None = None,
        runner: Optional[Callable[..., Any]] = None,
        start_worker: bool = True,
    ):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
        self.config_path = Path(config_path or self.project_root / "publish_config.yaml").resolve()
        self.tasks_path = Path(tasks_path or self.project_root / "publish_tasks.json").resolve()
        configured_publisher = os.environ.get("XHS_PUBLISHER_DIR")
        self.publisher_dir = Path(publisher_dir or configured_publisher or self.project_root / "third_party" / "XiaohongshuSkills").resolve()
        self.history_service = history_service
        self.runner = runner or subprocess.run
        self._lock = threading.RLock()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._load_tasks_and_recover()
        if start_worker:
            self._worker = threading.Thread(target=self._worker_loop, name="xhs-publish-worker", daemon=True)
            self._worker.start()

    # ---------- persistence/config ----------
    def _load_tasks_and_recover(self) -> None:
        raw = _read_json(self.tasks_path)
        tasks = raw.get("tasks", []) if isinstance(raw, dict) else []
        if isinstance(tasks, dict):
            tasks = list(tasks.values())
        if not isinstance(tasks, list):
            tasks = []
        changed = False
        for item in tasks:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            task = dict(item)
            if task.get("status") in ACTIVE_STATUSES:
                task["status"] = "unknown"
                task["error"] = "服务重启时发布任务被中断，无法确认浏览器是否已提交。"
                task["updated_at"] = _now()
                changed = True
            self._tasks[str(task["id"])] = task
        if changed or not self.tasks_path.exists():
            self._persist_tasks()

    def _persist_tasks(self) -> None:
        _atomic_write(self.tasks_path, {"tasks": list(self._tasks.values())})

    def get_config(self) -> Dict[str, Any]:
        with self._lock:
            config = dict(DEFAULT_CONFIG)
            config.update(_read_yaml(self.config_path))
            normalized = self._normalize_config(config)
            normalized.update(self._publisher_runtime_info())
            return normalized

    def _publisher_runtime_info(self) -> Dict[str, Any]:
        """返回不写入用户配置文件的发布器运行时信息。"""
        scripts_dir = self.publisher_dir / "scripts"
        return {
            "publisher_dir": str(self.publisher_dir),
            "publisher_available": all(
                (scripts_dir / name).is_file()
                for name in ("publish_pipeline.py", "cdp_publish.py")
            ),
        }

    def update_config(self, incoming: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(incoming, dict):
            raise PublishServiceError("INVALID_REQUEST", "请求参数不完整", "请求体必须是 JSON 对象。", "请提交 JSON 配置。")
        if isinstance(incoming.get("config"), dict):
            incoming = incoming["config"]
        with self._lock:
            config = self.get_config()
            for key in DEFAULT_CONFIG:
                if key in incoming:
                    config[key] = incoming[key]
            config = self._normalize_config(config, validate=True)
            persistable = {key: config[key] for key in DEFAULT_CONFIG}
            _atomic_write(self.config_path, persistable, mode=0o600, yaml_format=True)
            config.update(self._publisher_runtime_info())
            return config

    @staticmethod
    def _normalize_config(config: Dict[str, Any], validate: bool = False) -> Dict[str, Any]:
        result = dict(DEFAULT_CONFIG)
        result.update(config or {})
        account = result.get("account", "")
        port = result.get("port", 9222)
        headless = result.get("headless", False)
        mode = result.get("default_mode", "preview")
        if not isinstance(account, str) or len(account) > 64 or any(ord(c) < 32 or c in "/\\" for c in account):
            if validate:
                raise PublishServiceError("INVALID_REQUEST", "发布配置无效", "account 必须是不含路径分隔符的短字符串。", "请检查账号名称。")
            account = ""
        try:
            port = int(port)
        except (TypeError, ValueError):
            port = 9222
        if not 1 <= port <= 65535:
            if validate:
                raise PublishServiceError("INVALID_REQUEST", "发布配置无效", "port 必须在 1 到 65535 之间。", "请检查 Chrome CDP 端口。")
            port = 9222
        if not isinstance(headless, bool):
            if validate:
                raise PublishServiceError("INVALID_REQUEST", "发布配置无效", "headless 必须是布尔值。", "请检查无头模式设置。")
            headless = bool(headless)
        if mode not in {"preview", "auto"}:
            if validate:
                raise PublishServiceError("INVALID_REQUEST", "发布配置无效", "default_mode 必须为 preview 或 auto。", "请检查默认发布模式。")
            mode = "preview"
        return {"account": account.strip(), "port": port, "headless": headless, "default_mode": mode}

    # ---------- input/file validation ----------
    def _history(self):
        return self.history_service or get_history_service()

    def _ordered_images(self, record_id: str) -> list[str]:
        history = self._history()
        record = history.get_record(record_id, sync_images=True)
        if not record:
            raise PublishServiceError("NOT_FOUND", "历史作品不存在", f"找不到历史记录：{record_id}。", "请刷新历史作品列表后重试.", 404)
        image_info = record.get("images") or {}
        task_id = image_info.get("task_id")
        generated = image_info.get("generated")
        if record.get("status") != "completed":
            raise PublishServiceError("INVALID_REQUEST", "作品尚未完成", "只有已完成的作品可以发布。", "请等待图片和文案全部生成完成。")
        if (record.get("content") or {}).get("status") != "done":
            raise PublishServiceError("INVALID_REQUEST", "作品文案尚未完成", "当前作品文案还没有生成完成。", "请先完成标题、正文和标签生成。")
        if not task_id or not isinstance(generated, list) or not generated:
            raise PublishServiceError("INVALID_REQUEST", "作品图片不完整", "当前作品没有可发布的图片。", "请先完成图片生成后再发布。")
        pages = (record.get("outline") or {}).get("pages")
        if isinstance(pages, list) and pages and len(generated) != len(pages):
            raise PublishServiceError("INVALID_REQUEST", "作品图片不完整", "图片数量与作品页数不一致，存在未生成的页面。", "请补齐全部图片后再发布。")
        history_root = Path(getattr(history, "history_dir", self.project_root / "history")).resolve()
        task_dir = Path(os.path.realpath(history_root / str(task_id)))
        try:
            if os.path.commonpath([str(history_root), str(task_dir)]) != str(history_root) or not task_dir.is_dir():
                raise ValueError
        except ValueError:
            raise PublishServiceError("INVALID_REQUEST", "作品图片路径无效", "图片任务目录不在历史目录内。", "请重新生成该作品图片。")
        ordered: list[str] = []
        for index, item in enumerate(generated):
            if not isinstance(item, str) or not item.strip():
                raise PublishServiceError("INVALID_REQUEST", "作品图片不完整", f"第 {index + 1} 张图片为空。", "请补齐图片后再发布。")
            candidate = Path(os.path.realpath(task_dir / item.strip()))
            try:
                inside = os.path.commonpath([str(task_dir), str(candidate)]) == str(task_dir)
            except ValueError:
                inside = False
            if not inside or not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                raise PublishServiceError("INVALID_REQUEST", "作品图片路径无效", f"第 {index + 1} 张图片不是受支持的历史图片。", "只允许 history/<task_id> 内的 PNG/JPG/JPEG/WEBP 文件。")
            ordered.append(str(candidate))
        return ordered

    @staticmethod
    def validate_content(title: Any, copywriting: Any, tags: Any) -> tuple[str, str, list[str]]:
        if not isinstance(title, str) or not title.strip():
            raise PublishServiceError("INVALID_REQUEST", "发布内容无效", "title 不能为空。", "请填写笔记标题。")
        title = title.strip()
        if _title_weight(title) > 38:
            raise PublishServiceError("INVALID_REQUEST", "发布内容无效", "标题长度超过 38 个计数单位（中文按 2 计）。", "请缩短标题后重试。")
        if not isinstance(copywriting, str) or not copywriting.strip():
            raise PublishServiceError("INVALID_REQUEST", "发布内容无效", "copywriting 不能为空。", "请填写笔记正文。")
        if not isinstance(tags, list) or len(tags) > 10 or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
            raise PublishServiceError("INVALID_REQUEST", "发布内容无效", "tags 必须是最多 10 个非空字符串。", "请检查话题标签。")
        normalized_tags = [tag.strip().lstrip("#").strip() for tag in tags]
        if any(not tag for tag in normalized_tags):
            raise PublishServiceError("INVALID_REQUEST", "发布内容无效", "tags 不能包含空标签。", "请检查话题标签。")
        return title, copywriting.strip(), normalized_tags

    # ---------- task lifecycle ----------
    def _set_status(self, task_id: str, status: str, **changes: Any) -> Dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return {}
            task.update(changes)
            task["status"] = status
            task["updated_at"] = _now()
            self._persist_tasks()
            return dict(task)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def create_publish_task(self, record_id: str, *, title: Any, copywriting: Any, tags: Any, mode: str | None = None, confirm: Any = False) -> Dict[str, Any]:
        if confirm is not True:
            raise PublishServiceError("INVALID_REQUEST", "发布请求未确认", "confirm 必须为 true。", "请确认你已检查标题、正文和图片。")
        title, copywriting, tags = self.validate_content(title, copywriting, tags)
        config = self.get_config()
        mode = mode or config["default_mode"]
        if mode not in {"preview", "auto"}:
            raise PublishServiceError("INVALID_REQUEST", "发布模式无效", "mode 必须为 preview 或 auto。", "请选择预览或自动发布。")
        with self._lock:
            for task in self._tasks.values():
                if task.get("record_id") == record_id and task.get("status") in ACTIVE_STATUSES:
                    raise PublishServiceError("CONFLICT", "作品正在发布", "同一作品已有一个进行中的发布任务。", "请等待当前任务结束后再试。", 409)
            task_id = f"publish_{uuid.uuid4().hex[:12]}"
            task = {
                "id": task_id,
                "record_id": record_id,
                "title": title,
                "copywriting": copywriting,
                "tags": tags,
                "mode": mode,
                "status": "queued",
                "created_at": _now(),
                "updated_at": _now(),
                "note_url": None,
                "error": None,
                "output": "",
            }
            self._tasks[task_id] = task
            self._persist_tasks()
            self._queue.put(task_id)
            return dict(task)

    def confirm_task(self, task_id: str, confirm: Any = True) -> Dict[str, Any]:
        if confirm is not True:
            raise PublishServiceError("INVALID_REQUEST", "确认参数无效", "confirm 必须为 true。", "请确认要提交当前预览内容。")
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise PublishServiceError("NOT_FOUND", "发布任务不存在", f"找不到发布任务：{task_id}。", "请刷新任务列表后重试。", 404)
            if task.get("status") != "ready_for_review":
                raise PublishServiceError("CONFLICT", "任务当前不可确认", "只有 ready_for_review 状态的预览任务可以确认发布。", "请等待预填完成后再确认。", 409)
            task["status"] = "submitting"
            task["updated_at"] = _now()
            task["error"] = None
            self._persist_tasks()
            self._queue.put(task_id)
            return dict(task)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                task_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if task_id is None:
                self._queue.task_done()
                break
            try:
                task = self.get_task(task_id)
                if task and task.get("status") == "queued":
                    self._run_prepare(task_id)
                elif task and task.get("status") == "submitting":
                    self._run_confirm(task_id)
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                logger.exception("小红书发布任务异常: %s", task_id)
                self._set_status(task_id, "failed", error=str(exc))
            finally:
                self._queue.task_done()

    def _command_options(self, config: Dict[str, Any], *, allow_headless: bool = True) -> list[str]:
        options = ["--host", "127.0.0.1", "--port", str(config["port"])]
        if config.get("account"):
            options.extend(["--account", config["account"]])
        if allow_headless and config.get("headless"):
            options.append("--headless")
        return options

    def _require_script(self, script_name: str) -> Path:
        script = self.publisher_dir / "scripts" / script_name
        if not script.is_file():
            raise PublishServiceError(
                "PUBLISHER_UNAVAILABLE",
                "小红书发布组件不可用",
                f"未找到发布器脚本：{script}。",
                "请安装 third_party/XiaohongshuSkills，或设置 XHS_PUBLISHER_DIR 指向该目录。",
                503,
            )
        return script

    def _run_command(self, args: list[str], timeout: float = 300) -> tuple[int, str, str]:
        try:
            result = self.runner(args, shell=False, capture_output=True, text=True, timeout=timeout, cwd=str(self.publisher_dir))
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            raise TimeoutError(f"发布命令超时：{stdout}\n{stderr}")
        return int(getattr(result, "returncode", 0)), str(getattr(result, "stdout", "") or ""), str(getattr(result, "stderr", "") or "")

    @staticmethod
    def _combine_output(stdout: str, stderr: str) -> str:
        return (stdout + ("\n" + stderr if stderr else "")).strip()[-8000:]

    @staticmethod
    def _extract_note_url(output: str) -> Optional[str]:
        match = NOTE_URL_RE.search(output or "")
        return match.group(0) if match else None

    def _check_login(self, config: Dict[str, Any]) -> tuple[bool, int, str]:
        script = self._require_script("cdp_publish.py")
        args = [sys.executable, str(script), *self._command_options(config), "check-login"]
        rc, stdout, stderr = self._run_command(args, timeout=60)
        output = self._combine_output(stdout, stderr)
        return rc == 0 and "NOT_LOGGED_IN" not in output, rc, output

    def auth_check(self) -> Dict[str, Any]:
        config = self.get_config()
        try:
            logged_in, rc, output = self._check_login(config)
        except PublishServiceError as exc:
            return {
                "success": False,
                "logged_in": False,
                "authenticated": False,
                "message": exc.app_error.to_message(),
                "error": exc.app_error.to_dict(),
                "output": "",
                "status": exc.app_error.status,
            }
        except Exception as exc:
            return {"success": False, "logged_in": False, "authenticated": False, "message": str(exc), "output": "", "status": 502}
        success = rc in {0, 1}
        return {
            "success": success,
            "logged_in": logged_in,
            "authenticated": logged_in,
            "message": ("已登录小红书" if logged_in else "尚未登录小红书") if success else "检查小红书登录状态失败",
            "output": output,
            "returncode": rc,
            **({"status": 502} if not success else {}),
        }

    def auth_login(self) -> Dict[str, Any]:
        config = self.get_config()
        try:
            script = self._require_script("cdp_publish.py")
            options = ["--host", "127.0.0.1", "--port", str(config["port"])]
            if config.get("account"):
                options.extend(["--account", config["account"]])
            args = [sys.executable, str(script), *options, "login"]
            rc, stdout, stderr = self._run_command(args, timeout=120)
        except PublishServiceError as exc:
            return {
                "success": False,
                "login_started": False,
                "message": exc.app_error.to_message(),
                "error": exc.app_error.to_dict(),
                "output": "",
                "status": exc.app_error.status,
            }
        except Exception as exc:
            return {"success": False, "login_started": False, "message": str(exc), "output": "", "status": 502}
        output = self._combine_output(stdout, stderr)
        return {
            "success": rc == 0,
            "login_started": rc == 0 or "LOGIN_READY" in output,
            "message": "已打开小红书登录页面，请扫码登录" if rc == 0 else "打开登录页面失败",
            "output": output,
            "returncode": rc,
        }

    def _run_prepare(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        self._set_status(task_id, "validating")
        try:
            images = self._ordered_images(task["record_id"])
        except PublishServiceError as exc:
            self._set_status(task_id, "failed", error=exc.app_error.to_dict())
            return
        config = self.get_config()
        execution_config = dict(config)
        if task["mode"] == "preview":
            execution_config["headless"] = False
        try:
            logged_in, rc, output = self._check_login(execution_config)
        except Exception as exc:
            self._set_status(task_id, "failed", error=str(exc))
            return
        if not logged_in:
            self._set_status(task_id, "auth_required", output=output, error="请先登录小红书账号。")
            return
        self._set_status(task_id, "opening_browser")
        self._set_status(task_id, "uploading")
        if task["mode"] == "auto":
            self._set_status(task_id, "submitting")
        else:
            self._set_status(task_id, "filling")
        content = task["copywriting"]
        if task.get("tags"):
            content = content.rstrip() + "\n\n" + " ".join(f"#{tag}" for tag in task["tags"])
        try:
            script = self._require_script("publish_pipeline.py")
        except PublishServiceError as exc:
            self._set_status(task_id, "failed", error=exc.app_error.to_dict())
            return
        # 预览的目的就是让用户在可见浏览器中检查内容；即使系统默认配置为
        # headless，也不能把预览内容放到用户看不到的窗口中。
        args = [sys.executable, str(script), *self._command_options(execution_config, allow_headless=task["mode"] == "auto")]
        if task["mode"] == "preview":
            args.append("--preview")
        args.extend(["--title", task["title"], "--content", content, "--images", *images])
        try:
            rc, stdout, stderr = self._run_command(args)
        except TimeoutError as exc:
            self._set_status(task_id, "unknown", error=str(exc))
            return
        output = self._combine_output(stdout, stderr)
        url = self._extract_note_url(output)
        if rc == 0 and task["mode"] == "preview" and "FILL_STATUS: READY_TO_PUBLISH" in output:
            self._set_status(task_id, "ready_for_review", output=output)
        elif rc == 0 and task["mode"] == "auto" and "PUBLISH_STATUS: PUBLISHED" in output:
            self._set_status(task_id, "published" if url else "submitted", output=output, note_url=url)
        elif task["mode"] == "auto" and "PUBLISH_STATUS: PUBLISHED" in output:
            self._set_status(task_id, "submitted" if not url else "published", output=output, note_url=url)
        elif "NOT_LOGGED_IN" in output:
            self._set_status(task_id, "auth_required", output=output, error="请先登录小红书账号。")
        elif task["mode"] == "auto" and (
            "Step 5: Clicking publish button" in output or "Publish button clicked" in output
        ):
            self._set_status(task_id, "unknown", output=output, error=stderr.strip() or "发布按钮已触发，但无法确认提交结果。")
        else:
            self._set_status(task_id, "failed", output=output, error=stderr.strip() or "发布器执行失败。")

    def _run_confirm(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        config = self.get_config()
        try:
            script = self._require_script("cdp_publish.py")
        except PublishServiceError as exc:
            self._set_status(task_id, "failed", error=exc.app_error.to_dict())
            return
        args = [sys.executable, str(script), *self._command_options(config), "click-publish"]
        try:
            rc, stdout, stderr = self._run_command(args)
        except TimeoutError as exc:
            self._set_status(task_id, "unknown", error=str(exc))
            return
        output = self._combine_output(stdout, stderr)
        url = self._extract_note_url(output)
        if "PUBLISH_STATUS: PUBLISHED" in output and rc == 0:
            self._set_status(task_id, "published" if url else "submitted", output=output, note_url=url)
        elif "PUBLISH_STATUS: PUBLISHED" in output:
            self._set_status(task_id, "submitted" if not url else "published", output=output, note_url=url)
        else:
            self._set_status(task_id, "unknown" if rc != 0 else "failed", output=output, error=stderr.strip() or "无法确认发布结果。")

    def close(self) -> None:
        self._stop_event.set()
        self._queue.put(None)
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2)


_service_instance: PublishService | None = None
_service_lock = threading.Lock()


def get_publish_service() -> PublishService:
    global _service_instance
    with _service_lock:
        if _service_instance is None:
            _service_instance = PublishService()
        return _service_instance


def reset_publish_service() -> None:
    """测试和开发重载使用：停止当前后台线程并清空单例。"""
    global _service_instance
    with _service_lock:
        if _service_instance is not None:
            _service_instance.close()
        _service_instance = None
