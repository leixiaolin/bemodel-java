def page_num(value):
    return max(1, value or 1)


def page_size(value, default=20):
    return default if value is None or value < 1 else min(value, 200)


def page_result(items, total, number, size):
    return {"list": items, "total": total, "pageNum": number, "pageSize": size}
