import re


def snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def camel_case(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(p[:1].upper() + p[1:] for p in rest)


def java_string_hash(value: str) -> int:
    h = 0
    data = value.encode("utf-16-be", errors="surrogatepass")
    for i in range(0, len(data), 2):
        h = (31 * h + int.from_bytes(data[i:i + 2], "big")) & 0xFFFFFFFF
    return h if h < 0x80000000 else h - 0x100000000


def java_hex_hash(value: str) -> str:
    return f"{java_string_hash(value) & 0xFFFFFFFF:08X}"


def java_hash_set_order(values):
    """String HashSet iteration for ordinary non-treeified Java HashMap buckets."""
    unique = list(dict.fromkeys(values))
    capacity = 16
    while len(unique) > capacity * .75:
        capacity *= 2
    def bucket(value):
        h = java_string_hash(value) & 0xFFFFFFFF
        return (h ^ (h >> 16)) & (capacity-1)
    return sorted(unique, key=bucket)


def java_local_datetime(value):
    if value is None:
        return 'null'
    return value.isoformat(timespec='microseconds' if value.microsecond else 'seconds' if value.second else 'minutes')
