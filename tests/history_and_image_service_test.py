from pathlib import Path
import threading

from backend.services.history import HistoryService
from backend.services.image import ActiveGenerationError, ImageService
from backend.services.image_rate_limiter import ImageRateLimiter


def make_history_service(tmp_path: Path) -> HistoryService:
    service = HistoryService.__new__(HistoryService)
    service.history_dir = str(tmp_path)
    service.index_file = str(tmp_path / "index.json")
    service._init_index()
    return service


def test_history_update_protects_images_and_completed_status(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("topic", {
        "raw": "raw",
        "pages": [
            {"index": 0, "type": "cover", "content": "cover"},
            {"index": 1, "type": "content", "content": "content"},
        ],
    })

    assert service.update_record(
        record_id,
        images={"task_id": "task_1", "generated": ["0.png", "1.png"]},
        status="completed",
        thumbnail="0.png",
    )
    assert service.update_record(
        record_id,
        images={"task_id": "task_1", "generated": []},
        status="generating",
    )

    record = service.get_record(record_id)
    assert record["images"]["generated"] == ["0.png", "1.png"]
    assert record["status"] == "completed"


def test_merge_generated_image_is_index_aligned(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("topic", {
        "raw": "raw",
        "pages": [
            {"index": 0, "type": "cover", "content": "cover"},
            {"index": 1, "type": "content", "content": "content"},
            {"index": 2, "type": "summary", "content": "summary"},
        ],
    })

    service.merge_generated_image(record_id, "task_1", 2, "2.png")
    record = service.get_record(record_id)

    assert record["images"]["generated"] == ["", "", "2.png"]
    assert record["status"] == "partial"
    assert record["thumbnail"] == "2.png"


def test_restart_recovers_generating_record_without_resubmitting(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("topic", {
        "raw": "raw",
        "pages": [
            {"index": 0, "type": "cover", "content": "cover"},
            {"index": 1, "type": "content", "content": "content"},
        ],
    })
    service.update_record(
        record_id,
        images={"task_id": "task_interrupted", "generated": []},
        status="generating",
    )
    task_dir = tmp_path / "task_interrupted"
    task_dir.mkdir()
    (task_dir / "0.png").write_bytes(b"already-generated")

    service._recover_interrupted_generations()

    record = service.get_record(record_id)
    assert record["status"] == "partial"
    assert record["images"]["generated"] == ["0.png", ""]


def test_default_image_prompts_prioritize_visuals_and_limit_tutorial_text():
    prompt_dir = Path(__file__).parent.parent / "backend" / "prompts"
    full_prompt = (prompt_dir / "image_prompt.txt").read_text(encoding="utf-8")
    short_prompt = (prompt_dir / "image_prompt_short.txt").read_text(encoding="utf-8")

    for prompt in (full_prompt, short_prompt):
        rendered = prompt.format(
            page_content="第一步：准备器具。水温 92–96℃。",
            page_type="content",
            user_topic="咖啡教程",
        )
        assert "逐字" in rendered
        assert "画面" in rendered
        assert "≤10" in rendered or "10 个汉字" in rendered


def test_outline_prompt_allows_explicit_no_cover_structure():
    prompt_path = Path(__file__).parent.parent / "backend" / "prompts" / "outline_prompt.txt"
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "明确要求“不生成封面”" in prompt
    assert "严格按其页数和页面结构执行" in prompt


def test_cached_generation_events_do_not_call_generator(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("topic", {
        "raw": "raw",
        "pages": [
            {"index": 0, "type": "cover", "content": "cover"},
            {"index": 1, "type": "content", "content": "content"},
        ],
    })
    service.update_record(
        record_id,
        images={"task_id": "task_1", "generated": ["0.png", ""]},
        status="partial",
    )

    image_service = ImageService.__new__(ImageService)
    image_service.history_service = service

    events = image_service.get_cached_generation_events(record_id, [
        {"index": 0, "type": "cover", "content": "cover"},
        {"index": 1, "type": "content", "content": "content"},
    ])

    assert [event["event"] for event in events] == ["complete", "error", "finish"]
    assert events[0]["data"]["cached"] is True
    assert events[-1]["data"]["completed"] == 1
    assert events[-1]["data"]["failed_indices"] == [1]


class FakeGenerator:
    def generate_image(self, **kwargs):
        return b"image-bytes"


def test_single_image_generation_writes_history_immediately(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("topic", {
        "raw": "raw",
        "pages": [{"index": 0, "type": "cover", "content": "cover"}],
    })

    image_service = ImageService.__new__(ImageService)
    image_service.generator = FakeGenerator()
    image_service.provider_config = {"type": "image_api", "model": "gpt-image-2"}
    image_service.use_short_prompt = False
    image_service.prompt_template = "{page_content}"
    image_service.prompt_template_short = ""
    task_dir = str(tmp_path / "task_1")
    Path(task_dir).mkdir()
    image_service.rate_limiter = ImageRateLimiter(max_concurrent=1, interval_seconds=0)
    image_service.history_service = service

    result = image_service._generate_single_image(
        {"index": 0, "type": "cover", "content": "cover"},
        "task_1",
        record_id=record_id,
        total_count=1,
        task_dir=task_dir,
    )

    assert result == (0, True, "0.png", None)
    record = service.get_record(record_id)
    assert record["images"]["generated"] == ["0.png"]
    assert record["status"] == "completed"


def test_retry_failed_images_creates_task_dir_and_merges_by_index(tmp_path):
    service = make_history_service(tmp_path)
    record_id = service.create_record("topic", {
        "raw": "raw",
        "pages": [
            {"index": 0, "type": "cover", "content": "cover"},
            {"index": 1, "type": "content", "content": "content"},
            {"index": 2, "type": "summary", "content": "summary"},
        ],
    })

    image_service = ImageService.__new__(ImageService)
    image_service.generator = FakeGenerator()
    image_service.provider_config = {"type": "image_api", "model": "gpt-image-2"}
    image_service.use_short_prompt = False
    image_service.prompt_template = "{page_content}"
    image_service.prompt_template_short = ""
    image_service.history_root_dir = str(tmp_path)
    image_service.rate_limiter = ImageRateLimiter(max_concurrent=1, interval_seconds=0)
    image_service.history_service = service
    image_service.worker_count = 1
    image_service._task_states = {}

    events = list(image_service.retry_failed_images(
        "task_1",
        [
            {"index": 2, "type": "summary", "content": "summary"},
            {"index": 1, "type": "content", "content": "content"},
        ],
        record_id=record_id,
    ))

    assert [event["event"] for event in events] == [
        "retry_start",
        "complete",
        "complete",
        "retry_finish",
    ]
    assert (tmp_path / "task_1" / "1.png").exists()
    assert (tmp_path / "task_1" / "2.png").exists()

    record = service.get_record(record_id)
    assert record["images"]["generated"] == ["", "1.png", "2.png"]
    assert record["status"] == "partial"


def make_image_service(tmp_path: Path, history_service: HistoryService, generator=None) -> ImageService:
    service = ImageService.__new__(ImageService)
    service.generator = generator or FakeGenerator()
    service.provider_config = {"type": "image_api", "model": "gpt-image-2"}
    service.use_short_prompt = False
    service.prompt_template = "{page_content}"
    service.prompt_template_short = ""
    service.history_root_dir = str(tmp_path)
    service.rate_limiter = ImageRateLimiter(max_concurrent=2, interval_seconds=0)
    service.history_service = history_service
    service.worker_count = 1
    service._task_states = {}
    service._task_lock = threading.RLock()
    return service


def test_prepare_generation_binds_record_and_rejects_duplicate(tmp_path):
    history = make_history_service(tmp_path)
    pages = [{"index": 0, "type": "cover", "content": "cover"}]
    record_id = history.create_record("topic", {"pages": pages})
    service = make_image_service(tmp_path, history)

    reservation = service.prepare_generation(pages, record_id=record_id)
    state = service.get_task_state(reservation["task_id"])
    record = history.get_record(record_id)

    assert state["status"] == "queued"
    assert state["phase"] == "accepted"
    assert state["record_id"] == record_id
    assert state["created_at"]
    assert record["status"] == "generating"
    assert record["images"]["task_id"] == reservation["task_id"]

    try:
        service.prepare_generation(pages, record_id=record_id)
    except ActiveGenerationError as exc:
        assert exc.task_id == reservation["task_id"]
        assert exc.state["status"] == "queued"
    else:
        raise AssertionError("重复活动任务应被拒绝")


def test_all_failed_generation_finishes_task_and_history_as_error(tmp_path):
    class FailedGenerator:
        def generate_image(self, **kwargs):
            raise RuntimeError("render failed")

    history = make_history_service(tmp_path)
    pages = [{"index": 0, "type": "cover", "content": "cover"}]
    record_id = history.create_record("topic", {"pages": pages})
    service = make_image_service(tmp_path, history, FailedGenerator())
    reservation = service.prepare_generation(pages, record_id=record_id)

    events = list(service.generate_images(
        pages,
        task_id=reservation["task_id"],
        record_id=record_id,
        prepared=True,
    ))

    assert events[0]["event"] == "accepted"
    assert events[0]["data"]["task_id"] == reservation["task_id"]
    assert events[-1]["event"] == "finish"
    assert events[-1]["data"]["status"] == "failed"
    state = service.get_task_state(reservation["task_id"])
    assert state["status"] == "failed"
    assert state["phase"] == "finished"
    assert state["finished_at"]
    assert history.get_record(record_id)["status"] == "error"


def test_systemic_cover_error_breaks_remaining_pages(tmp_path):
    class NetworkFailedGenerator:
        def __init__(self):
            self.calls = 0

        def generate_image(self, **kwargs):
            self.calls += 1
            raise RuntimeError("Image API 连接失败: TLS connection reset")

    pages = [
        {"index": 0, "type": "cover", "content": "cover"},
        {"index": 1, "type": "content", "content": "one"},
        {"index": 2, "type": "content", "content": "two"},
    ]
    history = make_history_service(tmp_path)
    record_id = history.create_record("topic", {"pages": pages})
    generator = NetworkFailedGenerator()
    service = make_image_service(tmp_path, history, generator)

    events = list(service.generate_images(pages, record_id=record_id))

    assert generator.calls == 1
    breaker_errors = [
        event for event in events
        if event["event"] == "error" and event["data"].get("phase") == "circuit_breaker"
    ]
    assert [event["data"]["index"] for event in breaker_errors] == [1, 2]
    assert events[-1]["data"]["failed_indices"] == [0, 1, 2]


def test_explicit_task_dirs_prevent_cross_task_writes(tmp_path):
    history = make_history_service(tmp_path)
    service = make_image_service(tmp_path, history)
    task_a = tmp_path / "task_a"
    task_b = tmp_path / "task_b"
    task_a.mkdir()
    task_b.mkdir()

    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(service._generate_single_image(
                {"index": 0, "type": "cover", "content": "a"},
                "task_a",
                task_dir=str(task_a),
            ))
        ),
        threading.Thread(
            target=lambda: results.append(service._generate_single_image(
                {"index": 1, "type": "content", "content": "b"},
                "task_b",
                task_dir=str(task_b),
            ))
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert (task_a / "0.png").exists()
    assert not (task_a / "1.png").exists()
    assert (task_b / "1.png").exists()
    assert not (task_b / "0.png").exists()
