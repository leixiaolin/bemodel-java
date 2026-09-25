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
    DETERMINISTIC_CALLS = {"CS_ROUTE", "CS_SEMANTIC_PLAN", "MAPPING_SUGGEST", "MISS_CLASSIFY"}

    def __init__(self, session):
        self.logs = LlmLogService(session)

    def chat(self, call_type, system_prompt, user_prompt):
        digest = ((system_prompt or "") + " | " + (user_prompt or ""))[:200]
        if not settings.deepseek_api_key.strip():
            self.logs.log(call_type, settings.deepseek_model, digest, 0, False, "API Key 未配置")
            return None
        started = time.monotonic()
        try:
            response = httpx.post(settings.deepseek_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + settings.deepseek_api_key}, timeout=settings.deepseek_timeout_seconds,
                json={"model": settings.deepseek_model, "temperature": 0 if call_type in self.DETERMINISTIC_CALLS else .2, "messages": [
                    {"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]})
            response.raise_for_status()
            choices = response.json().get("choices", [])
            content = choices[0].get("message", {}).get("content") if choices else None
            self.logs.log(call_type, settings.deepseek_model, digest, int((time.monotonic()-started)*1000), content is not None, None, content)
            return content
        except Exception as exc:
            self.logs.log(call_type, settings.deepseek_model, digest, int((time.monotonic()-started)*1000), False, str(exc), None)
            return None
