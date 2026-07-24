"""历史图片列表合并与状态计算。"""
import os
from typing import Dict, List, Optional


class HistoryImageMerger:
    """处理 index-aligned images.generated。"""

    @staticmethod
    def has_images(generated: Optional[List[str]]) -> bool:
        return any(bool(item) for item in (generated or []))

    @staticmethod
    def merge_generated(
        existing: Optional[List[str]],
        page_index: int,
        filename: str,
        total_count: Optional[int] = None,
    ) -> List[str]:
        generated = [item or "" for item in (existing or [])]
        target_len = max(len(generated), page_index + 1, total_count or 0)
        while len(generated) < target_len:
            generated.append("")
        generated[page_index] = filename
        return generated

    @staticmethod
    def merge_many(
        existing: Optional[List[str]],
        files_by_index: Dict[int, str],
        total_count: Optional[int] = None,
    ) -> List[str]:
        generated = [item or "" for item in (existing or [])]
        target_len = max(len(generated), total_count or 0)
        if files_by_index:
            target_len = max(target_len, max(files_by_index.keys()) + 1)
        while len(generated) < target_len:
            generated.append("")
        for index, filename in files_by_index.items():
            generated[index] = filename
        return generated

    @staticmethod
    def compute_status(generated: Optional[List[str]], total_count: int) -> str:
        completed = sum(1 for item in (generated or []) if item)
        if completed == 0:
            return "draft"
        if total_count > 0 and completed >= total_count:
            return "completed"
        return "partial"

    @staticmethod
    def first_image(generated: Optional[List[str]]) -> Optional[str]:
        for item in generated or []:
            if item:
                return item
        return None

    @staticmethod
    def files_by_index(history_dir: str, task_id: str) -> Dict[int, str]:
        task_dir = os.path.join(history_dir, task_id)
        if not os.path.isdir(task_dir):
            return {}

        files: Dict[int, str] = {}
        for filename in os.listdir(task_dir):
            if filename.startswith("thumb_"):
                continue
            if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            try:
                index = int(filename.rsplit(".", 1)[0])
            except ValueError:
                continue
            files[index] = filename
        return dict(sorted(files.items()))
