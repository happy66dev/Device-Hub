"""在线状态与使用空档的时间线计算。

为什么要单独一个模块：看板要把一天的每一分钟分成三类——

- **离线**：这段时间没有任何心跳，说明采集端没在跑（软件没启动、被关掉、机器关机）；
- **空档**：设备在线，但这一分钟没有任何使用记录；
- **在用**：这一分钟有使用记录，时间轴上画成应用色块。

喵~注意：空档的定义是「在线但无使用记录」，不是「在线且报 AFK」。两者不等价：
手机亮屏（afk=false）却因为被投屏门控暂停计时时同样没有使用记录，那也是空档。
主人的口径是「时间轴上不允许出现无使用记录的空档」，所以只要有心跳、没色块，就是空档喵。

这三类的判定逻辑不依赖数据库和 HTTP，放在这里就能直接用单元测试锁住喵。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# 离线区间喵
KIND_OFFLINE = "offline"

# 空档（在线但没有使用记录）区间喵
KIND_AFK = "afk"

# 一分钟的秒数喵
SECONDS_PER_MINUTE = 60

# 默认心跳超时：超过这么久没有新上报就认为采集端没在跑喵
# 喵~注意：原来是 180 秒，会让 60-180 秒的上报中断在时间轴上留一条白缝——
# 既不算使用也不算空档，更不算离线，看起来像渲染漏了。
# 主人的口径是「离线必须绝对真实」，短暂断报按离线呈现更贴近事实；
# 而且网络抖动导致的上报丢失，客户端下一轮会补上心跳，不必为容错放宽这么久喵
DEFAULT_HEARTBEAT_TIMEOUT_SECONDS = 60

# 空档边界容差：客户端给的精确时刻与整分钟结果相差超过这个值就认为时钟不可信喵
EDGE_TOLERANCE_SECONDS = 180

# 喵~注意：这里原来有个 MIN_AFK_SECONDS_PER_MINUTE = 30，用来要求
# "这一分钟里被 AFK 覆盖够 30 秒才算空档"。主人的口径改成
# 「无使用记录就是空档」之后，在线且没使用的分钟一律算空档，
# 这个阈值不再参与判定，删掉避免误导喵

# 喵~注意：短于这个秒数的状态段直接丢掉不留痕——把空档边界挪到客户端给的
# 精确时刻时会在边界切出 0.0-0.9 秒的残余段（实测 95 个状态段里 41 个是这种），
# 前端按百分比定位，0.6 秒折合宽度不到千分之一像素，画出来是一条若隐若现的竖线喵
MIN_VISIBLE_SECONDS = 1

# 喵~注意：精确区间补出来的空档碎片短于这个秒数就丢掉，避免时间轴上全是碎斜纹喵
# 喵~注意：原来是 10 秒，但上报间隔 60 秒、AFK 边界帧往往还带 1-2 秒残留使用量，
# 这 1-2 秒会从 AFK 碎片尾部扣掉，导致 10-11 秒的真实短空档只剩 8-9 秒被误丢，
# 时间轴上表现为两个使用色块之间留 6-10 秒空白（实测 4 小时内出现 6 处共 42 秒）。
# 收到 5 秒后这些真实短空档能正常画出斜纹，1-2 秒的抖动噪声仍被挡住喵
MIN_AFK_SECONDS = 5

# 喵~注意：兜底残缝阈值——所有区间算完后，相邻两个使用色块之间剩下的零点几秒到几秒
# 如果既不是离线也没被任何区间覆盖，就把这段补成空档，让时间轴连续不留白。
# 主人的原则是「离线数据必须绝对真实，空档可以不那么精确」，所以这里
# 只填使用段之间的小残缝，绝不碰离线区间，也绝不会把离线时间改画成空档喵。
# 阈值取 180 秒：实测一次采集端重启会造成 80-140 秒的上报中断，按整分钟判定时
# 首尾两分钟都有心跳、中间那一分钟既没使用也没 AFK，于是留出一条白线。
# 这类空白必然是「设备在线、只是没在用」，补成空档才对；
# 再长的空白说明设备真的失联，会由按分钟判定归到离线，不必在这里兜喵
RESIDUAL_AFK_SECONDS = 180


@dataclass(frozen=True)
class Heartbeat:
    """一次上报心跳喵。"""

    # 上报时间（UTC）喵
    reported_at: datetime

    # 这次上报时采集端是否处于 AFK 喵
    afk: bool

    # 上报的设备 ID，多设备合并时要按设备分开判断喵
    device_id: str = ""

    # 这台设备是不是服务器角色：服务器 AFK 直接算离线喵
    is_server: bool = False

    # 客户端"停止计时"的那一刻，用来把空档起点量到秒（旧客户端不带）喵
    afk_since: datetime | None = None

    # 客户端"恢复计时"的那一刻，用来把空档终点量到秒（旧客户端不带）喵
    active_since: datetime | None = None


@dataclass(frozen=True)
class PresenceInterval:
    """一段连续的离线或空档区间喵。"""

    # 区间类型：offline 或 afk 喵
    kind: str

    # 区间起点（UTC）喵
    start: datetime

    # 区间终点（UTC）喵
    end: datetime

    @property
    def seconds(self) -> int:
        """区间长度秒数喵。"""
        # 直接算差值喵
        return int((self.end - self.start).total_seconds())


def _minute_starts(start: datetime, end: datetime) -> list[datetime]:
    """把时间窗切成整分钟起点列表喵。"""
    # 喵~防御：窗口非法时返回空列表喵
    if end <= start:
        return []
    minutes: list[datetime] = []
    cursor = start
    while cursor < end:
        minutes.append(cursor)
        cursor += timedelta(seconds=SECONDS_PER_MINUTE)
    return minutes


def _bridge_afk_gaps(
    intervals: list[PresenceInterval],
    spans: list[tuple[datetime, datetime]],
    bridge_seconds: int,
) -> list[PresenceInterval]:
    """把空档区间的两端补到相邻使用区间的边界上喵。

    为什么需要：采集端"停止计时"和"上报 afk=true"不是同一时刻——
    Windows 端要先攒满 60 秒空闲才判定 AFK，而且这一批里还带着使用时长时会被抑制成 afk=false，
    所以服务端看到的 AFK 起点总比"最后一段使用结束"晚一个上报周期（实测稳定晚 65 秒）。
    不补的话，色块和斜纹之间会留一条没有任何含义的空白喵。

    输入：区间列表、使用区间（可乱序）、最大回补秒数（0 表示不补）。
    输出：补过缝的新区间列表；只改 afk 区间，离线区间原样返回。
    边界：只在缝隙不超过 bridge_seconds 时补，避免把真正没数据的空白也说成空档喵。
    """
    # 喵~防御：没开回补或没有使用区间时原样返回喵
    if bridge_seconds <= 0 or not spans:
        return intervals
    # 容差喵
    tolerance = timedelta(seconds=bridge_seconds)
    # 使用区间按起点排序，便于找"前一段的结尾"和"后一段的开头"喵
    ordered = sorted(spans, key=lambda item: (item[0], item[1]))
    bridged: list[PresenceInterval] = []
    for interval in intervals:
        # 喵~防御：只处理空档，离线留空是主人要的语义喵
        if interval.kind != KIND_AFK:
            bridged.append(interval)
            continue
        start = interval.start
        end = interval.end
        # 往前找最近一段"整段都在空档之前"的使用结束时刻喵
        previous_end: datetime | None = None
        for _, span_end in ordered:
            if span_end <= interval.start:
                previous_end = span_end if previous_end is None else max(previous_end, span_end)
        if previous_end is not None and (interval.start - previous_end) <= tolerance:
            start = previous_end
        # 往后找最近一段"整段都在空档之后"的使用开始时刻喵
        for span_start, _ in ordered:
            if span_start >= interval.end and (span_start - interval.end) <= tolerance:
                end = span_start
                break
        # 喵~防御：补完仍然没有宽度时保持原样喵
        if end <= start:
            bridged.append(interval)
            continue
        # 有变化才新建对象喵
        bridged.append(
            interval if (start == interval.start and end == interval.end) else PresenceInterval(
                kind=interval.kind, start=start, end=end
            )
        )
    return bridged


@dataclass(frozen=True)
class AfkSpan:
    """一台设备的一段 AFK 区间喵。"""

    # 区间起点喵
    start: datetime

    # 区间终点喵
    end: datetime

    # 起点是不是客户端给的精确时刻（不是的话只能退回上报时刻，不能拿来量边界）喵
    start_exact: bool = False

    # 终点是不是客户端给的精确时刻喵
    end_exact: bool = False

    # 这段区间属于哪台设备喵
    device_id: str = ""


def _edge_trusted(candidate: datetime, reported_at: datetime) -> bool:
    """判断客户端给的边界时刻能不能当精确边界用喵。

    输入：客户端给的时刻、这次上报的时刻。
    输出：True 表示可信。
    边界：库里 reported_at 只存到秒，所以允许最多 1 秒的"边界晚于上报"；
          偏差超过 EDGE_TOLERANCE_SECONDS 时认为时钟不可信，退回上报时刻喵。
    """
    # 喵~注意：上报时间入库时截到整秒，客户端给的时刻带毫秒，这里留 1 秒余量喵
    if candidate > reported_at + timedelta(seconds=1):
        return False
    # 偏差太大同样不采信喵
    return (reported_at - candidate).total_seconds() <= EDGE_TOLERANCE_SECONDS


def _device_afk_spans(
    heartbeats: list[Heartbeat], start: datetime, end: datetime
) -> list[AfkSpan]:
    """按设备算出精确的 AFK 区间喵。

    输入：心跳列表、窗口起止。
    输出：AfkSpan 列表，两端都夹在窗口内，并标明边界是不是客户端给的精确时刻。
    边界：旧客户端不带 afk_since / active_since 时退回心跳上报时刻，此时边界不算精确喵。
    """
    # 按设备分组喵
    by_device: dict[str, list[Heartbeat]] = {}
    for beat in heartbeats:
        by_device.setdefault(beat.device_id, []).append(beat)
    spans: list[AfkSpan] = []
    for device_id, beats in by_device.items():
        # 每台设备按时间顺序走一遍，AFK 状态翻转就开/关一段喵
        beats.sort(key=lambda item: item.reported_at)
        opened: datetime | None = None
        opened_exact = False
        for beat in beats:
            if beat.afk:
                # 喵~防御：起点晚于上报时间说明客户端时钟有问题，退回上报时刻喵
                if opened is None:
                    candidate = beat.afk_since
                    # 喵~注意：客户端时钟偏差超过容差就不采信，退回上报时刻，免得斜纹拉出几十分钟喵
                    if candidate is not None and _edge_trusted(candidate, beat.reported_at):
                        opened, opened_exact = candidate, True
                    else:
                        opened, opened_exact = beat.reported_at, False
            elif opened is not None:
                # 终点同理，不能让"恢复时刻"跑到这次上报之后喵
                candidate = beat.active_since
                if candidate is not None and _edge_trusted(candidate, beat.reported_at):
                    spans.append(AfkSpan(opened, candidate, opened_exact, True, device_id))
                else:
                    spans.append(AfkSpan(opened, beat.reported_at, opened_exact, False, device_id))
                opened = None
                opened_exact = False
        # 窗口结束时还在 AFK 就开到末尾喵
        if opened is not None:
            spans.append(AfkSpan(opened, end, opened_exact, True, device_id))
    # 夹进窗口并丢掉空区间喵
    clipped: list[AfkSpan] = []
    for span in spans:
        left = max(span.start, start)
        right = min(span.end, end)
        if right > left:
            clipped.append(AfkSpan(left, right, span.start_exact, span.end_exact, span.device_id))
    return clipped


def _snap_afk_edges(
    intervals: list[PresenceInterval],
    afk_spans: list[AfkSpan],
    window_start: datetime,
    window_end: datetime,
) -> list[PresenceInterval]:
    """用客户端给的精确 AFK 区间把空档两端量到秒喵。

    输入：按分钟算出的区间、每台设备的 AFK 区间、窗口起止。
    输出：空档两端对齐到精确边界的新区间列表；离线区间原样返回。
    边界：只有组内**所有**在线设备都给了精确边界时才挪那一端，
          偏移超过 EDGE_TOLERANCE_SECONDS 时认为时钟不可信，保持整分钟喵。
    """
    # 喵~防御：没有精确区间就原样返回喵
    if not afk_spans:
        return intervals
    # 容差喵
    tolerance = EDGE_TOLERANCE_SECONDS
    snapped: list[PresenceInterval] = []
    for interval in intervals:
        # 喵~防御：只处理空档，离线留空的语义不变喵
        if interval.kind != KIND_AFK:
            snapped.append(interval)
            continue
        # 用区间中点找出"这段时间里哪些设备确实在 AFK"喵
        middle = interval.start + (interval.end - interval.start) / 2
        covering = [span for span in afk_spans if span.start <= middle <= span.end]
        if not covering:
            snapped.append(interval)
            continue
        start = interval.start
        end = interval.end
        # 起点：组内所有设备都给了精确起点时才能取最晚的那个喵
        if all(span.start_exact for span in covering):
            candidate = max(max(span.start for span in covering), window_start)
            if abs((candidate - interval.start).total_seconds()) <= tolerance:
                start = candidate
        # 终点：组内所有设备都给了精确终点时才能取最早的那个喵
        if all(span.end_exact for span in covering):
            candidate = min(min(span.end for span in covering), window_end)
            if abs((candidate - interval.end).total_seconds()) <= tolerance:
                end = candidate
        # 喵~防御：量完没有宽度就保持原样喵
        if end <= start:
            snapped.append(interval)
            continue
        snapped.append(PresenceInterval(kind=interval.kind, start=start, end=end))
    return snapped


def _subtract_ranges(
    ranges: list[tuple[datetime, datetime]], cuts: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """从一组区间里扣掉另一组区间喵。

    输入：被扣的区间列表、要扣掉的区间列表。
    输出：扣完之后的区间列表（可能为空）。
    """
    # 被扣的区间先合并，避免重复裁剪喵
    result = list(ranges)
    for cut_start, cut_end in _merge_intervals(cuts):
        remaining: list[tuple[datetime, datetime]] = []
        for left, right in result:
            # 喵~防御：完全不相交就原样保留喵
            if cut_end <= left or cut_start >= right:
                remaining.append((left, right))
                continue
            # 左边还剩下的部分喵
            if left < cut_start:
                remaining.append((left, cut_start))
            # 右边还剩下的部分喵
            if cut_end < right:
                remaining.append((cut_end, right))
        result = remaining
    # 过滤掉空区间喵
    return [(left, right) for left, right in result if right > left]


def _every_device_afk(
    beats_by_device: dict[str, list[Heartbeat]],
    spans_by_device: dict[str, list[tuple[datetime, datetime]]],
    piece_start: datetime,
    piece_end: datetime,
    timeout: timedelta,
) -> bool:
    """判断这段碎片里是不是所有有心跳的设备都在空档喵。

    输入：按设备分组的心跳、按设备分组的精确空档区间、碎片起止、心跳超时。
    输出：True 表示可以画成空档。
    边界：这一刻没有心跳的设备算离线，不参与判断；只要有一台在线设备不在空档就返回 False 喵。
    """
    # 用碎片中点代表整段，避免边界处的抖动喵
    moment = piece_start + (piece_end - piece_start) / 2
    for device_id, beats in beats_by_device.items():
        # 找这一刻之前最近的一条心跳喵
        latest: Heartbeat | None = None
        for beat in beats:
            if beat.reported_at <= moment:
                latest = beat
            else:
                break
        # 喵~防御：没心跳或心跳太旧说明这台设备离线，不参与判断喵
        if latest is None or (moment - latest.reported_at) > timeout:
            continue
        # 这台设备必须落在自己的精确空档区间里喵
        if not any(left <= moment <= right for left, right in spans_by_device.get(device_id, [])):
            return False
    return True


def _add_exact_afk_pieces(
    intervals: list[PresenceInterval],
    afk_spans: list[AfkSpan],
    usage_spans: list[tuple[datetime, datetime]],
    heartbeats: list[Heartbeat],
    timeout: timedelta,
    window_start: datetime,
    window_end: datetime,
) -> list[PresenceInterval]:
    """用客户端给的精确区间补出"整分钟判不出来"的短空档喵。

    输入：已经算好的区间、精确空档区间、使用段、心跳、心跳超时、窗口起止。
    输出：补上短空档后的区间列表（按时间升序）。
    边界：碎片先扣掉使用段与离线区间，短于 MIN_AFK_SECONDS 的丢弃；
          只有所有在线设备都在空档里才补，避免多设备时画出假斜纹喵。
    """
    # 只认至少一端精确的区间喵
    exact_spans = [span for span in afk_spans if span.start_exact or span.end_exact]
    # 喵~防御：客户端没给精确边界就什么都不做喵
    if not exact_spans:
        return intervals
    # 按设备整理心跳与区间，判断"是不是所有设备都在空档"喵
    beats_by_device: dict[str, list[Heartbeat]] = {}
    for beat in heartbeats:
        beats_by_device.setdefault(beat.device_id, []).append(beat)
    for beats in beats_by_device.values():
        beats.sort(key=lambda item: item.reported_at)
    spans_by_device: dict[str, list[tuple[datetime, datetime]]] = {}
    for span in exact_spans:
        spans_by_device.setdefault(span.device_id, []).append((span.start, span.end))
    # 逐段扣掉使用时长，得到候选碎片喵
    pieces: list[tuple[datetime, datetime]] = []
    for span in exact_spans:
        left = max(span.start, window_start)
        right = min(span.end, window_end)
        if right <= left:
            continue
        cursor = left
        for usage_start, usage_end in _merge_intervals(usage_spans):
            if usage_end <= cursor or usage_start >= right:
                continue
            if usage_start > cursor:
                pieces.append((cursor, min(usage_start, right)))
            cursor = max(cursor, usage_end)
            if cursor >= right:
                break
        if cursor < right:
            pieces.append((cursor, right))
    # 喵~防御：碎片太短就丢掉，避免时间轴上出现一堆碎斜纹喵
    pieces = [(a, b) for a, b in pieces if (b - a).total_seconds() >= MIN_AFK_SECONDS]
    if not pieces:
        return intervals
    # 只保留"所有在线设备都在空档里"的碎片喵
    kept = [
        (piece_start, piece_end)
        for piece_start, piece_end in pieces
        if _every_device_afk(beats_by_device, spans_by_device, piece_start, piece_end, timeout)
    ]
    if not kept:
        return intervals
    # 合并：整分钟算出来的空档 + 精确碎片，再扣掉离线区间喵
    afk_ranges = [(item.start, item.end) for item in intervals if item.kind == KIND_AFK] + kept
    offline_ranges = [(item.start, item.end) for item in intervals if item.kind == KIND_OFFLINE]
    merged = _subtract_ranges(_merge_intervals(afk_ranges), offline_ranges)
    # 离线区间原样保留，空档换成合并后的结果喵
    rebuilt = [item for item in intervals if item.kind != KIND_AFK]
    rebuilt.extend(PresenceInterval(KIND_AFK, left, right) for left, right in merged)
    rebuilt.sort(key=lambda item: item.start)
    return rebuilt


def _merge_intervals(items: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """把可能重叠的区间合并成不重叠的列表喵。

    输入：区间列表（可乱序）。
    输出：按起点排序、互不重叠的区间列表。
    """
    # 先按起点排序喵
    ordered = sorted(items)
    merged: list[tuple[datetime, datetime]] = []
    for left, right in ordered:
        # 喵~防御：右端不大于左端的区间直接丢掉喵
        if right <= left:
            continue
        # 与上一段接得上就并进去喵
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged


def _fill_residual_afk(
    intervals: list[PresenceInterval],
    usage_spans: list[tuple[datetime, datetime]],
    heartbeats: list[Heartbeat],
    timeout: timedelta,
    start: datetime,
    end: datetime,
) -> list[PresenceInterval]:
    """补上「最后一次使用」到「被判离线」之间那段无记录的空隙喵。

    输入：已算好的区间列表、使用区间、心跳列表、心跳超时、窗口起止。
    输出：补过空隙后的区间列表（按时间升序）。

    喵~注意：要补的是「使用段之间、或使用段与离线段之间」漏着的那截空白。
    这一截既不是使用、也不是离线的正式起点，时间轴上就是一条白线，
    而主人明确要求「不允许出现无使用记录的空档」。

    补成什么按心跳判断：那段期间还有心跳就补空档（人在但没操作），
    心跳已经超时就补离线（客户端掉线了）。

    为什么不能整段窗口地扫：窗口开头那段本来就该由整分钟判定归到离线，
    不需要兜底；这里只认贴着使用段的那些缝，避免把合法的空白也算进来喵。
    """
    # 喵~防御：空窗口没什么可补的喵
    if end <= start:
        return intervals
    # 离线段：用来判定"缝的右端到哪为止"喵
    offline_spans = _merge_intervals(
        [(item.start, item.end) for item in intervals if item.kind == KIND_OFFLINE]
    )
    # 使用段合并后找"最后一段使用"喵
    merged_usage = _merge_intervals([(left, right) for left, right in usage_spans if right > left])
    # 已覆盖的区间：使用段 + 已判出的空档/离线喵
    occupied = _merge_intervals(
        [(item.start, item.end) for item in intervals if item.kind in (KIND_OFFLINE, KIND_AFK)]
        + merged_usage
    )
    # 候选空隙：只补紧贴使用段的那几种白线喵
    # 喵~注意：按分钟判定有盲区——心跳超时线落在分钟中间时，那一分钟既有
    # "还活着"的心跳记录、又没有任何使用，整分钟判定什么都不产出，
    # 时间轴上就留下一条白线（实测 80 秒）。实测下来白线只有三类：
    # ① 相邻两段使用之间；② 使用结束到离线判定起点之间；③ 离线结束后到使用开始之间。
    # 三类都要盖上，否则时间轴会漏白喵
    patches: list[tuple[datetime, datetime]] = []
    # 空隙左端只取"紧贴使用段"的位置喵
    # 喵~注意：为什么不把窗口起点、也不把"在线期间整段没开应用"的时段当左端——
    # 窗口开头那段本来就该由整分钟判定归到离线，不需要兜底；
    # 而"整段在线但没开任何应用"在真实数据里根本不会出现：客户端每轮上报
    # 必然带 afk 标记（Windows 看键鼠空闲、安卓看是否息屏），
    # 活着就一定有 afk=True 或 afk=False，不存在两边都不占的状态喵
    left_edges: list[tuple[datetime, int]] = []
    # ① 每段使用结束 → 接下一段使用开始 / 夹在中间的离线起点：覆盖"两段使用之间"喵
    for index, (_, usage_end) in enumerate(merged_usage):
        left_edges.append((usage_end, index + 1))
    # ② 每段离线结束 → 接它之后的第一段使用：覆盖"离线判完后到使用开始"的白线喵
    # 喵~注意：这类必须真有下一段使用才补，否则离线结束后的大段空白会被误填喵
    for _, offline_end in offline_spans:
        next_index = 0
        while next_index < len(merged_usage) and merged_usage[next_index][0] <= offline_end:
            next_index += 1
        if next_index < len(merged_usage):
            left_edges.append((offline_end, next_index))
    # 喵~注意：最后一段使用之后也要补，但右端不能直接取窗口末尾——
    # 那样会把好几小时涂成空档。右端取"心跳彻底失效"的时刻，
    # 也就是最后一条心跳 + 超时；再往后属于客户端不在了，交给离线喵。
    # ① 里最后一段使用结束已经作为左端入队了，这里不再重复加喵
    for gap_left_raw, next_index in left_edges:
        # 喵~防御：这已经越界了就没有右边的段喵
        if next_index > len(merged_usage):
            continue
        # 找下一段使用开始（没有就用窗口末尾）喵
        next_start = (
            merged_usage[next_index][0] if next_index < len(merged_usage) else end
        )
        # 喵~注意：右端优先取"紧跟其后的离线段起点"——离线段是按整分钟切出来的，
        # 它和使用段之间常常差几十秒，那几十秒正是要补的白线喵
        trimmed_by_offline = False
        for offline_start in sorted(offline_spans):
            if gap_left_raw < offline_start[0] < next_start:
                next_start = offline_start[0]
                trimmed_by_offline = True
                break
        # 喵~注意：没有下一段使用、也没有离线可接时，右端截到"心跳失效线"——
        # 再往后是客户端不在了，由整分钟判定归到离线，不该由兜底填成空档喵
        if not trimmed_by_offline and next_index >= len(merged_usage) and heartbeats:
            last_beat_at = max(beat.reported_at for beat in heartbeats)
            next_start = min(next_start, last_beat_at + timeout)
        gap_left = max(gap_left_raw, start)
        gap_right = min(next_start, end)
        if gap_right <= gap_left:
            continue
        # 从这段里扣掉已被覆盖的部分，剩下的才是真正漏掉的空白喵
        cursor = gap_left
        for occ_left, occ_right in occupied:
            if occ_right <= cursor or occ_left >= gap_right:
                continue
            if occ_left > cursor:
                patches.append((cursor, min(occ_left, gap_right)))
            cursor = max(cursor, occ_right)
            if cursor >= gap_right:
                break
        if cursor < gap_right:
            patches.append((cursor, gap_right))
    # 喵~防御：没有空隙就原样返回喵
    # 喵~注意：只补"窄缝"——超过 RESIDUAL_AFK_SECONDS 的空白交给整分钟判定，
    # 否则"最后一段使用之后"那几个小时会被整段涂成空档，afk 时长直接算爆喵
    patches = [
        (left, right)
        for left, right in patches
        if right > left and (right - left).total_seconds() <= RESIDUAL_AFK_SECONDS
    ]
    if not patches:
        return intervals
    # 心跳按时间排好，下面用双指针扫喵
    ordered_beats = sorted(heartbeats, key=lambda item: item.reported_at)
    # 按"这段期间还有没有心跳"决定补成空档还是离线喵
    filled = list(intervals)
    for left, right in patches:
        if _covered_by_heartbeat(ordered_beats, left, right, timeout):
            # 还有心跳说明设备在线、只是没在用，补成空档喵
            filled.append(PresenceInterval(kind=KIND_AFK, start=left, end=right))
        else:
            # 喵~注意：心跳已经超时说明客户端不在了，这段必须是离线喵
            filled.append(PresenceInterval(kind=KIND_OFFLINE, start=left, end=right))
    # 按起点排序，保持输出稳定喵
    filled.sort(key=lambda item: (item.start, item.end))
    return filled


def _covered_by_heartbeat(
    ordered_beats: list[Heartbeat],
    left: datetime,
    right: datetime,
    timeout: timedelta,
) -> bool:
    """判断一段空白是否全程都被心跳覆盖喵。

    输入：按上报时间升序的心跳、空白起止、心跳超时。
    输出：true 表示这段空白里每个时刻都还处在某个心跳的有效期内。
    边界：空白跨过超时线就返回 false——那意味着客户端在中途已经掉了喵。
    """
    # 喵~防御：没有心跳就无从覆盖喵
    if not ordered_beats:
        return False
    # 找空白起点之前（含）最近的一条心跳喵
    latest: Heartbeat | None = None
    for beat in ordered_beats:
        if beat.reported_at <= right:
            latest = beat
        else:
            break
    # 喵~防御：空白起点之后才有心跳，说明这段之前已经断了喵
    if latest is None:
        return False
    # 用最近的一条心跳算它能不能一直覆盖到空白结束喵
    horizon = latest.reported_at + timeout
    # 空白结束前必须还有心跳续上；否则中途就断了喵
    for beat in ordered_beats:
        if beat.reported_at <= left:
            continue
        if beat.reported_at >= right:
            break
        # 中途有更新的心跳，说明覆盖被续上了喵
        horizon = max(horizon, beat.reported_at + timeout)
    # 覆盖到空白结束才算全程在线喵
    return horizon >= right


def subtract_offline_from_usage(
    usage_spans: list[tuple[datetime, datetime]],
    states: list[PresenceInterval],
) -> list[tuple[datetime, datetime]]:
    """把被离线段覆盖的那部分使用时长扣掉，让离线记录绝对真实喵。

    输入：使用区间、已经算好的状态区间（含离线与空档）。
    输出：扣掉离线部分后的使用区间列表，按起点升序。

    喵~注意：为什么需要它——采集端在上报中断（崩溃、断电、进程被杀）后会把
    积压的使用时长一次性补报，这批秒数没有时间戳，服务端只能把它们铺在
    "上一次铺到的位置"之后，于是会把中断期间的离线时段也盖成使用色块，
    时间轴上就出现「离线期间还在用应用」这种自相矛盾的画面。
    主人的口径是「离线数据必须绝对真实，空档不那么精确没关系」，
    所以这里一律以离线为准：离线区间覆盖到哪里，使用段就裁到哪里喵。
    """
    # 喵~防御：没有状态区间就没有离线可扣喵
    offline = _merge_intervals(
        [(item.start, item.end) for item in states if item.kind == KIND_OFFLINE]
    )
    if not offline or not usage_spans:
        return usage_spans
    # 逐段扣掉离线覆盖喵
    kept: list[tuple[datetime, datetime]] = []
    for span_start, span_end in usage_spans:
        cursor = span_start
        for offline_start, offline_end in offline:
            # 喵~防御：离线段在游标之前或之后都不影响本段喵
            if offline_end <= cursor or offline_start >= span_end:
                continue
            # 离线之前还有使用就留下来喵
            if offline_start > cursor:
                kept.append((cursor, min(offline_start, span_end)))
            cursor = max(cursor, offline_end)
            if cursor >= span_end:
                break
        # 尾巴也要留喵
        if cursor < span_end:
            kept.append((cursor, span_end))
    # 只保留有宽度的段喵
    return [(left, right) for left, right in kept if right > left]


def subtract_usage_from_offline(
    intervals: list[PresenceInterval],
    usage_spans: list[tuple[datetime, datetime]],
) -> list[PresenceInterval]:
    """把被使用段覆盖的那部分离线时间裁掉，使用记录优先喵。

    输入：已算好的状态区间、使用区间（可乱序）。
    输出：裁过离线段的区间列表，按起点升序。

    喵~注意：为什么使用段优先——采集端断网时并不会停止累计，它会把这一批
    秒数留在内存里，等网络恢复后一次性补报。服务端此时才收到心跳，
    按心跳算出来的离线段就会和这批补报的使用段重叠，时间轴上出现
    「离线期间还在用应用」这种自相矛盾的画面。

    两侧的证据强弱不对称：
    - 离线的依据只是"这段时间没收到心跳"，只能证明网络没连通；
    - 使用记录是客户端逐轮累计出来的真实秒数，单轮有上限
      （Windows 15 秒 / 补记 60 秒，安卓同样是采样间隔的倍数），
      不会凭空造出时间，更能证明人确实在用。
    所以这里以使用为准，把离线裁到使用段之外；离线区间被裁光就整段丢弃喵。
    """
    # 喵~防御：没有使用段就没有可裁的依据喵
    if not usage_spans or not intervals:
        return intervals
    # 使用区间先合并，避免逐段重复计算喵
    merged_usage = _merge_intervals(usage_spans)
    kept: list[PresenceInterval] = []
    for interval in intervals:
        # 喵~防御：空档有客户端给的精确边界，不参与这层裁剪喵
        if interval.kind != KIND_OFFLINE:
            kept.append(interval)
            continue
        # 逐段扣掉被使用覆盖的部分喵
        cursor = interval.start
        for usage_start, usage_end in merged_usage:
            # 喵~防御：使用段在游标之前或之后都不影响本段喵
            if usage_end <= cursor or usage_start >= interval.end:
                continue
            # 使用之前还有离线就留下来喵
            if usage_start > cursor:
                kept.append(
                    PresenceInterval(kind=KIND_OFFLINE, start=cursor, end=min(usage_start, interval.end))
                )
            cursor = max(cursor, usage_end)
            if cursor >= interval.end:
                break
        # 尾巴也要留喵
        if cursor < interval.end:
            kept.append(PresenceInterval(kind=KIND_OFFLINE, start=cursor, end=interval.end))
    # 按起点排序，保持输出稳定喵
    kept.sort(key=lambda item: (item.start, item.end))
    return kept


def build_presence(
    heartbeats: list[Heartbeat],
    start: datetime,
    end: datetime,
    timeout_seconds: int = DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
    usage_spans: list[tuple[datetime, datetime]] | None = None,
    bridge_seconds: int = 0,
) -> tuple[list[PresenceInterval], int, int]:
    """把心跳序列折算成离线区间与空档区间喵。

    输入：心跳列表、窗口起止、心跳超时秒数、可选的使用区间（用来避免重复计空档）、
          空档两端回补的最大秒数（0 表示不补）。
    输出：(区间列表, 离线秒数, 空档秒数)。
    边界：心跳为空时整段窗口都算离线喵。
    """
    # 窗口切成分钟喵
    minutes = _minute_starts(start, end)
    # 喵~防御：窗口为空直接返回喵
    if not minutes:
        return [], 0, 0
    # 心跳按时间排序，后面用双指针推进喵
    ordered = sorted(heartbeats, key=lambda item: item.reported_at)
    # 使用区间也排好序，用来判断某一分钟是否已经计入使用喵
    spans = sorted(usage_spans or [], key=lambda span: span[0])
    # 超时时间喵
    timeout = timedelta(seconds=max(1, int(timeout_seconds)))
    # 喵~注意：先把客户端给的精确空档区间算出来，逐分钟判定时用它兜住"短空档"喵
    afk_spans = _device_afk_spans(heartbeats, start, end)
    # 按设备整理成区间列表，判定时要"所有在线设备都在 AFK"才算空档喵
    spans_by_device: dict[str, list[tuple[datetime, datetime]]] = {}
    for span in afk_spans:
        spans_by_device.setdefault(span.device_id, []).append((span.start, span.end))
    # 指针与"每台设备当前最近的一条心跳"喵
    index = 0
    latest_by_device: dict[str, Heartbeat] = {}
    span_index = 0
    # 累计秒数喵
    offline_seconds = 0
    afk_seconds = 0
    # 结果区间喵
    intervals: list[PresenceInterval] = []
    # 当前正在累积的区间喵
    current_kind: str | None = None
    current_start: datetime | None = None

    def flush(cutoff: datetime) -> None:
        """把正在累积的区间收尾喵。"""
        nonlocal current_kind, current_start
        if current_kind is None or current_start is None:
            return
        intervals.append(PresenceInterval(kind=current_kind, start=current_start, end=cutoff))
        current_kind = None
        current_start = None

    for minute_start in minutes:
        # 这一分钟的结束时刻喵
        minute_end = minute_start + timedelta(seconds=SECONDS_PER_MINUTE)
        # 把上报时间不晚于本分钟结束的心跳都吃掉，按设备各记一条最新的喵
        while index < len(ordered) and ordered[index].reported_at <= minute_end:
            beat = ordered[index]
            latest_by_device[beat.device_id] = beat
            index += 1
        # 找出这一分钟仍被心跳覆盖的设备喵
        covered = [
            beat
            for beat in latest_by_device.values()
            if (beat.reported_at + timeout) >= minute_start
        ]
        # 喵~防御：服务器角色 AFK 说明这台机器没人在用，直接当成离线喵
        covered = [beat for beat in covered if not (beat.is_server and beat.afk)]
        # 判断这一分钟是否已经计入使用喵
        used = False
        while span_index < len(spans) and spans[span_index][1] <= minute_start:
            span_index += 1
        if span_index < len(spans):
            span_start, span_end = spans[span_index]
            used = span_start < minute_end and span_end > minute_start
        # 喵~注意：总轴合成按「使用帧 > 任何设备在线 > 全部离线」的优先级喵
        # ① 只要这一分钟有使用帧，就一定是"在用"，压过一切喵
        # ② 没有使用帧、但还有设备在线，就算空档，压过离线喵
        # ③ 一台在线的都没有，才算离线喵
        kind: str | None = None
        if used:
            # 有使用帧 → 在用，不产出区间（色块由使用段自己画）喵
            kind = None
        elif not covered:
            kind = KIND_OFFLINE
            offline_seconds += SECONDS_PER_MINUTE
        else:
            # 喵~注意：主人的口径是「无使用记录就是空档」——只要设备还在线，
            # 这一分钟没画出色块就一定是空档，不许留白喵
            # 喵~注意：这里原来还要求 afk_cover 够 30 秒、或所有设备都报 AFK，
            # 否则 kind 留 None（注释说"算使用态"，实际既不画色块也不画斜纹，
            # 时间轴上就是一条白缝，正是它自己说不能留的那种白）。
            # 实测踩到：手机亮屏但被投屏门控暂停计时，afk=false 又没有使用记录，
            # 14:00-16:28 整整 148 分钟全白。现在不看 afk 标记——
            # 在线且没使用就是空档，afk 只影响边界精确度，不影响是否算空档喵
            kind = KIND_AFK
            afk_seconds += SECONDS_PER_MINUTE
        # 喵~防御：在用状态不产出区间，但要把已经累积的区间收尾喵
        if kind is None:
            flush(minute_start)
            continue
        # 同类型就继续累积，换类型就收尾重开喵
        if current_kind != kind:
            flush(minute_start)
            current_kind = kind
            current_start = minute_start
    # 循环结束后收尾喵
    flush(minutes[-1] + timedelta(seconds=SECONDS_PER_MINUTE))
    # 喵~注意：B 方案——用客户端给的 afk_since / active_since 把空档两端量到秒喵
    if afk_spans:
        intervals = _snap_afk_edges(intervals, afk_spans, start, end)
        # 喵~注意：短到整分钟都判不出来的空档（例如 40 秒）用精确区间直接补成碎片喵
        intervals = _add_exact_afk_pieces(
            intervals, afk_spans, spans, heartbeats, timeout, start, end
        )
        # 边界挪过之后空档总时长按区间重算，保证和图上的斜纹对得上喵
        afk_seconds = sum(item.seconds for item in intervals if item.kind == KIND_AFK)
    # 喵~注意：使用记录优先于离线——断网期间客户端一直在本地累计，
    # 网络恢复后一次性补报，此时按心跳算出的离线会与补报的使用段重叠。
    # 先裁掉被使用覆盖的那部分离线喵
    intervals = subtract_usage_from_offline(intervals, spans)
    # 喵~注意：最后一层兜底——主人要求时间轴上绝不允许出现「无使用记录的空档」，
    # 所以裁完之后把整个窗口再扫一遍，任何没被覆盖的空白都补上。
    # 空白期间还有心跳就补空档，心跳已超时就补离线喵
    intervals = _fill_residual_afk(intervals, spans, heartbeats, timeout, start, end)
    # 喵~注意：最后再清一遍亚秒碎片——把空档边界挪到客户端给的精确时刻时，
    # 会在边界处切出 0.0-0.9 秒的残余段（实测 95 个状态段里有 41 个是这种）。
    # 前端按百分比定位色块，0.6 秒折合宽度不到千分之一像素，
    # 画出来就是一条若隐若现的竖线，看起来像"无使用记录的碎片"。
    # 丢掉它们不影响总时长：这些秒数本来就不到 1 秒，四舍五入后是 0 喵
    intervals = [
        item
        for item in intervals
        if (item.end - item.start).total_seconds() >= MIN_VISIBLE_SECONDS
    ]
    # 兜底补完之后按区间重算两个总时长，保证和图上色块对得上喵
    afk_seconds = sum(item.seconds for item in intervals if item.kind == KIND_AFK)
    offline_seconds = sum(item.seconds for item in intervals if item.kind == KIND_OFFLINE)
    # 喵~注意：A 方案（按容差把空档回补到相邻色块）已被 B 取代，保留代码备用喵
    # 它只是把缝隙盖住，并没有把边界量准，主人要求 B/D 上线后停用它喵
    # intervals = _bridge_afk_gaps(intervals, spans, bridge_seconds)
    # if bridge_seconds > 0:
    #     afk_seconds = sum(item.seconds for item in intervals if item.kind == KIND_AFK)
    return intervals, offline_seconds, afk_seconds
