import json
import os
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.publish import PublishService, PublishServiceError


class FakeHistoryService:
    def __init__(self, history_dir: Path, record: dict | None):
        self.history_dir = str(history_dir)
        self.record = record

    def get_record(self, record_id, sync_images=False):
        if self.record and self.record.get("id") == record_id:
            return self.record
        return None


def make_record(task_id="task_1", generated=None):
    generated = ["0.png", "1.jpg"] if generated is None else generated
    return {
        "id": "record_1",
        "status": "completed",
        "content": {"status": "done"},
        "outline": {"pages": [{"index": index} for index in range(len(generated))]},
        "images": {"task_id": task_id, "generated": generated},
    }


def make_service(tmp_path, *, runner=None, record=None, start_worker=False):
    history_dir = tmp_path / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    task_dir = history_dir / "task_1"
    task_dir.mkdir(exist_ok=True)
    (task_dir / "0.png").write_bytes(b"png")
    (task_dir / "1.jpg").write_bytes(b"jpg")
    publisher_dir = tmp_path / "publisher"
    (publisher_dir / "scripts").mkdir(parents=True)
    (publisher_dir / "scripts" / "publish_pipeline.py").touch()
    (publisher_dir / "scripts" / "cdp_publish.py").touch()
    return PublishService(
        history_service=FakeHistoryService(history_dir, record or make_record()),
        project_root=tmp_path,
        config_path=tmp_path / "publish_config.yaml",
        tasks_path=tmp_path / "publish_tasks.json",
        publisher_dir=publisher_dir,
        runner=runner,
        start_worker=start_worker,
    )


def wait_for_status(service, task_id, expected, timeout=2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = service.get_task(task_id)
        if task and task["status"] in expected:
            return task
        time.sleep(0.01)
    raise AssertionError(f"task did not reach {expected}: {service.get_task(task_id)}")


def test_config_is_atomic_private_and_validated(tmp_path):
    service = make_service(tmp_path)
    config = service.update_config({"account": "creator", "port": 9333, "headless": True, "default_mode": "auto"})

    assert config["account"] == "creator"
    assert config["port"] == 9333
    assert config["headless"] is True
    assert config["default_mode"] == "auto"
    assert config["publisher_available"] is True
    assert config["publisher_dir"] == str((tmp_path / "publisher").resolve())
    assert stat.S_IMODE(os.stat(tmp_path / "publish_config.yaml").st_mode) == 0o600
    assert not list(tmp_path.glob(".publish_config.yaml.*"))

    with pytest.raises(PublishServiceError) as exc_info:
        service.update_config({"port": 70000})
    assert exc_info.value.app_error.status == 400


@pytest.mark.parametrize(
    "title,copywriting,tags",
    [
        ("这是一个非常非常非常非常非常非常非常非常非常长的标题", "正文", []),
        ("！" * 20, "正文", []),
        ("正常标题", "", []),
        ("正常标题", "正文", [str(index) for index in range(11)]),
    ],
)
def test_publish_content_validation(title, copywriting, tags):
    with pytest.raises(PublishServiceError):
        PublishService.validate_content(title, copywriting, tags)


def test_ordered_images_reject_empty_slot_and_path_escape(tmp_path):
    empty = make_service(tmp_path / "empty", record=make_record(generated=["0.png", ""]))
    with pytest.raises(PublishServiceError, match="第 2 张图片为空"):
        empty._ordered_images("record_1")

    escaped_root = tmp_path / "escaped"
    escaped = make_service(escaped_root, record=make_record(generated=["0.png", "../../outside.png"]))
    (escaped_root / "outside.png").write_bytes(b"outside")
    with pytest.raises(PublishServiceError, match="第 2 张图片不是受支持"):
        escaped._ordered_images("record_1")


def test_ordered_images_reject_unsupported_extension_and_missing_page(tmp_path):
    unsupported_root = tmp_path / "unsupported"
    unsupported = make_service(unsupported_root, record=make_record(generated=["0.png", "1.gif"]))
    (unsupported_root / "history" / "task_1" / "1.gif").write_bytes(b"gif")
    with pytest.raises(PublishServiceError, match="受支持"):
        unsupported._ordered_images("record_1")

    missing_record = make_record(generated=["0.png"])
    missing_record["outline"]["pages"].append({"index": 1})
    missing = make_service(tmp_path / "missing", record=missing_record)
    with pytest.raises(PublishServiceError, match="图片数量与作品页数不一致"):
        missing._ordered_images("record_1")


def test_ordered_images_require_completed_images_and_content(tmp_path):
    generating_record = make_record()
    generating_record["status"] = "generating"
    generating = make_service(tmp_path / "generating", record=generating_record)
    with pytest.raises(PublishServiceError, match="只有已完成的作品"):
        generating._ordered_images("record_1")

    idle_content_record = make_record()
    idle_content_record["content"]["status"] = "idle"
    idle_content = make_service(tmp_path / "idle", record=idle_content_record)
    with pytest.raises(PublishServiceError, match="文案还没有生成完成"):
        idle_content._ordered_images("record_1")


def test_preview_task_uses_current_python_safe_args_and_preview_flag(tmp_path):
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        if args[-1] == "check-login":
            return SimpleNamespace(returncode=0, stdout="Login confirmed", stderr="")
        return SimpleNamespace(returncode=0, stdout="FILL_STATUS: READY_TO_PUBLISH", stderr="")

    service = make_service(tmp_path, runner=runner, start_worker=True)
    try:
        service.update_config({"headless": True})
        task = service.create_publish_task(
            "record_1", title="一篇测试笔记", copywriting="正文内容", tags=["教程", "AI"], mode="preview", confirm=True
        )
        done = wait_for_status(service, task["id"], {"ready_for_review", "failed"})
        assert done["status"] == "ready_for_review"
        assert len(calls) == 2
        pipeline_args, pipeline_kwargs = calls[1]
        assert pipeline_args[0] == sys.executable
        assert pipeline_args[1].endswith("scripts/publish_pipeline.py")
        assert "--preview" in pipeline_args
        assert "--headless" not in pipeline_args
        assert pipeline_args[pipeline_args.index("--images") + 1 :] == [
            str((tmp_path / "history" / "task_1" / "0.png").resolve()),
            str((tmp_path / "history" / "task_1" / "1.jpg").resolve()),
        ]
        assert pipeline_args[pipeline_args.index("--content") + 1].endswith("#教程 #AI")
        assert pipeline_kwargs["shell"] is False
    finally:
        service.close()


def test_auto_task_without_note_url_is_only_submitted(tmp_path):
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        if args[-1] == "check-login":
            return SimpleNamespace(returncode=0, stdout="Login confirmed", stderr="")
        return SimpleNamespace(returncode=0, stdout="FILL_STATUS: READY_TO_PUBLISH\nPUBLISH_STATUS: PUBLISHED", stderr="")

    service = make_service(tmp_path, runner=runner, start_worker=True)
    try:
        service.update_config({"headless": True})
        task = service.create_publish_task(
            "record_1", title="自动发布测试", copywriting="正文内容", tags=[], mode="auto", confirm=True
        )
        done = wait_for_status(service, task["id"], {"published", "submitted", "failed"})
        assert done["status"] == "submitted"
        assert done["note_url"] is None
        assert "--preview" not in calls[1]
        assert "--headless" in calls[1]
    finally:
        service.close()


def test_auto_task_with_note_url_is_published(tmp_path):
    def runner(args, **kwargs):
        if args[-1] == "check-login":
            return SimpleNamespace(returncode=0, stdout="Login confirmed", stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="PUBLISH_STATUS: PUBLISHED\nNote published at: https://www.xiaohongshu.com/explore/abcdef123456",
            stderr="",
        )

    service = make_service(tmp_path, runner=runner, start_worker=True)
    try:
        task = service.create_publish_task(
            "record_1", title="发布链接测试", copywriting="正文内容", tags=[], mode="auto", confirm=True
        )
        done = wait_for_status(service, task["id"], {"published", "submitted", "failed"})
        assert done["status"] == "published"
        assert done["note_url"] == "https://www.xiaohongshu.com/explore/abcdef123456"
    finally:
        service.close()


def test_login_required_and_single_active_task(tmp_path):
    def runner(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="NOT_LOGGED_IN", stderr="")

    service = make_service(tmp_path, runner=runner, start_worker=True)
    try:
        task = service.create_publish_task(
            "record_1", title="登录测试", copywriting="正文内容", tags=[], mode="preview", confirm=True
        )
        done = wait_for_status(service, task["id"], {"auth_required"})
        assert done["status"] == "auth_required"

        # auth_required 已经收敛，可以在登录后重新发起；queued/ready_for_review 则会冲突。
        second = service.create_publish_task(
            "record_1", title="再次发布", copywriting="正文内容", tags=[], mode="preview", confirm=True
        )
        with pytest.raises(PublishServiceError) as exc_info:
            service.create_publish_task(
                "record_1", title="并发发布", copywriting="正文内容", tags=[], mode="preview", confirm=True
            )
        assert exc_info.value.app_error.status == 409
        assert second["status"] == "queued"
    finally:
        service.close()


def test_interrupted_task_is_recovered_as_unknown(tmp_path):
    tasks_path = tmp_path / "publish_tasks.json"
    tasks_path.write_text(json.dumps({"tasks": [{"id": "publish_old", "record_id": "record_1", "status": "filling"}]}), encoding="utf-8")
    service = make_service(tmp_path, start_worker=False)

    recovered = service.get_task("publish_old")
    assert recovered["status"] == "unknown"
    saved = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert saved["tasks"][0]["status"] == "unknown"


def test_unavailable_publisher_is_reported_without_subprocess(tmp_path):
    called = False

    def runner(args, **kwargs):
        nonlocal called
        called = True

    service = make_service(tmp_path, runner=runner)
    (tmp_path / "publisher" / "scripts" / "cdp_publish.py").unlink()

    result = service.auth_check()
    assert result["success"] is False
    assert result["error"]["code"] == "PUBLISHER_UNAVAILABLE"
    assert result["status"] == 503
    assert called is False

    login_result = service.auth_login()
    assert login_result["success"] is False
    assert login_result["error"]["code"] == "PUBLISHER_UNAVAILABLE"
    assert login_result["status"] == 503


def test_preview_confirmation_click_without_url_is_submitted(tmp_path):
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="PUBLISH_STATUS: PUBLISHED", stderr="")

    service = make_service(tmp_path, runner=runner, start_worker=True)
    try:
        task = service.create_publish_task(
            "record_1", title="确认发布测试", copywriting="正文内容", tags=[], mode="preview", confirm=True
        )
        service._set_status(task["id"], "ready_for_review")
        confirmed = service.confirm_task(task["id"], confirm=True)
        assert confirmed["status"] == "submitting"
        done = wait_for_status(service, task["id"], {"submitted", "published", "unknown"})
        assert done["status"] == "submitted"
        assert calls[-1][-1] == "click-publish"
    finally:
        service.close()
