"""图片服务商策略归一化。"""
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ImageProviderPolicy:
    """归一化后的图片服务商能力与调度配置。"""

    api_key: str
    base_url: str
    model: str
    endpoint_type: str
    max_concurrent: int = 1
    request_interval_seconds: float = 3.0
    high_concurrency: bool = False
    response_format: Optional[str] = None
    network_retry_count: int = 0
    server_retry_count: int = 1

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        default_model: str = "default-model",
        default_endpoint: str = "/v1/images/generations",
    ) -> "ImageProviderPolicy":
        base_url = (config.get("base_url") or "https://api.example.com").rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        endpoint_type = cls.normalize_endpoint(
            config.get("endpoint_type") or default_endpoint
        )

        max_concurrent = _positive_int(config.get("max_concurrent"), default=1)
        request_interval = _non_negative_float(
            config.get("request_interval_seconds"),
            default=3.0,
        )

        response_format = config.get("response_format")
        if response_format in ("", None):
            response_format = None

        return cls(
            api_key=config.get("api_key", ""),
            base_url=base_url,
            model=config.get("model") or default_model,
            endpoint_type=endpoint_type,
            max_concurrent=max_concurrent,
            request_interval_seconds=request_interval,
            high_concurrency=bool(config.get("high_concurrency", False)),
            response_format=response_format,
            # 长耗时生图在连接断开后盲重试可能重复计费。网络错误默认不重试；
            # 明确的 429/5xx 默认仅重试一次，并允许服务商配置覆盖。
            network_retry_count=_non_negative_int(
                config.get("network_retry_count", config.get("network_retries")),
                default=0,
            ),
            server_retry_count=_non_negative_int(
                config.get("server_retry_count", config.get("server_retries")),
                default=1,
            ),
        )

    @property
    def is_chat_endpoint(self) -> bool:
        endpoint = self.endpoint_type.lower()
        return "chat" in endpoint or "completions" in endpoint

    @property
    def worker_count(self) -> int:
        if self.high_concurrency and self.max_concurrent > 1:
            return self.max_concurrent
        return 1

    @staticmethod
    def normalize_endpoint(endpoint_type: str) -> str:
        if endpoint_type == "images":
            endpoint_type = "/v1/images/generations"
        elif endpoint_type == "chat":
            endpoint_type = "/v1/chat/completions"
        if not endpoint_type.startswith("/"):
            endpoint_type = "/" + endpoint_type
        return endpoint_type


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _non_negative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
        return parsed if parsed >= 0 else default
    except (TypeError, ValueError):
        return default


def _non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else default
    except (TypeError, ValueError):
        return default
