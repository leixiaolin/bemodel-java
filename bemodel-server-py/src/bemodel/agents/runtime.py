"""MAF (Microsoft Agent Framework) 适配层。

DeepSeek 网关经 OpenAIChatClient(base_url) 直连。本模块只承担智能体的
LLM 调用执行：审计落 bm_llm_log，降级语义与 llm.services.DeepSeekClient
一致——key 未配置或调用失败返回 None，绝不阻断问数主流程。
现有 DeepSeekClient 调用不迁移，新智能体统一经此接入；后续多智能体
编排（WorkflowAgent 等）在此层之上扩展。
"""

import asyncio
import concurrent.futures
import time

from agent_framework import ChatOptions, Message
from agent_framework.openai import OpenAIChatClient
from openai import AsyncOpenAI

from bemodel.config import settings
from bemodel.llm.services import LlmLogService

CRITIC_CALL_TYPE = 'CS_SEMANTIC_CRITIQUE'


def _run_sync(coroutine):
    """问数链路是同步代码（FastAPI 线程池，无运行中的 loop），asyncio.run 桥接；
    万一在事件循环线程被调用，转到独立线程执行，避免嵌套 loop 报错。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def _chat_client():
    """每次调用新建客户端：httpx AsyncClient 绑定创建时的事件循环，
    asyncio.run 每次新开 loop，跨调用复用会报 Event loop is closed。
    仅在智能体触发路径调用，构造成本可忽略。"""
    return OpenAIChatClient(
        model=settings.deepseek_model,
        async_client=AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url.rstrip('/'),
            timeout=settings.deepseek_timeout_seconds,
        ),
    )


def critic_chat(session, system_prompt, user_prompt):
    """校验纠错智能体单轮判定调用：返回模型文本或 None（降级）。"""
    logs = LlmLogService(session)
    digest = ((system_prompt or '')+' | '+(user_prompt or ''))[:200]
    if not settings.deepseek_api_key.strip():
        logs.log(CRITIC_CALL_TYPE, settings.deepseek_model, digest, 0, False, 'API Key 未配置')
        return None
    started = time.monotonic()
    try:
        response = _run_sync(_chat_client().get_response(
            [Message(role='system', contents=system_prompt), Message(role='user', contents=user_prompt)],
            options=ChatOptions(temperature=0),
        ))
        content = response.text
        logs.log(CRITIC_CALL_TYPE, settings.deepseek_model, digest,
                 int((time.monotonic()-started)*1000), content is not None, None, content)
        return content
    except Exception as exc:
        logs.log(CRITIC_CALL_TYPE, settings.deepseek_model, digest,
                 int((time.monotonic()-started)*1000), False, str(exc), None)
        return None
