import re
from typing import Any


_MISSING = object()
_RATIO_RE = re.compile(r"([1-9]\d{0,2}):([1-9]\d{0,2})")


class VideoParamError(ValueError):
    """Raised when video generation parameters cannot be sent safely."""


def normalize_video_duration(value: Any, default: int | object = _MISSING) -> int:
    if value is None or value == "":
        if default is not _MISSING:
            return int(default)
        raise VideoParamError("视频时长必须是正整数秒数")

    if isinstance(value, bool):
        raise VideoParamError("视频时长必须是正整数秒数")

    if isinstance(value, int):
        duration = value
    elif isinstance(value, str):
        value = value.strip()
        if not value.isdecimal():
            raise VideoParamError("视频时长必须是正整数秒数")
        duration = int(value)
    else:
        raise VideoParamError("视频时长必须是正整数秒数")

    if duration <= 0:
        raise VideoParamError("视频时长必须是正整数秒数")
    return duration


def normalize_video_ratio(value: Any, default: str | object = _MISSING) -> str:
    if value is None or value == "":
        if default is not _MISSING:
            return str(default)
        raise VideoParamError("视频比例必须使用 16:9 这类正整数宽高比")

    ratio = str(value).strip()
    match = _RATIO_RE.fullmatch(ratio)
    if not match:
        raise VideoParamError("视频比例必须使用 16:9 这类正整数宽高比")
    return f"{int(match.group(1))}:{int(match.group(2))}"
