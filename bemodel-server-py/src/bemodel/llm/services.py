from collections import Counter
import logging
import time
import httpx
from bemodel.config import settings
from bemodel.core.base_dao import BaseDAO
from bemodel.modeling.services import ReleaseService
from .entities import LlmLog


class LlmLogService(BaseDAO):
    def __init__(self, session):
        super().__init__(session, LlmLog)

    def log(self, call_type, model, digest, latency, success, error, response=None):
        try:
            # A failed audit insert must not poison the caller's transaction/session.
            with self.session.begin_nested():
                row = LlmLog(call_type=call_type, model=model, ontology_version=ReleaseService(self.session).current_tag() or "未发布",
                    prompt_digest=(digest or "")[:200], latency_ms=latency, success=int(success), err_msg=error,
                    response_digest=(response or "")[:512] if response is not None else None)
                self.session.add(row)
                self.session.flush()
            if not self.session.info.get("transaction_depth"):
                self.session.commit()
        except Exception:
            logging.getLogger(__name__).exception("LLM 调用日志写入失败（不影响主流程）")

    def stats(self):
        rows = self.select_list()
        return {"total": len(rows), "successRate": int(sum(r.success == 1 for r in rows) * 100 / len(rows) + .5) if rows else 0,
                "byType": dict(Counter(r.call_type for r in rows)),
                "avgLatencyMs": int(sum(r.latency_ms for r in rows) / len(rows) + .5) if rows else 0,
                "currentOntologyVersion": ReleaseService(self.session).current_tag() or "未发布"}


class DeepSeekClient:
    # 标签/JSON 等结构化输出调用对同一问题必须稳定，采样温度归零；
    # 自由文本答复（客服回复、答案组织、报告）保留少量随机性。
    DETERMINISTIC_CALLS = {"CS_ROUTE", "CS_SEMANTIC_PLAN", "MAPPING_SUGGEST", "MISS_CLASSIFY", "DATASOURCE_ONTOLOGY_ANALYSIS"}

    def __init__(self, session):
        self.logs = LlmLogService(session)
        self.last_error = None

    @staticmethod
    def _content_as_text(content):
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = DeepSeekClient._content_as_text(item.get("text"))
                    if text is None and "content" in item:
                        text = DeepSeekClient._content_as_text(item.get("content"))
                    if text:
                        parts.append(text)
            return "".join(parts)
        if isinstance(content, dict):
            text = DeepSeekClient._content_as_text(content.get("text"))
            if text is None and "content" in content:
                text = DeepSeekClient._content_as_text(content.get("content"))
            return text if text is not None else ""
        if isinstance(content, bool):
            return str(content).lower()
        if content is not None:
            return str(content)
        return None

    def chat(self, call_type, system_prompt, user_prompt):
        self.last_error = None
        digest = ((system_prompt or "") + " | " + (user_prompt or ""))[:200]
        if not settings.deepseek_api_key.strip():
            self.last_error = "API Key 未配置"
            self.logs.log(call_type, settings.deepseek_model, digest, 0, False, "API Key 未配置")
            return None
        started = time.monotonic()
        timeout = (settings.ontology_analysis_timeout_seconds
                   if call_type == "DATASOURCE_ONTOLOGY_ANALYSIS" else settings.deepseek_timeout_seconds)
        try:
            response = httpx.post(settings.deepseek_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + settings.deepseek_api_key}, timeout=timeout,
                json={"model": settings.deepseek_model, "temperature": 0 if call_type in self.DETERMINISTIC_CALLS else .2, "messages": [
                    {"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]})
            response.raise_for_status()
            root = response.json()
            choices = root.get("choices") if isinstance(root, dict) else None
            first = choices[0] if isinstance(choices, list) and choices else None
            message = first.get("message") if isinstance(first, dict) else None
            content = self._content_as_text(message.get("content") if isinstance(message, dict) else None)
            if call_type == "DATASOURCE_ONTOLOGY_ANALYSIS" and not (content or "").strip():
                finish = first.get("finish_reason") if isinstance(first, dict) else None
                reasoning = bool(message.get("reasoning_content")) if isinstance(message, dict) else False
                self.last_error = "模型未返回正文"
                if finish == "length":
                    self.last_error += "（输出长度限制已触发）"
                elif reasoning:
                    self.last_error += "（仅返回推理内容）"
                logging.getLogger(__name__).warning(
                    "本体治理模型响应为空：finish_reason=%r，包含推理=%s，响应字段=%s，消息字段=%s",
                    finish, reasoning, sorted(root) if isinstance(root, dict) else type(root).__name__,
                    sorted(message) if isinstance(message, dict) else type(message).__name__)
                self.logs.log(call_type, settings.deepseek_model, digest,
                              int((time.monotonic()-started)*1000), False, self.last_error, None)
                return None
            self.logs.log(call_type, settings.deepseek_model, digest, int((time.monotonic()-started)*1000), content is not None, None, content)
            return content
        except Exception as exc:
            if isinstance(exc, httpx.TimeoutException):
                self.last_error = f"模型请求超时（{timeout} 秒）"
            elif isinstance(exc, httpx.HTTPStatusError):
                self.last_error = f"模型服务返回 HTTP {exc.response.status_code}"
            elif isinstance(exc, httpx.RequestError):
                self.last_error = "无法连接模型服务"
            else:
                self.last_error = f"模型调用失败（{type(exc).__name__}）"
            self.logs.log(call_type, settings.deepseek_model, digest, int((time.monotonic()-started)*1000), False, str(exc), None)
            return None
