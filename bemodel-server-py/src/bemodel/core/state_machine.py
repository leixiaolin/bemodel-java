from .exceptions import BizException

TRANSITIONS = {"DRAFT": {"REVIEW"}, "REVIEW": {"PUBLISHED", "DRAFT"},
               "PUBLISHED": {"DEPRECATED"}, "DEPRECATED": {"DRAFT"}}


def check(current, target):
    if target not in TRANSITIONS:
        raise BizException(f"非法状态: {target}")
    if target not in TRANSITIONS.get(current, set()):
        raise BizException(f"不允许从 {current} 流转到 {target}")


def action_name(target):
    return {"REVIEW": "提交评审", "PUBLISHED": "发布", "DEPRECATED": "废弃"}.get(target, "退回草稿")
