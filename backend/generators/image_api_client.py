"""OpenAI-compatible 图片接口 HTTP 客户端。"""
import logging
import time
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Optional

import requests

from .image_provider_policy import ImageProviderPolicy
from .image_response_extractor import ImageResponseExtractor

logger = logging.getLogger(__name__)


class ImageApiClient:
    """负责请求兼容图片上游、退避重试和响应解析。"""

    def __init__(
        self,
        policy: ImageProviderPolicy,
        session: Optional[requests.Session] = None,
        timeout: int = 300,
    ):
        self.policy = policy
        self.session = session or requests.Session()
        self.timeout = timeout
        self.extractor = ImageResponseExtractor(self.download_image)

    def generate_via_images(self, payload: Dict[str, Any]) -> bytes:
        result = self._post_json(payload, label="Image API")
        return self.extractor.extract_from_images_response(result)

    def generate_via_chat(self, payload: Dict[str, Any]) -> bytes:
        result = self._post_json(payload, label="Chat API")
        return self.extractor.extract_from_chat_response(result)

    def download_image(self, url: str) -> bytes:
        logger.info(f"下载图片: {url[:100]}...")
        try:
            response = self.session.get(url, timeout=60)
        except requests.exceptions.Timeout as exc:
            raise Exception("下载图片超时，请重试") from exc
        except requests.RequestException as exc:
            raise Exception(f"下载图片失败: {str(exc)}") from exc

        if response.status_code != 200:
            raise Exception(f"下载图片失败: HTTP {response.status_code}")

        logger.info(f"图片下载成功: {len(response.content)} bytes")
        return response.content

    def _post_json(self, payload: Dict[str, Any], label: str) -> Dict[str, Any]:
        url = f"{self.policy.base_url}{self.policy.endpoint_type}"
        request_payload = dict(payload)
        if self.policy.response_format and "response_format" not in request_payload:
            request_payload["response_format"] = self.policy.response_format

        downgraded_response_format = False
        network_attempt = 0
        server_attempt = 0

        while True:
            try:
                logger.debug(f"{label} 请求: {url}")
                response = self.session.post(
                    url,
                    headers=self._headers(),
                    json=request_payload,
                    timeout=self.timeout,
                )
            except (
                requests.exceptions.SSLError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as exc:
                if network_attempt >= self.policy.network_retry_count:
                    raise Exception(f"{label} 连接失败: {str(exc)}") from exc
                self._sleep_for_retry(network_attempt)
                network_attempt += 1
                continue

            if response.status_code == 200:
                return response.json()

            error_detail = response.text[:500]
            if (
                "response_format" in request_payload
                and not downgraded_response_format
                and _is_unknown_response_format(error_detail)
            ):
                logger.warning("上游不支持 response_format，移除后重试一次")
                request_payload.pop("response_format", None)
                downgraded_response_format = True
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if server_attempt < self.policy.server_retry_count:
                    self._sleep_for_retry(server_attempt, response)
                    server_attempt += 1
                    continue

            logger.error(f"{label} 请求失败: status={response.status_code}, error={error_detail}")
            raise Exception(
                f"{label} 请求失败 (状态码: {response.status_code})\n"
                f"错误详情: {error_detail}\n"
                f"请求地址: {url}"
            )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.policy.api_key}",
            "Content-Type": "application/json",
        }

    def _sleep_for_retry(self, attempt: int, response: Optional[requests.Response] = None):
        retry_after = _parse_retry_after(response.headers.get("Retry-After")) if response else None
        delay = retry_after if retry_after is not None else min(1.5 * (attempt + 1), 5.0)
        time.sleep(delay)


def _is_unknown_response_format(error_detail: str) -> bool:
    text = error_detail.lower()
    return "unknown parameter" in text and "response_format" in text


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            return max((retry_at.timestamp() - time.time()), 0.0)
        except (TypeError, ValueError, OverflowError):
            return None
