"""授时模块：向阿里云 NTP 对齐时间，避免依赖本机与客户端时钟喵。

为什么要单独做一个时钟：
  - 采集端的系统时间可能不准（改过时间、没开自动同步、虚拟机快照回滚）；
  - 看板浏览器的时间同样不可信（用户机器时区/时钟随便改）；
  - 时间轴、心跳、离线判定全都要一个统一口径，所以服务端自己对齐一次，
    之后所有"现在"都从 TrustedClock 取喵。

对齐方式：SNTP（UDP 123）优先，拿不到就退到阿里云官网的 HTTP Date 头，
再不行才退回本机时钟并在日志里提示，绝不因为授时失败就拒绝上报喵。
"""

from __future__ import annotations

import logging
import socket
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.clock")

# NTP 报文固定 48 字节喵
NTP_PACKET_SIZE = 48

# NTP 端口喵
NTP_PORT = 123

# 1900-01-01 到 1970-01-01 之间的秒数，NTP 时间戳要减掉它喵
NTP_EPOCH_OFFSET = 2_208_988_800

# 客户端请求报文：LI=0、VN=3、Mode=3（客户端），其余字段留空喵
NTP_REQUEST_PACKET = b"\x1b" + 47 * b"\x00"

# 阿里云公共 NTP 服务器，按顺序尝试喵
DEFAULT_SERVERS = (
    "ntp.aliyun.com",
    "ntp1.aliyun.com",
    "ntp2.aliyun.com",
    "ntp3.aliyun.com",
    "ntp4.aliyun.com",
)

# HTTP 兜底用的地址，只读响应头里的 Date 喵
DEFAULT_HTTP_URL = "https://www.aliyun.com"

# 对齐一次最多等多久（秒）喵
DEFAULT_TIMEOUT_SECONDS = 2.0

# 相邻两次对齐的最小间隔（秒），防止配置写得太小把阿里云打爆喵
MIN_SYNC_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class ClockSnapshot:
    """一次授时状态快照，接口与看板都用它喵。"""

    # 当前时间偏移（秒），正数表示本机慢喵
    offset_seconds: float
    # 授时来源，例如 ntp:ntp.aliyun.com / http:www.aliyun.com / system 喵
    source: str
    # 最近一次成功对齐的时间，没成功过就是 None 喵
    synced_at: datetime | None
    # 是否已经成功对齐过喵
    synced: bool


def build_request_packet() -> bytes:
    """构造 SNTP 客户端请求报文喵。

    输入：无。
    输出：48 字节报文，首字节 0x1B 表示 LI=0、VN=3、Mode=3。
    边界：报文是常量，多次调用返回同样的内容喵。
    """
    # 直接返回常量，避免每次握手都新建 bytes 喵
    return NTP_REQUEST_PACKET


def parse_offset(data: bytes, sent_at: float, received_at: float) -> float | None:
    """从 SNTP 响应里算出本机时钟偏移喵。

    输入：响应报文、发包前后的本机时间戳（time.time() 秒）。
    输出：服务端时间减本机时间的偏移（秒）；报文不合法时返回 None。
    边界：
      - 只认传输时间戳（transmit timestamp，偏移 40 字节起）；
      - 按 (发包时刻 + 收包时刻) / 2 作为本机基准，抵消一半网络延迟喵。
    """
    # 喵~防御：报文太短说明不是合法 SNTP 响应喵
    if len(data) < NTP_PACKET_SIZE:
        return None
    # 取传输时间戳的整数秒与小数部分喵
    seconds, fraction = struct.unpack("!II", data[40:48])
    # 喵~防御：秒数为 0 表示服务端还没填时间，按失败处理喵
    if seconds == 0:
        return None
    # 还原成 Unix 时间（秒，带小数）喵
    server_time = seconds - NTP_EPOCH_OFFSET + fraction / 2**32
    # 本机基准时间取发包与收包的中点喵
    local_time = (sent_at + received_at) / 2
    # 偏移就是两者之差喵
    return server_time - local_time


class TrustedClock:
    """可注入的授时时钟，所有"现在"都从它取喵。"""

    def __init__(
        self,
        servers: tuple[str, ...] = DEFAULT_SERVERS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        http_url: str = DEFAULT_HTTP_URL,
    ) -> None:
        """记录服务器列表与超时，初始偏移为 0（等同本机时钟）喵。"""
        # 阿里云 NTP 服务器列表喵
        self._servers = tuple(servers) or DEFAULT_SERVERS
        # 单次握手超时喵
        self._timeout = max(0.2, float(timeout_seconds))
        # HTTP 兜底地址喵
        self._http_url = http_url
        # 当前偏移（秒）喵
        self._offset = 0.0
        # 当前来源喵
        self._source = "system"
        # 最近一次成功对齐时刻喵
        self._synced_at: datetime | None = None

    def now(self) -> datetime:
        """取对齐后的当前时间（UTC，带时区）喵。

        输入：无。
        输出：datetime，已叠加授时偏移。
        边界：从没对齐成功时等于本机 UTC 时间喵。
        """
        # 本机 UTC 时间加上偏移就是对齐后的时间喵
        return datetime.now(timezone.utc) + timedelta(seconds=self._offset)

    def snapshot(self) -> ClockSnapshot:
        """导出当前授时状态，供接口与看板展示喵。"""
        # 直接按内部字段拼快照喵
        return ClockSnapshot(
            offset_seconds=round(self._offset, 3),
            source=self._source,
            synced_at=self._synced_at,
            synced=self._synced_at is not None,
        )

    def sync(self) -> ClockSnapshot:
        """对齐一次时间，依次尝试 NTP、HTTP、本机喵。

        输入：无。
        输出：对齐后的状态快照。
        边界：所有来源都失败时保留旧偏移，只把来源标成 system 并在日志告警喵。
        """
        # 先试阿里云 NTP 喵
        for server in self._servers:
            offset = self._query_sntp(server)
            # 喵~防御：单个服务器失败就换下一个，不抛异常喵
            if offset is None:
                continue
            # 记下偏移、来源与时间喵
            self._offset = offset
            self._source = f"ntp:{server}"
            self._synced_at = datetime.now(timezone.utc)
            LOGGER.info("授时成功 source=%s offset=%.3fs", self._source, offset)
            return self.snapshot()
        # NTP 全挂就退到 HTTP Date 喵
        offset = self._query_http_date()
        if offset is not None:
            # HTTP 兜底成功喵
            self._offset = offset
            self._source = "http:aliyun"
            self._synced_at = datetime.now(timezone.utc)
            LOGGER.info("授时成功 source=%s offset=%.3fs", self._source, offset)
            return self.snapshot()
        # 喵~防御：授时全失败也不能让服务挂掉，退回本机时钟并告警喵
        self._source = "system"
        LOGGER.warning("授时失败，暂时使用本机时钟，请检查网络或 NTP 是否被封")
        return self.snapshot()

    def _query_sntp(self, server: str) -> float | None:
        """向单个 NTP 服务器查询偏移喵。

        输入：服务器域名或 IP。
        输出：偏移秒数；失败返回 None。
        边界：DNS 解析失败、超时、报文异常都返回 None，不抛异常喵。
        """
        try:
            # 用 UDP 建一个短连接喵
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                # 设置超时，避免卡住上报线程喵
                sock.settimeout(self._timeout)
                # 记下发包时间喵
                sent_at = time.time()
                # 发请求喵
                sock.sendto(NTP_REQUEST_PACKET, (server, NTP_PORT))
                # 等响应喵
                data, _ = sock.recvfrom(NTP_PACKET_SIZE)
                # 记下收包时间喵
                received_at = time.time()
        except (OSError, ValueError) as error:
            # 喵~防御：网络层异常只记 debug，交给下一个服务器喵
            LOGGER.debug("NTP 查询失败 server=%s error=%s", server, error)
            return None
        # 交给纯函数解析偏移喵
        return parse_offset(data, sent_at, received_at)

    def _query_http_date(self) -> float | None:
        """读阿里云官网响应头里的 Date 作为兜底授时喵。

        输入：无。
        输出：偏移秒数；失败返回 None。
        边界：只用响应头，不下载正文喵。
        """
        try:
            # 延迟导入，避免没装 httpx 时影响其它功能喵
            import httpx

            # 记下发请求前的本机时间喵
            sent_at = time.time()
            # 只取响应头，超时与 NTP 一致喵
            response = httpx.head(self._http_url, timeout=self._timeout, follow_redirects=True)
            # 记下收到响应的时间喵
            received_at = time.time()
            # 取 Date 头喵
            date_text = response.headers.get("date", "")
            # 喵~防御：没有 Date 头就没法兜底喵
            if not date_text:
                return None
            # 解析成 datetime 并转成时间戳喵
            server_time = parsedate_to_datetime(date_text).timestamp()
        except Exception as error:  # noqa: BLE001 - 兜底路径不允许把异常抛给主流程
            # 喵~防御：兜底失败也只记 debug 喵
            LOGGER.debug("HTTP 授时失败 error=%s", error)
            return None
        # 与 NTP 一样取往返中点做基准喵
        return server_time - (sent_at + received_at) / 2

# 模块级默认时钟：服务端各处共用同一个实例，保证全进程口径一致喵
_DEFAULT_CLOCK = TrustedClock()


def get_clock() -> TrustedClock:
    """取全局时钟实例喵。

    输入：无。
    输出：TrustedClock，未对齐过时等价于本机 UTC 时间。
    边界：任何模块都可以调用，返回的是同一个对象喵。
    """
    # 直接返回模块级实例喵
    return _DEFAULT_CLOCK


def set_clock(instance: TrustedClock) -> None:
    """替换全局时钟实例，服务端启动时按配置重建喵。

    输入：新的 TrustedClock 实例。
    输出：无。
    边界：只在启动阶段调用，避免运行中口径突变喵。
    """
    # 声明要改模块级变量喵
    global _DEFAULT_CLOCK
    # 换成新实例喵
    _DEFAULT_CLOCK = instance
