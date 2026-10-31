"""授时模块单元测试：SNTP 解析、偏移计算与兜底路径喵。"""

from __future__ import annotations

import struct

from app import clock as clock_module
from app.clock import NTP_EPOCH_OFFSET, TrustedClock, build_request_packet, parse_offset


def _response_with_transmit(seconds: float) -> bytes:
    """构造一条带传输时间戳的 SNTP 响应，其余字节留空喵。"""
    # 整数秒与小数部分拆成两个 32 位整数喵
    whole = int(seconds) + NTP_EPOCH_OFFSET
    fraction = int((seconds - int(seconds)) * 2**32)
    # 前 40 字节留空，后 8 字节放传输时间戳喵
    return b"\x00" * 40 + struct.pack("!II", whole, fraction)


def test_build_request_packet_is_48_bytes() -> None:
    """请求报文必须是 48 字节且模式位为客户端喵。"""
    # 报文长度固定喵
    assert len(build_request_packet()) == 48
    # 首字节 0x1B：LI=0、VN=3、Mode=3 喵
    assert build_request_packet()[0] == 0x1B


def test_parse_offset_uses_round_trip_midpoint() -> None:
    """偏移应按发包与收包的中点计算喵。"""
    # 假设服务端时间比本机快 10 秒喵
    server_time = 1_700_000_000.0
    # 本机发包 999.0、收包 999.2，中点 999.1 喵
    offset = parse_offset(_response_with_transmit(server_time), 999.0, 999.2)
    # 偏移应为 服务端 - 中点喵
    assert offset is not None
    assert abs(offset - (server_time - 999.1)) < 0.01


def test_parse_offset_rejects_short_or_zero_packet() -> None:
    """报文过短或时间戳为 0 时应返回 None 喵。"""
    # 短报文喵
    assert parse_offset(b"\x00" * 10, 1.0, 1.1) is None
    # 传输时间戳为 0 喵
    assert parse_offset(b"\x00" * 48, 1.0, 1.1) is None


def test_trusted_clock_falls_back_to_system(monkeypatch) -> None:
    """NTP 与 HTTP 都失败时应退回本机时钟且不抛异常喵。"""
    # 构造一个什么都不通的时钟喵
    fallback = TrustedClock(servers=("127.0.0.1",), timeout_seconds=0.05)
    # 让 NTP 查询直接失败喵
    monkeypatch.setattr(fallback, "_query_sntp", lambda server: None)
    # 让 HTTP 兜底也失败喵
    monkeypatch.setattr(fallback, "_query_http_date", lambda: None)
    # 对齐一次喵
    snapshot = fallback.sync()
    # 来源应标记为 system 且未对齐喵
    assert snapshot.source == "system"
    assert snapshot.synced is False
    # now() 仍然可用喵
    assert fallback.now().tzinfo is not None


def test_trusted_clock_applies_offset(monkeypatch) -> None:
    """对齐成功后 now() 应叠加偏移，快照来源也要写对喵。"""
    # 固定一个 +5 秒的偏移喵
    fixed = TrustedClock(servers=("ntp.aliyun.com",))
    monkeypatch.setattr(fixed, "_query_sntp", lambda server: 5.0)
    # 对齐一次喵
    snapshot = fixed.sync()
    # 来源与偏移应正确喵
    assert snapshot.source == "ntp:ntp.aliyun.com"
    assert snapshot.synced is True
    # now() 应比本机 UTC 时间快约 5 秒喵
    import datetime as datetime_module

    delta = fixed.now() - datetime_module.datetime.now(datetime_module.timezone.utc)
    assert 4.0 < delta.total_seconds() < 6.0
    # 模块级常量没被改坏喵
    assert clock_module.NTP_EPOCH_OFFSET == NTP_EPOCH_OFFSET
