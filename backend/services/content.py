"""
内容生成服务

生成小红书风格的标题、文案和标签
"""

import json
import logging
import os
import re
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from backend.utils.text_client import get_text_chat_client

logger = logging.getLogger(__name__)


class ContentService:
    """内容生成服务：生成标题、文案、标签"""

    def __init__(self):
        logger.debug("初始化 ContentService...")
        self.text_config = self._load_text_config()
        self.client = self._get_client()
        self.prompt_template = self._load_prompt_template()
        logger.info(f"ContentService 初始化完成，使用服务商: {self.text_config.get('active_provider')}")

    def _load_text_config(self) -> dict:
        """加载文本生成配置"""
        config_path = Path(__file__).parent.parent.parent / 'text_providers.yaml'
        logger.debug(f"加载文本配置: {config_path}")

        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                logger.debug(f"文本配置加载成功: active={config.get('active_provider')}")
                return config
            except yaml.YAMLError as e:
                logger.error(f"文本配置 YAML 解析失败: {e}")
                raise ValueError(
                    f"文本配置文件格式错误: text_providers.yaml\n"
                    f"YAML 解析错误: {e}\n"
                    "解决方案：检查 YAML 缩进和语法"
                )

        logger.warning("text_providers.yaml 不存在，使用默认配置")
        return {
            'active_provider': 'google_gemini',
            'providers': {
                'google_gemini': {
                    'type': 'google_gemini',
                    'model': 'gemini-2.0-flash-exp',
                    'temperature': 1.0,
                    'max_output_tokens': 8000
                }
            }
        }

    def _get_client(self):
        """根据配置获取客户端"""
        active_provider = self.text_config.get('active_provider', 'google_gemini')
        providers = self.text_config.get('providers', {})

        if not providers:
            logger.error("未找到任何文本生成服务商配置")
            raise ValueError(
                "未找到任何文本生成服务商配置。\n"
                "解决方案：\n"
                "1. 在系统设置页面添加文本生成服务商\n"
                "2. 或手动编辑 text_providers.yaml 文件"
            )

        if active_provider not in providers:
            available = ', '.join(providers.keys())
            logger.error(f"文本服务商 [{active_provider}] 不存在，可用: {available}")
            raise ValueError(
                f"未找到文本生成服务商配置: {active_provider}\n"
                f"可用的服务商: {available}\n"
                "解决方案：在系统设置中选择一个可用的服务商"
            )

        provider_config = providers.get(active_provider, {})

        if not provider_config.get('api_key'):
            logger.error(f"文本服务商 [{active_provider}] 未配置 API Key")
            raise ValueError(
                f"文本服务商 {active_provider} 未配置 API Key\n"
                "解决方案：在系统设置页面编辑该服务商，填写 API Key"
            )

        logger.info(f"使用文本服务商: {active_provider} (type={provider_config.get('type')})")
        return get_text_chat_client(provider_config)

    def _load_prompt_template(self) -> str:
        """加载提示词模板"""
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts",
            "content_prompt.txt"
        )
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    def _parse_json_response(self, response_text: str) -> Dict[str, Any]:
        """解析 AI 返回的 JSON 响应"""
        # 尝试直接解析
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', response_text)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试找到 JSON 对象的开始和结束
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            try:
                return json.loads(response_text[start_idx:end_idx + 1])
            except json.JSONDecodeError:
                pass

        logger.error(f"无法解析 JSON 响应: {response_text[:200]}...")
        raise ValueError("AI 返回的内容格式不正确，无法解析")

    def generate_series_topic_suggestions(
        self,
        series_context: str,
        existing_topics: List[str],
        allow_third_party_ip: bool = False,
    ) -> List[Dict[str, Any]]:
        """按系列规则生成 5 个候选主题；候选本身不会写入合集。"""
        existing = [str(topic).strip() for topic in existing_topics if str(topic).strip()]
        ip_rule = (
            "可以包含第三方动漫、影视、游戏或品牌 IP 方向，但必须把 uses_ip 标为 true，"
            "不得声称官方授权或合作。"
            if allow_third_party_ip
            else "只允许原创人物、原创世界观和通用题材；不得出现第三方动漫、影视、游戏、品牌或真实人物 IP，uses_ip 必须为 false。"
        )
        prompt = "\n".join([
            "你是小红书长期系列的选题编辑。请根据下面的系列硬约束生成恰好 5 个可独立成篇的新主题。",
            series_context,
            f"已有主题（不得重复或仅换同义词）：{json.dumps(existing[-200:], ensure_ascii=False)}",
            ip_rule,
            "要求：主题具体、有画面或剧情空间，彼此差异明显；不要把视觉风格本身当作主题；每个理由不超过 40 字。",
            '只输出 JSON 对象：{"suggestions":[{"topic":"...","reason":"...","uses_ip":false}]}。',
        ])
        active_provider = self.text_config.get('active_provider', 'google_gemini')
        provider_config = self.text_config.get('providers', {}).get(active_provider, {})
        response_text = self.client.generate_text(
            prompt=prompt,
            model=provider_config.get('model', 'gemini-2.0-flash-exp'),
            temperature=provider_config.get('temperature', 1.0),
            max_output_tokens=min(int(provider_config.get('max_output_tokens', 4000)), 4000),
        )
        parsed = self._parse_json_response(response_text)
        raw_items = parsed.get("suggestions")
        if not isinstance(raw_items, list):
            raise ValueError("AI 未返回 suggestions 数组")

        existing_keys = {re.sub(r"\s+", " ", topic).strip().casefold() for topic in existing}
        seen = set(existing_keys)
        suggestions: List[Dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            topic = re.sub(r"\s+", " ", str(raw.get("topic") or "")).strip()[:200]
            reason = re.sub(r"\s+", " ", str(raw.get("reason") or "")).strip()[:200]
            raw_uses_ip = raw.get("uses_ip", False)
            uses_ip = raw_uses_ip is True or (
                isinstance(raw_uses_ip, str) and raw_uses_ip.strip().lower() in {"true", "1", "yes"}
            )
            key = topic.casefold()
            if not topic or key in seen or (uses_ip and not allow_third_party_ip):
                continue
            suggestions.append({"topic": topic, "reason": reason, "uses_ip": uses_ip})
            seen.add(key)
            if len(suggestions) == 5:
                break
        if len(suggestions) != 5:
            raise ValueError("AI 返回的有效候选不足 5 个")
        return suggestions

    def generate_content(
        self,
        topic: str,
        outline: str,
        series_context: str = "",
        series_template: Optional[Dict[str, Any]] = None,
        series_item_index: Optional[int] = None,
        series_item_title: Optional[str] = None,
        content_mode: str = "story",
        **_: Any,
    ) -> Dict[str, Any]:
        """
        生成标题、文案和标签

        参数：
            topic: 用户输入的主题
            outline: 大纲内容

        返回：
            包含 titles, copywriting, tags 的字典
        """
        try:
            logger.info(f"开始生成内容: topic={topic[:50]}...")

            # 构建提示词
            prompt = self.prompt_template.format(
                topic=topic,
                outline=outline
            )
            if series_context:
                prompt += (
                    "\n\n" + series_context +
                    "\n【系列文案校验要求】标题、正文和标签必须保持系列文案口吻；"
                    "不得声称第三方 IP 获得官方授权或合作。"
                )
                if content_mode == "character_sheet" or "内容方向：精细角色图" in series_context:
                    prompt += (
                        "\n【精细角色图文案要求】这不是剧情故事，不要编写事件经过、连续情节或虚构冒险；"
                        "标题、正文和标签只介绍角色阵容、外观亮点、像素风设定和创作备注，"
                        "正文保持短小，明确这是单张角色设定图。"
                    )
            elif series_template:
                from backend.services.series import build_context
                prompt += "\n\n" + build_context(series_template, series_item_title or topic, series_item_index)["series_context"]

            # 从配置中获取模型参数
            active_provider = self.text_config.get('active_provider', 'google_gemini')
            providers = self.text_config.get('providers', {})
            provider_config = providers.get(active_provider, {})

            model = provider_config.get('model', 'gemini-2.0-flash-exp')
            temperature = provider_config.get('temperature', 1.0)
            max_output_tokens = provider_config.get('max_output_tokens', 4000)

            logger.info(f"调用文本生成 API: model={model}, temperature={temperature}")
            response_text = self.client.generate_text(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens
            )

            logger.debug(f"API 返回文本长度: {len(response_text)} 字符")

            # 解析 JSON 响应
            content_data = self._parse_json_response(response_text)

            # 验证必要字段
            titles = content_data.get('titles', [])
            copywriting = content_data.get('copywriting', '')
            tags = content_data.get('tags', [])

            # 确保 titles 是列表
            if isinstance(titles, str):
                titles = [titles]

            # 确保 tags 是列表
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(',')]

            logger.info(f"内容生成完成: {len(titles)} 个标题, {len(tags)} 个标签")

            return {
                "success": True,
                "titles": titles,
                "copywriting": copywriting,
                "tags": tags
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"内容生成失败: {error_msg}")

            # 根据错误类型提供更详细的错误信息
            if "api_key" in error_msg.lower() or "unauthorized" in error_msg.lower() or "401" in error_msg:
                detailed_error = (
                    f"API 认证失败。\n"
                    f"错误详情: {error_msg}\n"
                    "可能原因：API Key 无效或已过期\n"
                    "解决方案：在系统设置页面检查并更新 API Key"
                )
            elif "model" in error_msg.lower() or "404" in error_msg:
                detailed_error = (
                    f"模型访问失败。\n"
                    f"错误详情: {error_msg}\n"
                    "解决方案：在系统设置页面检查模型名称配置"
                )
            elif "timeout" in error_msg.lower() or "连接" in error_msg:
                detailed_error = (
                    f"网络连接失败。\n"
                    f"错误详情: {error_msg}\n"
                    "解决方案：检查网络连接，稍后重试"
                )
            elif "rate" in error_msg.lower() or "429" in error_msg or "quota" in error_msg.lower():
                detailed_error = (
                    f"API 配额限制。\n"
                    f"错误详情: {error_msg}\n"
                    "解决方案：等待配额重置，或升级 API 套餐"
                )
            else:
                detailed_error = (
                    f"内容生成失败。\n"
                    f"错误详情: {error_msg}\n"
                    "建议：检查配置文件 text_providers.yaml"
                )

            return {
                "success": False,
                "error": detailed_error
            }


def get_content_service() -> ContentService:
    """
    获取内容生成服务实例
    每次调用都创建新实例以确保配置是最新的
    """
    return ContentService()
