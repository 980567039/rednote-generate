"""图片上游响应解析。"""
import base64
import logging
import re
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)


class ImageResponseExtractor:
    """把不同兼容接口响应归一成图片二进制。"""

    def __init__(self, download_image: Callable[[str], bytes]):
        self.download_image = download_image

    def extract_from_images_response(self, result: Dict[str, Any]) -> bytes:
        data = result.get("data")
        if not isinstance(data, list) or not data:
            raise ValueError(
                "图片接口未返回 data 图片数据。\n"
                f"响应内容: {str(result)[:500]}"
            )

        item = data[0]
        if not isinstance(item, dict):
            raise ValueError(f"图片接口 data 格式异常: {str(item)[:300]}")

        if item.get("b64_json"):
            image_data = self._decode_base64_image(item["b64_json"])
            logger.info(f"图片响应解析成功: b64_json, {len(image_data)} bytes")
            return image_data

        if item.get("url"):
            logger.info("图片响应返回 URL，开始下载图片")
            return self.download_image(item["url"])

        raise ValueError(
            "无法从图片接口响应中提取图片数据：未找到 b64_json 或 url。\n"
            f"响应片段: {str(item)[:500]}"
        )

    def extract_from_chat_response(self, result: Dict[str, Any]) -> bytes:
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError(
                "Chat 图片接口未返回 choices 数据。\n"
                f"响应内容: {str(result)[:500]}"
            )

        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str):
            raise ValueError(
                "Chat 图片接口响应 content 格式异常。\n"
                f"响应内容: {str(result)[:500]}"
            )

        data_urls = re.findall(r"!\[.*?\]\((data:image/[^;]+;base64,[^\s\)]+)\)", content)
        if data_urls:
            logger.info("从 Markdown 中提取到 Base64 图片数据")
            return self._decode_base64_image(data_urls[0])

        urls = re.findall(r"!\[.*?\]\((https?://[^\s\)]+)\)", content)
        if urls:
            logger.info(f"从 Markdown 中提取到 {len(urls)} 个图片 URL")
            return self.download_image(urls[0])

        stripped = content.strip()
        if stripped.startswith("data:image"):
            logger.info("检测到纯 Base64 图片数据")
            return self._decode_base64_image(stripped)

        if stripped.startswith("http://") or stripped.startswith("https://"):
            logger.info("检测到纯图片 URL")
            return self.download_image(stripped)

        raise ValueError(
            "无法从 Chat 图片接口响应中提取图片数据。\n"
            f"响应内容: {content[:500]}"
        )

    @staticmethod
    def _decode_base64_image(value: str) -> bytes:
        if value.startswith("data:"):
            value = value.split(",", 1)[1]
        return base64.b64decode(value)
