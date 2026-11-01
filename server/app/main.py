"""FastAPI 应用入口：上报接口、健康检查、设备列表。

接口约定见 docs/protocol.md：
- 上报必须带 X-Ingest-Token；
- 校验失败返回 4xx 且响应体是 {"ok": false, "error": ..., "detail": ...}；
- 成功统一返回 {"ok": true, ...} 喵。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .clock import DEFAULT_SERVERS, TrustedClock, get_clock, set_clock

from . import acl, botcheck, db, icons, ingest, people, presence, queries, settings, storage
from .bot import simulate
from .bot import users as bot_users
from .bot.runner import BotRunner
from .config import AppConfig, ConfigError, load_config, resolve_config_path
from .gating import reason_text
from .db import utc_now
from .models import ReportPayload

# 模块级授时时钟：所有"现在"都从这里取，避免依赖客户端或浏览器时钟喵
# 授时时钟由 clock 模块统一持有，启动时按配置重建喵
# 模块级日志器，日志格式在 lifespan 里统一配置喵
LOGGER = logging.getLogger("device_hub")

# 服务端版本号，随包一起返回，便于客户端排查喵
SERVER_VERSION = "0.1.0"

# 清理过期数据的间隔秒数，一小时一次足够喵
PRUNE_INTERVAL_SECONDS = 3600
# 心跳超时：超过这么久没有新上报就认为采集端没在跑（离线）喵
HEARTBEAT_TIMEOUT_SECONDS = presence.DEFAULT_HEARTBEAT_TIMEOUT_SECONDS


def _bot_signature(config: AppConfig) -> tuple[str, ...]:
    """把影响机器人连接与准入的配置摊平成可比较的元组喵。

    输入：完整配置。
    输出：字符串元组；两次取值不同说明需要重建机器人任务。
    边界：只覆盖 napcat / qqbot / acl 三段，其它段改了不影响机器人喵。
    """
    # 喵~注意：用 repr 把嵌套列表也拍平，避免列表不可哈希带来的比较麻烦喵
    return (
        repr(asdict(config.napcat)),
        repr(asdict(config.qqbot)),
        repr(asdict(config.acl)),
    )


async def _restart_bot(app: FastAPI, config: AppConfig) -> None:
    """按新配置重建机器人后台任务喵。

    输入：FastAPI 实例、新配置。
    输出：无；通道全关时只把任务清空。
    边界：旧任务先取消并等待退出，避免两个连接同时挂在网关上喵。
    """
    # 取旧任务句柄喵
    old_task: asyncio.Task[None] | None = getattr(app.state, "bot_task", None)
    if old_task is not None:
        # 请求取消并等待真正结束喵
        old_task.cancel()
        await asyncio.gather(old_task, return_exceptions=True)
    # 先清空，后面按需重建喵
    app.state.bot_runner = None
    app.state.bot_task = None
    # 喵~防御：两个通道都关着就不用建任务喵
    if not config.napcat.enabled and not config.qqbot.enabled:
        LOGGER.info("配置热更新：机器人通道全部关闭")
        return
    # 建新实例并起任务喵
    runner = BotRunner(config)
    app.state.bot_runner = runner
    app.state.bot_task = asyncio.create_task(runner.run(), name="device-hub-bot")
    LOGGER.info("配置热更新：机器人通道已重建（%s）", ", ".join(runner.channel_names()) or "无")


async def _apply_runtime_config(app: FastAPI, new_config: AppConfig) -> list[str]:
    """把新配置热更新到运行中的服务，返回需要重启才生效的项喵。

    输入：FastAPI 实例、刚加载出来的新配置。
    输出：需要重启才能生效的字段名列表；能热更新的项不会出现在里面。
    边界：机器人相关配置变化才重建机器人任务，只改阈值之类不会断线喵。
    """
    # 取旧配置用于比较喵
    old_config: AppConfig = app.state.config
    # 换上新配置，所有路由都从 app.state 取，下一次请求就生效喵
    app.state.config = new_config
    # 日志级别立刻生效喵
    logging.getLogger().setLevel(new_config.server.log_level.upper())
    # 机器人连接与准入变了才重建任务喵
    if _bot_signature(old_config) != _bot_signature(new_config):
        await _restart_bot(app, new_config)
    # 记录确实热更新了喵
    LOGGER.info("配置热更新完成")
    # 端口与数据库路径绑在进程启动阶段，改了只能重启喵
    restart_required: list[str] = []
    if old_config.server.port != new_config.server.port:
        restart_required.append("server.port")
    if old_config.server.db_path != new_config.server.db_path:
        restart_required.append("server.db_path")
    return restart_required



def _error_response(status_code: int, error_code: str, detail: str) -> JSONResponse:
    """构造统一格式的错误响应喵。"""
    # 错误码给机器看，detail 给主人看，两者都不含卖萌用语喵
    return JSONResponse(status_code=status_code, content={"ok": False, "error": error_code, "detail": detail})


def _verify_token(request: Request, config: AppConfig) -> bool:
    """校验上报口令，使用常量时间比较避免计时攻击喵。"""
    # 读取请求头，缺失时为 None 喵
    provided_token = request.headers.get("x-ingest-token")
    # 喵~防御：没带口令直接判定失败喵
    if provided_token is None:
        return False
    # 常量时间比较，避免通过响应时间猜测口令喵
    # 喵~注意：compare_digest 遇到含非 ASCII 字符的 str 会抛 TypeError，
    # 直接比 str 会让「口令含中文」或「攻击者发高位字节」变成 500，这里统一编成 bytes 再比喵
    return hmac.compare_digest(provided_token.encode("utf-8"), config.ingest.token.encode("utf-8"))


# 重启用的分离启动器：等旧进程释放端口后再拉起新进程喵
RESTART_LAUNCHER = """
import socket, subprocess, sys, time
port = int(sys.argv[1]); root = sys.argv[2]; log_path = sys.argv[3]
# 等旧进程把端口让出来喵
for _ in range(300):
    probe = socket.socket()
    try:
        probe.connect(("127.0.0.1", port))
        probe.close()
        time.sleep(0.1)
    except OSError:
        break
time.sleep(0.4)
out = open(log_path, "a", encoding="utf-8", buffering=1)
flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
subprocess.Popen([sys.executable, "-m", "app.main"], cwd=root, stdout=out, stderr=out, creationflags=flags)
"""


def _spawn_restart(config: AppConfig) -> None:
    """起一个分离进程，在旧进程退出后重新拉起服务喵。

    输入：当前配置（要用里面的监听端口）。
    输出：无。
    边界：启动器自身失败会抛异常，调用方负责记录日志喵。
    """
    # server 目录就是 app 包的上一级喵
    root = Path(__file__).resolve().parent.parent
    # 新进程的日志追加到同一个文件，方便排查喵
    log_path = root / "data" / "server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # 分离标志：Windows 用 DETACHED_PROCESS，其它平台该值为 0 喵
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [sys.executable, "-c", RESTART_LAUNCHER, str(config.server.port), str(root), str(log_path)],
        cwd=str(root),
        creationflags=flags,
        close_fds=True,
    )


def _restart_after_reply(config: AppConfig) -> None:
    """先让 HTTP 响应发出去，再重启进程喵。"""
    # 给响应留一点发出时间喵
    time.sleep(0.4)
    try:
        # 拉起启动器喵
        _spawn_restart(config)
    except Exception:  # noqa: BLE001
        # 喵~防御：启动器都起不来就别退出了，否则服务彻底没了喵
        LOGGER.exception("重启失败：无法启动新的服务进程")
        return
    # 再等一下确保启动器已经在等待端口喵
    time.sleep(0.6)
    LOGGER.info("服务端正在重启：端口 %s", config.server.port)
    # 立刻退出，把端口让给新进程喵
    os._exit(0)


def _handle_report(
    config: AppConfig, body: bytes, received_at: datetime, client_ip: str = ""
) -> tuple[int, dict[str, object]]:
    """在独立线程里完成解析与落库，返回 (HTTP 状态码, 响应体) 喵。

    输入：配置、原始请求体字节、服务端接收时间。
    输出：状态码与响应字典。
    边界：JSON 语法错误、字段校验失败、数据库异常都转换成对应状态码喵。
    """
    # 喵~防御：空请求体直接判定为非法负载喵
    if not body:
        return 422, {"ok": False, "error": "invalid_payload", "detail": "请求体为空"}
    try:
        # 先按 UTF-8 解码，非法编码会抛 UnicodeDecodeError 喵
        text_body = body.decode("utf-8")
    except UnicodeDecodeError:
        # 喵~防御：客户端编码错误时给出明确提示喵
        return 422, {"ok": False, "error": "invalid_payload", "detail": "请求体必须是 UTF-8 编码"}
    try:
        # 解析 JSON 文本喵
        raw_payload = json.loads(text_body)
    except json.JSONDecodeError as json_error:
        # 喵~防御：JSON 语法错误时把出错位置告诉客户端喵
        return 422, {"ok": False, "error": "invalid_payload", "detail": f"JSON 解析失败：{json_error}"}
    try:
        # 用 pydantic 做字段级校验喵
        payload = ReportPayload.model_validate(raw_payload)
    except ValidationError as validation_error:
        # 喵~防御：只回传前 3 条错误，避免响应体过长喵
        first_errors = validation_error.errors()[:3]
        # 拼成可读的中文说明喵
        detail_text = "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in first_errors)
        return 422, {"ok": False, "error": "invalid_payload", "detail": detail_text}

    # 打开数据库连接执行落库喵
    connection = db.connect(config.server.db_path)
    try:
        # 落库并拿到摘要，门控配置决定是否真的写入使用时长喵
        result = ingest.save_report(connection, payload, received_at, config.gating_settings(), client_ip=client_ip)
    except sqlite3.Error as sql_error:
        # 喵~防御：数据库异常记录日志并返回 500，不把 SQL 细节暴露给客户端喵
        LOGGER.exception("写入上报数据失败：%s", sql_error)
        return 500, {"ok": False, "error": "internal_error", "detail": "服务端写入数据失败，请稍后重试"}
    finally:
        # 无论成功失败都关闭连接喵
        connection.close()

    # 喵~注意：客户端报了"抓不到前台"的秒数时记一条，方便定位计时缺口，正常上报不刷屏喵
    if payload.foreground_missing_seconds:
        LOGGER.info(
            "设备 %s 本次有 %s 秒抓不到前台应用",
            payload.device_id,
            payload.foreground_missing_seconds,
        )

    # 组装成功响应喵
    return 200, {
        "ok": True,
        "device_id": result.device_id,
        "duplicate": result.duplicate,
        "usage_rows_written": result.usage_rows_written,
        "battery_written": result.battery_written,
        "stats_paused": result.stats_paused,
        "stats_paused_reason": result.stats_paused_reason,
        "mirrored_tags": list(result.mirrored_tags),
        "windows_written": result.windows_written,
        "accepted_at": db.to_utc_text(received_at),
    }


class NoCacheStaticFiles(StaticFiles):
    """静态资源每次都回源校验，改完样式不用手动清缓存喵。"""

    async def get_response(self, path: str, scope: dict) -> Any:  # type: ignore[override]
        """在父类响应上补一个 no-cache 头喵。"""
        # 交给 Starlette 处理文件读取与 304 判定喵
        response = await super().get_response(path, scope)
        # 喵~防御：不设这个头，浏览器会按启发式缓存旧文件喵
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

async def _run_clock_sync_loop(interval_seconds: int) -> None:
    """后台定期对齐时间，失败也不影响服务喵。

    输入：对齐间隔秒数。
    输出：无（一直循环到任务被取消）。
    边界：单次失败只记日志，下个周期继续尝试喵。
    """
    # 喵~防御：间隔太小会把阿里云 NTP 打爆，最低按 60 秒算喵
    interval = max(60, int(interval_seconds))
    while True:
        try:
            # 在线程池里跑阻塞的 socket 查询，别卡事件循环喵
            await run_in_threadpool(get_clock().sync)
        except Exception as error:  # noqa: BLE001 - 授时失败不允许影响主服务
            # 喵~防御：任何异常都只记日志喵
            LOGGER.warning("授时任务异常：%s", error)
        # 睡到下一次对齐喵
        await asyncio.sleep(interval)


def create_app(config: AppConfig | None = None) -> FastAPI:
    """创建 FastAPI 应用，允许测试注入配置喵。

    输入：可选的 AppConfig；不传时在启动阶段读取 config.yaml。
    输出：配置好路由与生命周期的 FastAPI 实例。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """启动时加载配置并建表，关闭时收尾喵。"""
        # 测试可以注入配置，生产环境走配置文件喵
        active_config = config or load_config()
        # 配置挂到 app.state，路由里通过 request.app.state 取用喵
        app.state.config = active_config
        # 统一配置日志级别喵
        logging.basicConfig(
            level=active_config.server.log_level.upper(),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        # 授时：启动时先对齐一次，之后按配置间隔后台刷新喵
        clock_task: asyncio.Task[None] | None = None
        if active_config.clock.enabled:
            # 换掉全局时钟实例，其它模块拿到的也是同一个喵
            set_clock(
                TrustedClock(
                    servers=active_config.clock.servers or DEFAULT_SERVERS,
                    timeout_seconds=active_config.clock.timeout_seconds,
                )
            )
            # 后台对齐一次，别把启动卡在网络上喵
            clock_task = asyncio.create_task(
                _run_clock_sync_loop(active_config.clock.sync_interval_seconds),
                name="device-hub-clock",
            )
        # 建表，重复启动安全喵
        db.init_db(active_config.server.db_path)
        # 图标键规则升级后把历史行重算一遍，避免「图标存在但显示不出来」喵
        _rekey_icon_keys(active_config)
        # 机器人任务句柄，未启用时为 None 喵
        bot_task: asyncio.Task[None] | None = None
        # 机器人实例，供状态接口读取连接情况喵
        bot_runner: BotRunner | None = None
        # 喵~防御：只要 NapCat 或官方通道有一个开着就起机器人任务喵
        if active_config.napcat.enabled or active_config.qqbot.enabled:
            # 先建实例再起任务，状态接口需要它喵
            bot_runner = BotRunner(active_config)
            # 创建机器人后台任务，与 Web 服务共用同一个事件循环喵
            bot_task = asyncio.create_task(bot_runner.run(), name="device-hub-bot")
        # 挂到 app.state，状态接口与热更新都从这里取喵
        app.state.bot_runner = bot_runner
        app.state.bot_task = bot_task
        # 打印启动摘要，方便主人确认监听地址与数据库位置喵
        LOGGER.info(
            "服务端启动：http://%s:%s，数据库=%s，机器人=%s",
            active_config.server.host,
            active_config.server.port,
            active_config.server.db_path,
            "启用" if active_config.napcat.enabled or active_config.qqbot.enabled else "关闭",
        )
        # 喵~注意：记下解释器与虚拟环境前缀，重启后能确认跑的是不是同一个环境喵
        LOGGER.info("解释器：%s（prefix=%s）", sys.executable, sys.prefix)
        try:
            # 交出控制权，开始处理请求喵
            yield
        finally:
            # 喵~防御：先停授时任务喵
            if clock_task is not None:
                clock_task.cancel()
                await asyncio.gather(clock_task, return_exceptions=True)
            # 喵~防御：关闭时先取消机器人任务，避免退出过程中还在发消息喵
            if bot_task is not None:
                # 请求取消喵
                bot_task.cancel()
                # 等待取消真正结束，忽略取消异常喵
                await asyncio.gather(bot_task, return_exceptions=True)
            # 关闭时只记录日志，数据库连接是每次请求独立打开的喵
            LOGGER.info("服务端已停止")

    # 创建应用并绑定生命周期喵
    application = FastAPI(title="device-hub", version=SERVER_VERSION, lifespan=lifespan)

    @application.post("/api/v1/report")
    async def submit_report(request: Request) -> JSONResponse:
        """接收客户端上报喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：口令不对直接 401，不继续读请求体喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 读取 Content-Length 请求头做前置大小判断喵
        content_length_header = request.headers.get("content-length")
        if content_length_header is not None:
            try:
                # 转成整数比较喵
                declared_length = int(content_length_header)
            except ValueError:
                # 喵~防御：Content-Length 不是数字说明请求被篡改喵
                return _error_response(400, "invalid_payload", "Content-Length 不是合法整数")
            # 喵~防御：声明长度超过上限时立即拒绝，避免读入超大请求体喵
            if declared_length > active_config.ingest.max_payload_bytes:
                return _error_response(413, "payload_too_large", f"请求体超过 {active_config.ingest.max_payload_bytes} 字节")
        # 读取真实请求体喵
        body = await request.body()
        # 喵~防御：没有 Content-Length 时也要检查真实长度喵
        if len(body) > active_config.ingest.max_payload_bytes:
            return _error_response(413, "payload_too_large", f"请求体超过 {active_config.ingest.max_payload_bytes} 字节")
        # 记录服务端接收时间，带 UTC 时区喵
        received_at = get_clock().now()
        # 把阻塞的解析与落库放到线程池，避免卡住事件循环喵
        # 取请求来源 IP，供 RDP 客户端身份比对喵
        source_ip = request.client.host if request.client else ""
        # 在线程池里解析并落库，避免阻塞事件循环喵
        status_code, response_body = await run_in_threadpool(_handle_report, active_config, body, received_at, source_ip)
        # 返回统一格式的响应喵
        return JSONResponse(status_code=status_code, content=response_body)

    @application.get("/healthz")
    async def healthz(request: Request) -> JSONResponse:
        """健康检查，用于部署后确认服务端活着喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 返回版本与数据库路径，方便主人核对是不是连到同一个库喵
        return JSONResponse(
            content={
                "ok": True,
                "version": SERVER_VERSION,
                "database": str(active_config.server.db_path),
                "bot_enabled": active_config.napcat.enabled,
            }
        )

    @application.get("/api/v1/time")
    async def get_server_time(request: Request) -> JSONResponse:
        """返回服务端授时时间，看板用它校准「现在」喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：时间本身不敏感，但接口统一要求口令，避免暴露部署信息喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 取一次授时快照喵
        snapshot = get_clock().snapshot()
        # 返回服务端"现在"与授时状态喵
        return JSONResponse(
            {
                "ok": True,
                "server_now": get_clock().now().isoformat().replace("+00:00", "Z"),
                "source": snapshot.source,
                "offset_seconds": snapshot.offset_seconds,
                "synced": snapshot.synced,
            }
        )


    @application.get("/api/v1/devices")
    async def list_devices(request: Request) -> JSONResponse:
        """调试用设备列表，同样需要上报口令喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：这个接口会暴露设备名，必须校验口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 数据库查询放到线程池执行喵
        summaries = await run_in_threadpool(_load_devices, active_config)
        # 把 dataclass 转成可序列化字典，时间转成 ISO 文本喵
        serialized = [
            {
                "device_id": item.device_id,
                "platform": item.platform,
                "display_name": item.display_name,
                "os_version": item.os_version,
                "last_seen_at": item.last_seen_at.isoformat(),
                "online": queries.is_online(item.last_seen_at),
            }
            for item in summaries
        ]
        # 返回列表喵
        return JSONResponse(content={"ok": True, "devices": serialized})

    @application.get("/api/v1/dashboard")
    async def dashboard(request: Request) -> JSONResponse:
        """看板首页数据：设备卡片、电量、当前应用与近 24 小时排行喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：看板会暴露设备信息，同样要求口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 数据库查询放到线程池喵
        cards = await run_in_threadpool(_load_dashboard, active_config)
        # 返回卡片列表喵
        return JSONResponse(content={"ok": True, "devices": cards})

    @application.get("/api/v1/rankings")
    async def global_rankings(request: Request) -> JSONResponse:
        """跨设备应用排行：scope=all/device/group，非法值按 all 处理，看板「应用排行」页用喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：排行会暴露应用使用情况，同样要求口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 读取窗口与条数参数，非法值用默认值兜底喵
        hours = _parse_positive_int(request.query_params.get("hours"), default=24, minimum=1, maximum=720)
        limit = _parse_positive_int(request.query_params.get("limit"), default=20, minimum=1, maximum=200)
        # 读取排行口径，非法值按 all 处理，避免前端写错就整页 500 喵
        scope = (request.query_params.get("scope") or "all").strip().lower()
        # 喵~防御：只认三种口径，其它值一律退回 all 喵
        if scope not in {"all", "device", "group"}:
            scope = "all"
        # 设备范围：逗号分隔的设备 ID，空表示全部设备喵
        raw_devices = (request.query_params.get("devices") or "").strip()
        device_ids = [item.strip() for item in raw_devices.split(",") if item.strip()]
        # 线程池里查总排行与分组明细喵
        entries, groups = await run_in_threadpool(
            _load_rankings, active_config, hours, limit, scope, device_ids or None
        )
        # 返回排行列表与分组明细，scope=all 时 groups 为空列表喵
        return JSONResponse(
            content={"ok": True, "hours": hours, "scope": scope, "entries": entries, "groups": groups}
        )

    @application.get("/api/v1/bot/status")
    async def bot_status(request: Request) -> JSONResponse:
        """机器人连接状态：看板用它提示 QQ 是否在线喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：状态里带群号，同样要求口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 取机器人实例，未启用时为 None 喵
        runner = getattr(request.app.state, "bot_runner", None)
        # 逐通道状态喵
        channels = runner.channel_status() if runner is not None else []
        # 任意通道连上就算在线喵
        connected = bool(runner is not None and runner.is_connected())
        # 返回状态喵
        return JSONResponse(
            content={
                "ok": True,
                "enabled": active_config.napcat.enabled or active_config.qqbot.enabled,
                "connected": connected,
                "ws_url": active_config.napcat.ws_url,
                "self_qq": active_config.napcat.self_qq,
                "whitelist_groups": list(active_config.acl.whitelist_groups),
                "blacklist_users": list(active_config.acl.blacklist_users),
                # 多通道状态，看板按这个分开展示喵
                "channels": channels,
                # 官方通道的可见配置，AppSecret 绝不外泄喵
                "qqbot": {
                    "enabled": active_config.qqbot.enabled,
                    "api_base": active_config.qqbot.api_base,
                    "app_id": _mask_secret(active_config.qqbot.app_id),
                    "intents": active_config.qqbot.intents,
                    "whitelist_group_openids": list(active_config.acl.whitelist_group_openids),
                    "private_user_openids": list(active_config.acl.private_user_openids),
                    "free_command_group_openids": list(active_config.qqbot.free_command_group_openids),
                },
            }
        )

    @application.post("/api/v1/bot/command")
    async def test_bot_command(request: Request) -> JSONResponse:
        """命令测试：不经过 QQ，直接把一条命令跑完整条处理链喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：命令测试会暴露设备数据，同样要求口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        try:
            # 读取请求体喵
            body = await request.json()
        except ValueError:
            # 喵~防御：不是合法 JSON 时给出示例喵
            return _error_response(422, "invalid_payload", "请求体必须是 JSON 对象，例如 {\"text\": \"/happy设备\"}")
        # 喵~防御：请求体必须是对象喵
        if not isinstance(body, dict):
            return _error_response(422, "invalid_payload", "请求体必须是 JSON 对象")
        # 取出命令文本喵
        raw_text = body.get("text")
        # 喵~防御：命令为空直接拒绝喵
        if not isinstance(raw_text, str) or not raw_text.strip():
            return _error_response(422, "invalid_payload", "text 不能为空，例如 {\"text\": \"/happy设备\"}")
        # 通道名，缺省走 NapCat，保持老行为喵
        channel = body.get("channel") or "napcat"
        # 喵~防御：通道名写错会让模拟结果对不上真实链路喵
        if channel not in ("napcat", "qqbot"):
            return _error_response(422, "invalid_payload", "channel 只能是 napcat 或 qqbot")
        # 官方通道的群标识是 openid 字符串，NapCat 是整数群号喵
        if channel == "napcat":
            # 解析可选的群号与 QQ 号喵
            group_key = _parse_optional_int(body.get("group_id"))
            user_key = _parse_optional_int(body.get("user_id"))
            # 喵~防御：给了但不是数字时明确报错，免得测试结果让人困惑喵
            if body.get("group_id") is not None and group_key is None:
                return _error_response(422, "invalid_payload", "group_id 必须是整数")
            if body.get("user_id") is not None and user_key is None:
                return _error_response(422, "invalid_payload", "user_id 必须是整数")
        else:
            # 官方通道按字符串取，空串当成没填喵
            group_key = _parse_optional_key(body.get("group_id"))
            user_key = _parse_optional_key(body.get("user_id"))
        # 是否 @ 了机器人，官方免 @ 群可以传 false 喵
        mentioned = bool(body.get("mention", True))
        # 群内角色，用于测免 @ 的角色门槛喵
        role = str(body.get("role") or "member")
        # 喵~防御：角色写错会让门槛判断失真喵
        if role not in ("member", "admin", "owner"):
            return _error_response(422, "invalid_payload", "role 只能是 member / admin / owner")
        # 线程池里跑一遍命令喵
        result = await run_in_threadpool(
            _run_bot_simulation,
            active_config,
            raw_text,
            group_key,
            user_key,
            channel,
            mentioned,
            role,
        )
        # 返回结果喵
        return JSONResponse(content={"ok": True, **result})

    @application.post("/api/v1/bot/test")
    async def test_bot_channel(request: Request) -> JSONResponse:
        """真连一次机器人通道，验证地址与凭据喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：凭据相关操作同样要求口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        try:
            # 读取请求体喵
            body = await request.json()
        except ValueError:
            return _error_response(422, "invalid_payload", "请求体必须是 JSON 对象，例如 {\"channel\": \"napcat\"}")
        # 喵~防御：请求体必须是对象喵
        if not isinstance(body, dict):
            return _error_response(422, "invalid_payload", "请求体必须是 JSON 对象")
        # 通道名喵
        channel = body.get("channel") or "napcat"
        # 喵~防御：只支持两个通道喵
        if channel not in ("napcat", "qqbot"):
            return _error_response(422, "invalid_payload", "channel 只能是 napcat 或 qqbot")
        # 喵~注意：测试用磁盘上的最新配置，这样改完配置不用先重启也能验证喵
        try:
            target_config = await run_in_threadpool(load_config)
        except Exception:  # noqa: BLE001
            # 配置读不出来就退回内存里的那份喵
            target_config = active_config
        # 真连一次喵
        result = await botcheck.test_channel(target_config, channel)
        # 返回结果喵
        return JSONResponse(
            content={
                "ok": True,
                "channel": result.channel,
                "connected": result.ok,
                "latency_ms": result.latency_ms,
                "detail": result.detail,
                "error": result.error,
            }
        )

    @application.get("/api/v1/settings")
    async def get_settings(request: Request) -> JSONResponse:
        """返回设置页可编辑的配置项（密钥只给占位符）喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：配置里含密钥，必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 配置文件路径喵
        config_path = resolve_config_path()
        # 喵~注意：以磁盘上的文件为准，否则刚保存的值会被内存里的旧配置"重置"回去喵
        try:
            disk_config = await run_in_threadpool(load_config, config_path)
        except ConfigError:
            # 喵~防御：盘上文件坏了就退回内存里的配置，页面至少还能打开喵
            disk_config = active_config
        # 摊平成字段列表喵
        fields = settings.read_settings(disk_config)
        # 返回喵
        return JSONResponse(
            content={
                "ok": True,
                "config_path": str(config_path),
                "fields": fields,
                "restart_required": False,
            }
        )

    @application.patch("/api/v1/settings")
    async def update_settings(request: Request) -> JSONResponse:
        """把设置页的改动写回 config.yaml 并立刻热更新生效喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：写配置文件是敏感操作，必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        try:
            # 读取请求体喵
            body = await request.json()
        except ValueError:
            return _error_response(422, "invalid_payload", "请求体必须是 JSON 对象")
        # 喵~防御：请求体必须是对象且带 changes 喵
        if not isinstance(body, dict):
            return _error_response(422, "invalid_payload", "请求体必须是 JSON 对象")
        changes = body.get("changes")
        if not isinstance(changes, dict):
            return _error_response(422, "invalid_payload", "changes 必须是「配置项 -> 新值」的对象")
        # 配置文件路径喵
        config_path = resolve_config_path()
        try:
            # 线程池里改文件，避免阻塞事件循环喵
            changed = await run_in_threadpool(settings.apply_settings, config_path, changes)
        except settings.SettingsError as error:
            # 喵~防御：取值不合法时原文件不动，直接回 400 喵
            return _error_response(400, "invalid_settings", str(error))
        # 喵~注意：写盘成功后立刻重新加载并热更新，不用重启服务喵
        restart_required: list[str] = []
        if changed:
            try:
                new_config = await run_in_threadpool(load_config, config_path)
            except ConfigError as error:
                # 喵~防御：理论上写盘前已校验过，真出错时保留旧配置并如实告知喵
                LOGGER.error("配置写盘后重新加载失败：%s", error)
                return _error_response(500, "reload_failed", f"配置已写盘但重新加载失败：{error}")
            restart_required = await _apply_runtime_config(request.app, new_config)
        # 返回改了哪些项喵
        return JSONResponse(
            content={
                "ok": True,
                "config_path": str(config_path),
                "changed": changed,
                # 喵~注意：能热更新的项已经生效，只有端口/数据库路径这类要重启喵
                "restart_required": bool(restart_required),
                "restart_fields": restart_required,
                "applied": bool(changed) and not restart_required,
            }
        )

    @application.post("/api/v1/server/restart")
    async def restart_server(request: Request, background: BackgroundTasks) -> JSONResponse:
        """重启服务端进程，让新配置生效喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：重启是破坏性操作，必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 喵~注意：先回 202，再由后台任务真正退出进程，否则前端看不到回复喵
        background.add_task(_restart_after_reply, active_config)
        return JSONResponse(
            status_code=202,
            content={"ok": True, "restarting": True, "port": active_config.server.port},
        )

    @application.post("/api/v1/icons")
    async def upload_icon(request: Request) -> JSONResponse:
        """上传一张应用图标（PNG），同一应用只保留最新一张喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：写库操作必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        try:
            # 解析请求体喵
            payload = await request.json()
        except (ValueError, json.JSONDecodeError):
            return _error_response(422, "invalid_payload", "请求体必须是合法 JSON")
        if not isinstance(payload, dict):
            return _error_response(422, "invalid_payload", "请求体必须是对象")
        # 解析 base64 图标喵
        try:
            png_bytes = base64.b64decode(str(payload.get("png_base64", "")), validate=True)
        except (ValueError, binascii.Error):
            # 喵~防御：base64 坏了直接拒绝，别把乱码写进库喵
            return _error_response(422, "invalid_payload", "png_base64 不是合法的 base64")
        # 校验并落库喵
        try:
            key = await run_in_threadpool(
                _save_icon,
                active_config,
                str(payload.get("app", "")),
                str(payload.get("package", "")),
                png_bytes,
            )
        except icons.IconError as error:
            return _error_response(422, "invalid_payload", str(error))
        # 返回图标键喵
        return JSONResponse(content={"ok": True, "key": key})

    @application.get("/api/v1/icons")
    async def list_icons(request: Request) -> JSONResponse:
        """列出已有图标与内容哈希，客户端据此比对要不要重新上传喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：需要口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 线程池里查库喵
        entries = await run_in_threadpool(_list_icons, active_config)
        # 返回结果喵
        return JSONResponse(content={"ok": True, "icons": entries})

    @application.get("/api/v1/storage")
    async def storage_stats(request: Request) -> JSONResponse:
        """返回库文件大小与各表行数喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：统计信息也算敏感数据，要口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 线程池里统计喵
        stats = await run_in_threadpool(_storage_stats, active_config)
        # 返回结果喵
        return JSONResponse(content={"ok": True, **stats})

    @application.post("/api/v1/storage/cleanup")
    async def storage_cleanup(request: Request) -> JSONResponse:
        """按天数清理历史数据喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：删数据必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        try:
            # 解析请求体喵
            payload = await request.json()
        except (ValueError, json.JSONDecodeError):
            return _error_response(422, "invalid_payload", "请求体必须是合法 JSON")
        # 校验参数喵
        try:
            before_days, targets = storage.parse_cleanup_request(payload)
        except storage.StorageError as error:
            return _error_response(422, "invalid_payload", str(error))
        # 线程池里删数据喵
        deleted = await run_in_threadpool(_storage_cleanup, active_config, before_days, targets)
        # 删完再统计一次，前端可以直接刷新喵
        stats = await run_in_threadpool(_storage_stats, active_config)
        # 返回结果喵
        return JSONResponse(
            content={
                "ok": True,
                "deleted": deleted,
                "deleted_total": sum(deleted.values()),
                "before_days": before_days,
                "threshold": storage.cleanup_threshold_text(before_days),
                "stats": stats,
            }
        )

    @application.get("/api/v1/devices/{device_id}/windows")
    async def device_windows(request: Request, device_id: str, limit: str | None = None) -> JSONResponse:
        """返回某台设备最近一次上报的窗口列表喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：需要口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 解析条数上限喵
        row_limit = _parse_bounded_int(limit, 80, 1, 200)
        # 线程池里查库喵
        result = await run_in_threadpool(_device_windows, active_config, device_id, row_limit)
        # 喵~防御：设备不存在时回 404 喵
        if result is None:
            return _error_response(404, "not_found", "没有这台设备")
        return JSONResponse(content={"ok": True, **result})

    @application.get("/api/v1/icons/{icon_key}")
    async def get_icon(request: Request, icon_key: str) -> Response:
        """按图标键返回 PNG 图片喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：<img> 带不了请求头，这里额外允许 ?token= 喵
        if not _verify_token(request, active_config) and not _verify_query_token(request, active_config):
            return _error_response(401, "invalid_token", "缺少口令")
        # 线程池里读图片喵
        png_bytes = await run_in_threadpool(_load_icon, active_config, icon_key)
        # 喵~防御：没有这张图就回 404，前端会退回色块喵
        if png_bytes is None:
            return _error_response(404, "not_found", "没有这张图标")
        # 图片允许浏览器缓存 30 天；键里含图标内容哈希，换图标后 URL 会变，
        # 浏览器自然按新 URL 重新拉，不会再把旧图标钉在缓存里喵
        return Response(
            content=png_bytes,
            media_type="image/png",
            # 喵~注意：缓存能放宽全靠「键随内容变」，键不变的话这里会害人看到旧图喵
            headers={"Cache-Control": "public, max-age=2592000"},
        )

    @application.get("/api/v1/people")
    async def list_people(request: Request) -> JSONResponse:
        """设备组列表：时间轴用它把多台设备合成一个人的时间轴喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：设备组会暴露设备归属，同样要求口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 线程池里读文件喵
        groups = await run_in_threadpool(people.load_people, active_config.server.db_path)
        # 返回结果喵
        return JSONResponse(
            content={
                "ok": True,
                "groups": [{"name": group.name, "devices": list(group.devices)} for group in groups],
            }
        )

    @application.put("/api/v1/people")
    async def update_people(request: Request) -> JSONResponse:
        """保存设备组（顺序即优先级）喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：写操作必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        try:
            # 解析请求体喵
            payload = await request.json()
        except (ValueError, json.JSONDecodeError):
            # 喵~防御：body 不是合法 JSON 时给出明确提示喵
            return _error_response(422, "invalid_payload", "请求体必须是合法 JSON")
        try:
            # 校验并规范化喵
            groups = people.parse_groups(payload)
        except people.PeopleError as error:
            # 喵~防御：校验失败直接把原因返回给前端喵
            return _error_response(422, "invalid_payload", str(error))
        # 落盘喵
        await run_in_threadpool(people.save_people, active_config.server.db_path, groups)
        # 返回保存后的结果喵
        return JSONResponse(
            content={
                "ok": True,
                "groups": [{"name": group.name, "devices": list(group.devices)} for group in groups],
            }
        )

    @application.get("/api/v1/acl/blocklist")
    async def list_blocklist(request: Request) -> JSONResponse:
        """黑名单列表：WebUI 用来展示与解封喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：名单属于管理数据，必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 线程池里读文件喵
        entries = await run_in_threadpool(acl.load_blocklist, active_config.server.db_path)
        # 配置里写死的那几条也一并返回，前端要标明「来自配置、不可在此删除」喵
        from_config = [
            {
                "channel": "napcat",
                "target": str(item),
                "note": "",
                "created_at": "",
                # 喵~注意：来源标记让前端决定按钮是否可用喵
                "source": "config",
            }
            for item in active_config.acl.blacklist_users
        ] + [
            {
                "channel": "qqbot",
                "target": str(item),
                "note": "",
                "created_at": "",
                "source": "config",
            }
            for item in active_config.acl.blacklist_member_openids
        ]
        runtime = [
            {
                "channel": entry.channel,
                "target": entry.target,
                "note": entry.note,
                "created_at": entry.created_at,
                "source": "runtime",
            }
            for entry in entries
        ]
        # 返回结果喵
        return JSONResponse(content={"ok": True, "entries": runtime + from_config})

    @application.get("/api/v1/acl/seen-users")
    async def list_seen_users(request: Request) -> JSONResponse:
        """最近执行过命令的人：用来反查 openid，好拉黑喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：名单属于管理数据，必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 线程池里查库喵
        rows = await run_in_threadpool(_load_seen_users, active_config)
        # 返回结果喵
        return JSONResponse(content={"ok": True, "users": rows})

    @application.post("/api/v1/acl/blocklist")
    async def add_blocklist(request: Request) -> JSONResponse:
        """拉黑一个人，立刻生效（不需要重启）喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：写操作必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        try:
            # 解析请求体喵
            payload = await request.json()
        except (ValueError, json.JSONDecodeError):
            # 喵~防御：body 不是合法 JSON 时给出明确提示喵
            return _error_response(422, "invalid_payload", "请求体必须是合法 JSON")
        # 喵~防御：body 必须是对象，否则字段全取不到喵
        if not isinstance(payload, dict):
            return _error_response(422, "invalid_payload", "请求体必须是对象")
        try:
            # 落盘喵
            added = await run_in_threadpool(
                acl.add_entry,
                active_config.server.db_path,
                str(payload.get("channel", "napcat")),
                str(payload.get("target", "")),
                str(payload.get("note", "")),
            )
        except acl.AclError as error:
            # 喵~防御：校验失败直接把原因返回给前端喵
            return _error_response(422, "invalid_payload", str(error))
        # 返回是否真的新增喵
        return JSONResponse(content={"ok": True, "added": added})

    @application.delete("/api/v1/acl/blocklist/{channel}/{target}")
    async def delete_blocklist(request: Request, channel: str, target: str) -> JSONResponse:
        """解除拉黑，立刻生效喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：写操作必须带口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 喵~防御：通道名写错时直接拒绝，别静默什么都不做喵
        if channel not in ("napcat", "qqbot"):
            return _error_response(422, "invalid_payload", "通道只能是 napcat 或 qqbot")
        try:
            # 从运行时名单里删喵
            removed = await run_in_threadpool(
                acl.remove_entry, active_config.server.db_path, channel, target
            )
        except acl.AclError as error:
            # 喵~防御：校验失败直接把原因返回给前端喵
            return _error_response(422, "invalid_payload", str(error))
        # 返回是否真的删掉了喵
        return JSONResponse(content={"ok": True, "removed": removed})

    @application.get("/api/v1/timeline")
    async def merged_timeline(request: Request) -> JSONResponse:
        """把多台设备合并成一条时间轴，自用时它们的时间不会重叠喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：合并时间轴同样要求口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 解析设备列表喵
        raw_devices = (request.query_params.get("devices") or "").strip()
        device_ids = [item.strip() for item in raw_devices.split(",") if item.strip()]
        # 喵~防御：没给设备就直接报错，避免返回一整天空白喵
        if not device_ids:
            return _error_response(422, "invalid_payload", "devices 不能为空，格式为 a,b,c")
        # 时区偏移与合并间隔喵
        tz_offset = _parse_bounded_int(request.query_params.get("tz_offset_minutes"), default=480, minimum=-720, maximum=840)
        merge_gap = _parse_bounded_int(request.query_params.get("merge_gap_seconds"), default=5, minimum=0, maximum=7200)
        # 把本地日期换算成 UTC 窗口喵
        day_range = _day_range_utc(request.query_params.get("date"), tz_offset)
        if day_range is None:
            return _error_response(422, "invalid_payload", "date 必须是 YYYY-MM-DD 格式")
        # 线程池里查合并时间轴喵
        payload = await run_in_threadpool(_load_day_timeline, active_config, device_ids, day_range, tz_offset, merge_gap)
        # 返回结果喵
        return JSONResponse(content={"ok": True, **payload})

    @application.get("/api/v1/devices/{device_id}/timeline")
    async def device_timeline(request: Request, device_id: str) -> JSONResponse:
        """某一天 0-24 点的使用时间轴喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：时间轴会暴露应用使用明细，同样要求口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 时区偏移，默认按东八区喵
        tz_offset = _parse_bounded_int(request.query_params.get("tz_offset_minutes"), default=480, minimum=-720, maximum=840)
        # 合并间隔，默认 15 分钟，和 patina 的 AFK 阈值一致喵
        merge_gap = _parse_bounded_int(request.query_params.get("merge_gap_seconds"), default=5, minimum=0, maximum=7200)
        # 把本地日期换算成 UTC 窗口喵
        day_range = _day_range_utc(request.query_params.get("date"), tz_offset)
        # 喵~防御：日期格式不对时给出明确提示喵
        if day_range is None:
            return _error_response(422, "invalid_payload", "date 必须是 YYYY-MM-DD 格式")
        # 线程池里查时间轴喵
        payload = await run_in_threadpool(_load_day_timeline, active_config, [device_id], day_range, tz_offset, merge_gap)
        # 返回时间轴喵
        return JSONResponse(content={"ok": True, **payload})

    @application.get("/api/v1/devices/{device_id}")
    async def device_detail(request: Request, device_id: str) -> JSONResponse:
        """单台设备详情：硬件、电量曲线、使用时间轴与应用排行喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：需要口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        # 线程池里查详情喵
        detail = await run_in_threadpool(_load_device_detail, active_config, device_id)
        # 喵~防御：设备不存在时给 404 而不是空对象喵
        if detail is None:
            return _error_response(404, "not_found", f"设备 {device_id} 不存在")
        # 返回详情喵
        return JSONResponse(content={"ok": True, **detail})

    @application.post("/api/v1/devices/{device_id}/role")
    async def update_role(request: Request, device_id: str) -> JSONResponse:
        """在看板里把设备标记为服务器或工作站喵。"""
        # 取当前配置喵
        active_config: AppConfig = request.app.state.config
        # 喵~防御：改角色属于写操作，必须校验口令喵
        if not _verify_token(request, active_config):
            return _error_response(401, "invalid_token", "X-Ingest-Token 缺失或不匹配")
        try:
            # 读取请求体喵
            body = await request.json()
        except ValueError:
            # 喵~防御：不是合法 JSON 时给出明确提示喵
            return _error_response(422, "invalid_payload", "请求体必须是 JSON 对象，例如 {\"role\": \"server\"}")
        # 取角色字段喵
        role = body.get("role") if isinstance(body, dict) else None
        # 喵~防御：只接受两个合法角色喵
        if role not in ("server", "workstation"):
            return _error_response(422, "invalid_payload", "role 只能是 server 或 workstation")
        # 线程池里执行更新喵
        updated = await run_in_threadpool(_set_device_role, active_config, device_id, str(role))
        # 喵~防御：设备不存在时返回 404 喵
        if not updated:
            return _error_response(404, "not_found", f"设备 {device_id} 不存在")
        # 返回更新结果喵
        return JSONResponse(content={"ok": True, "device_id": device_id, "role": role})

    # 看板静态资源目录喵
    web_dir = Path(__file__).resolve().parent / "web"
    # 喵~防御：目录不存在时跳过挂载，保证接口测试不被前端文件影响喵
    if web_dir.is_dir():
        # 静态资源挂在 /static 下喵
        application.mount("/static", NoCacheStaticFiles(directory=str(web_dir)), name="static")

        @application.get("/")
        async def dashboard_page() -> FileResponse:
            """返回看板首页喵。"""
            # 直接返回单页应用入口喵
            return FileResponse(web_dir / "index.html")

    return application


def _load_devices(config: AppConfig) -> list[queries.DeviceSummary]:
    """线程内查询设备列表的小工具函数喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 复用查询层的列表函数喵
        return queries.list_devices(connection)
    finally:
        # 关闭连接喵
        connection.close()


def _serialize_summary(item: queries.DeviceSummary) -> dict[str, object]:
    """把设备概要转成可 JSON 序列化的字典喵。"""
    # 逐字段转换，时间统一 ISO 文本喵
    return {
        "device_id": item.device_id,
        "platform": item.platform,
        "display_name": item.display_name,
        "os_version": item.os_version,
        "last_seen_at": item.last_seen_at.isoformat(),
        "online": queries.is_online(item.last_seen_at),
        "role": item.role,
        "tag": item.tag,
        "rdp_connected": item.rdp_connected,
        "stats_paused_reason": item.stats_paused_reason,
        "stats_paused_text": reason_text(item.stats_paused_reason) if item.stats_paused_reason else "",
    }


def _serialize_battery(snapshot: queries.BatterySnapshot | None) -> dict[str, object] | None:
    """把电量快照转成字典，没有数据时返回 None 喵。"""
    # 喵~防御：Windows 设备通常没有电量喵
    if snapshot is None:
        return None
    # 返回可序列化结构喵
    return {
        "percent": snapshot.percent,
        "charging": snapshot.charging,
        "sampled_at": snapshot.sampled_at.isoformat(),
    }


def _serialize_current_app(snapshot: queries.CurrentAppSnapshot | None) -> dict[str, object] | None:
    """把当前应用转成字典喵。"""
    # 喵~防御：没有当前应用时返回 None 喵
    if snapshot is None:
        return None
    # since 可能为空喵
    return {
        "name": snapshot.name,
        "package": snapshot.package,
        "since": snapshot.since.isoformat() if snapshot.since else None,
    }


def _icon_key_of(icon_keys: dict[tuple[str, str], str], app: str, package: str) -> str:
    """从预取的图标键映射里取某个应用的键喵。

    输入：current_icon_keys() 的结果、应用名、包名。
    输出：图标键；库里没有这张图标时返回空串，前端会退回色块喵。
    边界：查找用的规范化规则与 icons.icon_key() 一致，包名大小写不敏感喵。
    """
    # 喵~防御：查不到就给空串，绝不能现算一个库里不存在的假键（那会让前端 404）喵
    return icon_keys.get(icons.normalize_identity(app, package), "")


def _serialize_usage(entry: queries.UsageEntry, icon_keys: dict[tuple[str, str], str]) -> dict[str, object]:
    """把应用排行条目转成字典喵。"""
    # 带上包名，看板可以显示更精确的信息喵
    # 同时给出图标键，前端才能拼出 /api/v1/icons/<key> 的图片地址喵
    return {
        "app": entry.app,
        "package": entry.package,
        "seconds": entry.seconds,
        # 喵~注意：键现在含图标内容哈希，只能从库里查；没有图标时给空串，前端退回色块喵
        "icon_key": _icon_key_of(icon_keys, entry.app, entry.package),
    }


def _load_seen_users(config: AppConfig) -> list[dict[str, object]]:
    """线程内读出最近发言的人喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 查最近活跃的发言人喵
        rows = bot_users.list_seen_users(connection)
        # 转成前端要的字典喵
        return [bot_users.to_payload(row) for row in rows]
    finally:
        # 关闭连接喵
        connection.close()


def _load_dashboard(config: AppConfig) -> list[dict[str, object]]:
    """线程内组装看板卡片数据喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 查询看板数据喵
        cards = queries.dashboard_devices(connection)
        # 喵~注意：图标键一次查全表拿到，避免每张卡片、每个应用都单独查库喵
        icon_keys = icons.current_icon_keys(connection)
        # 逐张卡片序列化喵
        return [
            {
                **_serialize_summary(card.summary),
                "battery": _serialize_battery(card.battery),
                "current_app": _serialize_current_app(card.current_app),
                "usage_total_seconds": card.usage_total_seconds,
                "usage_top": [_serialize_usage(item, icon_keys) for item in card.usage_top],
            }
            for card in cards
        ]
    finally:
        # 关闭连接喵
        connection.close()


def _load_device_detail(config: AppConfig, device_id: str) -> dict[str, object] | None:
    """线程内组装单台设备详情喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 查详情喵
        detail = queries.get_device(connection, device_id)
        # 喵~防御：设备不存在时返回 None，由路由层给 404 喵
        if detail is None:
            return None
        # 取近 24 小时排行喵
        ranking = queries.usage_ranking(connection, device_id, hours=24)
        # 取电量曲线喵
        battery_points = queries.battery_series(connection, device_id, hours=24)
        # 取使用时间轴喵
        timeline = queries.usage_timeline(connection, device_id, hours=24)
        # 喵~注意：图标键一次查全表拿到，详情页一次只渲染一次喵
        icon_keys = icons.current_icon_keys(connection)
        # 组装响应喵
        return {
            **_serialize_summary(detail.summary),
            "hardware": detail.hardware,
            "battery": _serialize_battery(detail.battery),
            "current_app": _serialize_current_app(detail.current_app),
            "usage_total_seconds": detail.usage_total_seconds,
            "usage_ranking": [_serialize_usage(item, icon_keys) for item in ranking],
            "mirrored_tags": list(detail.mirrored_tags),
            "mirror_foreground": detail.mirror_foreground,
            "battery_series": [
                {"sampled_at": point.sampled_at.isoformat(), "percent": point.percent, "charging": point.charging}
                for point in battery_points
            ],
            "usage_timeline": [
                {"bucket_start": bucket.bucket_start.isoformat(), "seconds": bucket.seconds}
                for bucket in timeline
            ],
        }
    finally:
        # 关闭连接喵
        connection.close()


def _parse_positive_int(raw: str | None, default: int, minimum: int, maximum: int) -> int:
    """把查询参数解析成限定范围内的整数喵。

    输入：原始字符串、默认值、下限、上限。
    输出：夹到范围内的整数；解析失败时返回默认值。
    """
    # 喵~防御：没传参数就用默认值喵
    if raw is None:
        return default
    try:
        # 尝试解析成整数喵
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        # 喵~防御：乱传参数时退回默认值，不抛 422 打扰前端喵
        return default
    # 夹到合法范围喵
    return max(minimum, min(maximum, value))


def _serialize_global_usage(
    entry: queries.GlobalUsageEntry, icon_keys: dict[tuple[str, str], str]
) -> dict[str, object]:
    """把一条跨设备排行序列化成前端用的字典喵。

    输入：GlobalUsageEntry、预取的图标键映射。
    输出：含应用名、包名、秒数、设备数与设备名列表的字典。
    边界：包名为空时原样返回空串；库里没有图标时 icon_key 为空串喵。
    """
    # 图标键只能查库（键里含内容哈希），没有就给空串让前端退回色块喵
    return {
        "app": entry.app,
        "package": entry.package,
        "seconds": entry.seconds,
        "device_count": entry.device_count,
        "devices": list(entry.devices),
        # 按设备拆开的秒数，看板用它把一条时间条切成几段、每段一种深浅喵
        "device_seconds": [{"device": name, "seconds": seconds} for name, seconds in entry.device_seconds],
        # 喵~注意：查不到图标时给空串，不能现算假键喵
        "icon_key": _icon_key_of(icon_keys, entry.app, entry.package),
    }


def _load_rankings(
    config: AppConfig,
    hours: int,
    limit: int,
    scope: str = "all",
    device_ids: list[str] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """线程内查询跨设备应用排行，按口径返回总排行与分组明细喵。

    输入：配置、窗口小时数、每组条数上限、口径（all/device/group）、可选设备范围。
    输出：(总排行列表, 分组列表)；scope=all 时分组为空列表。
    边界：非法口径按 all 处理；设备组文件坏掉时按没有分组处理；
          device_ids 为 None 表示不限定设备喵。
    """
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 只有设备组口径才需要读 people.json，其它口径省一次文件 IO 喵
        groups = people.load_people(config.server.db_path) if scope == "group" else []
        # 查询总排行与分组明细喵
        entries, ranking_groups = queries.scoped_usage_ranking(
            connection,
            scope=scope,
            groups=groups,
            hours=hours,
            limit=limit,
            device_ids=device_ids,
        )
        # 喵~注意：总排行与分组明细共用同一份图标键映射，一屏几百条也只查一次库喵
        icon_keys = icons.current_icon_keys(connection)
        # 逐条序列化总排行喵
        serialized_entries = [_serialize_global_usage(entry, icon_keys) for entry in entries]
        # 逐组序列化分组明细喵
        serialized_groups = [
            {
                "key": group.key,
                "label": group.label,
                "kind": group.kind,
                "seconds": group.seconds,
                "entries": [_serialize_global_usage(entry, icon_keys) for entry in group.entries],
            }
            for group in ranking_groups
        ]
        # 返回总排行与分组明细喵
        return serialized_entries, serialized_groups
    finally:
        # 关闭连接喵
        connection.close()


def _parse_optional_int(value: object) -> int | None:
    """把可选字段解析成整数，解析不了时返回 None 喵。"""
    # 喵~防御：空值与布尔值都不当作整数喵
    if value is None or isinstance(value, bool):
        return None
    try:
        # 尝试转成整数喵
        return int(str(value).strip())
    except (TypeError, ValueError):
        # 喵~防御：解析失败交给调用方决定怎么提示喵
        return None


def _parse_optional_key(value: object) -> str | None:
    """把可选字段解析成字符串标识，空值时返回 None 喵。"""
    # 喵~防御：空值与布尔值都不当作标识喵
    if value is None or isinstance(value, bool):
        return None
    # 转成字符串并去掉首尾空白喵
    text = str(value).strip()
    # 空串等于没填喵
    return text or None


def _mask_secret(secret: str) -> str:
    """把凭据打码，只留前 4 位方便主人核对喵。"""
    # 喵~防御：没配置时直接返回空串喵
    if not secret:
        return ""
    # 太短就整体打码，避免泄露喵
    if len(secret) <= 4:
        return "*" * len(secret)
    # 保留前 4 位，其余打码喵
    return f"{secret[:4]}{'*' * 6}"


def _run_bot_simulation(
    config: AppConfig,
    text: str,
    group_id: int | str | None,
    user_id: int | str | None,
    channel: str = "napcat",
    mentioned: bool = True,
    role: str = "member",
) -> dict[str, object]:
    """线程内跑一次命令测试并把结果序列化喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 跑模拟喵
        result = simulate.simulate_command(
            connection,
            config,
            text,
            group_id=group_id,
            user_id=user_id,
            channel=channel,
            mentioned=mentioned,
            role=role,
        )
        # 图片转成 data URI，前端可以直接当 src 用喵
        image_data_uri = None
        if result.image:
            encoded = base64.b64encode(result.image).decode("ascii")
            image_data_uri = f"data:image/png;base64,{encoded}"
        # 组装返回字典喵
        return {
            "replied": result.replied,
            "reason": result.reason,
            "reason_text": result.reason_text,
            "command_text": result.command_text,
            "command_name": result.command_name,
            "text": result.text,
            "image_data_uri": image_data_uri,
            "image_bytes": len(result.image) if result.image else 0,
            "elapsed_ms": result.elapsed_ms,
            "channel": result.channel,
        }
    finally:
        # 关闭连接喵
        connection.close()


def _storage_stats(config: AppConfig) -> dict[str, object]:
    """线程内统计存储占用喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 统计喵
        return storage.collect_stats(connection, config.server.db_path)
    finally:
        # 关闭连接喵
        connection.close()


def _storage_cleanup(config: AppConfig, before_days: int, targets: tuple[str, ...]) -> dict[str, int]:
    """线程内执行历史清理喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 清理喵
        return storage.cleanup(connection, before_days, targets)
    finally:
        # 关闭连接喵
        connection.close()


def _device_windows(config: AppConfig, device_id: str, row_limit: int) -> dict[str, object] | None:
    """线程内查某台设备最近一次窗口快照喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 先确认设备存在喵
        exists = connection.execute(
            "SELECT 1 FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
        # 喵~防御：没有这台设备就返回 None 让接口层回 404 喵
        if exists is None:
            return None
        # 取最近一次上报时间喵
        latest = connection.execute(
            "SELECT MAX(reported_at) FROM window_samples WHERE device_id = ?", (device_id,)
        ).fetchone()
        # 喵~防御：从来没有窗口数据时返回空列表喵
        latest_at = latest[0] if latest and latest[0] else ""
        if not latest_at:
            return {"device_id": device_id, "reported_at": "", "windows": []}
        # 取该次快照的所有窗口喵
        rows = connection.execute(
            """
            SELECT app_name, package, title, minimized, foreground
            FROM window_samples
            WHERE device_id = ? AND reported_at = ?
            ORDER BY foreground DESC, minimized ASC, app_name ASC
            LIMIT ?
            """,
            (device_id, latest_at, row_limit),
        ).fetchall()
        # 喵~注意：图标键一次查全表拿到，窗口列表可能有几十条喵
        icon_keys = icons.current_icon_keys(connection)
        # 组装响应喵
        return {
            "device_id": device_id,
            "reported_at": latest_at,
            "windows": [
                {
                    "app": str(row["app_name"]),
                    "package": str(row["package"] or ""),
                    "title": str(row["title"] or ""),
                    "minimized": bool(row["minimized"]),
                    "foreground": bool(row["foreground"]),
                    # 喵~注意：没有图标的应用给空串，前端退回色块喵
                    "icon_key": _icon_key_of(icon_keys, str(row["app_name"]), str(row["package"] or "")),
                }
                for row in rows
            ],
        }
    finally:
        # 关闭连接喵
        connection.close()


def _verify_query_token(request: Request, config: AppConfig) -> bool:
    """允许把口令放在查询串里，供 <img> 这类带不了请求头的地方使用喵。"""
    # 取查询串里的口令喵
    raw = request.query_params.get("token", "")
    # 喵~防御：没有口令直接失败喵
    if not raw:
        return False
    # 常量时间比较，避免时序侧信道喵
    # 喵~注意：同 _verify_token，先编 bytes 再比，否则中文口令会 500 而不是 401 喵
    return hmac.compare_digest(raw.encode("utf-8"), config.ingest.token.encode("utf-8"))


def _save_icon(config: AppConfig, app: str, package: str, png_bytes: bytes) -> str:
    """线程内写一张图标喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 落库并返回键喵
        return icons.save_icon(connection, app, package, png_bytes)
    finally:
        # 关闭连接喵
        connection.close()


def _list_icons(config: AppConfig) -> list[dict[str, str]]:
    """线程内列出已有图标喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 返回列表喵
        return icons.list_icons(connection)
    finally:
        # 关闭连接喵
        connection.close()


def _rekey_icon_keys(config: AppConfig) -> None:
    """启动时按当前规则重算图标键，返回改动的行数写进日志喵。

    喵~注意：键里加了图标内容哈希之后，旧库里每一行的键都必然与新规则对不上，
    所以首次启动会把所有行重建一遍——这是预期行为，迁移完就稳定了喵。
    """
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 交给图标模块处理喵
        changed = icons.rekey_icons(connection)
    except sqlite3.Error as error:
        # 喵~防御：迁移失败不能挡住启动，最多图标对不上喵
        LOGGER.warning("图标键迁移失败：%s", error)
        return
    finally:
        # 关连接喵
        connection.close()
    # 有改动时打一条日志，方便主人核对喵
    if changed:
        LOGGER.info("已按新规则重算 %d 张应用图标的键", changed)


def _load_icon(config: AppConfig, key: str) -> bytes | None:
    """线程内按键取图标喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 返回图片字节喵
        return icons.load_icon(connection, key)
    finally:
        # 关闭连接喵
        connection.close()


def _parse_bounded_int(raw: str | None, default: int, minimum: int, maximum: int) -> int:
    """把查询参数解析成限定范围内的整数喵。

    输入：原始字符串、默认值、下限、上限。
    输出：夹到范围内的整数；解析失败时返回默认值。
    """
    # 喵~防御：没传参数就用默认值喵
    if raw is None:
        return default
    try:
        # 尝试解析成整数喵
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        # 喵~防御：乱传参数时退回默认值喵
        return default
    # 夹到合法范围喵
    return max(minimum, min(maximum, value))


def _parse_positive_int(raw: str | None, default: int, minimum: int, maximum: int) -> int:
    """兼容旧调用：解析成正整数喵。"""
    # 直接复用带边界版本喵
    return _parse_bounded_int(raw, default, minimum, maximum)


def _day_range_utc(date_text: str | None, tz_offset_minutes: int) -> tuple[datetime, datetime, str] | None:
    """把本地日期换算成 UTC 窗口喵。

    输入：YYYY-MM-DD 文本（可为空表示今天）、时区偏移分钟数。
    输出：(窗口起点, 窗口终点, 本地日期文本)；日期非法时返回 None。
    """
    # 构造本地时区喵
    local_tz = timezone(timedelta(minutes=tz_offset_minutes))
    if date_text:
        try:
            # 按 YYYY-MM-DD 解析喵
            local_day = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=local_tz)
        except ValueError:
            # 喵~防御：格式不对交给调用方报错喵
            return None
    else:
        # 没传日期就用授时时钟算出来的本地今天喵
        local_day = get_clock().now().astimezone(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    # 换算成 UTC 窗口喵
    start = local_day.astimezone(timezone.utc)
    end = (local_day + timedelta(days=1)).astimezone(timezone.utc)
    return start, end, local_day.strftime("%Y-%m-%d")


def _load_day_timeline(
    config: AppConfig,
    device_ids: list[str],
    day_range: tuple[datetime, datetime, str],
    tz_offset_minutes: int,
    merge_gap_seconds: int,
) -> dict[str, object]:
    """线程内查询某天的时间轴并按本地小时分桶喵。"""
    # 授时快照取一次，返回体里要用喵
    clock_snapshot = get_clock().snapshot()
    # 拆出窗口与日期喵
    start, end, date_text = day_range
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 喵~注意：合并视图（全部设备 / 设备组）按优先级把重叠时段裁给靠前的设备，
        # 几张设备的记录合起来才像「一个人」的时间轴；而单设备视图不需要裁剪喵
        merged_view = len(device_ids) > 1
        # 查连续段：泳道口径保留重叠，合并口径按优先级裁剪喵
        if merged_view:
            segments = queries.day_usage_segments(connection, device_ids, start, end, merge_gap_seconds)
            # 喵~注意：顶层色块要按优先级裁，否则同一时刻会叠两层颜色；
            # 但**应用轴**必须保留每台设备的完整记录——低优先级设备的应用
            # 在裁剪口径下会整段消失，图上就看不到那台设备到底用了什么喵
            lane_segments = queries.day_usage_lanes(connection, device_ids, start, end, merge_gap_seconds)
        else:
            segments = queries.day_usage_lanes(connection, device_ids, start, end, merge_gap_seconds)
            # 单设备不需要两套数据，应用轴直接复用喵
            lane_segments = segments
        # 查心跳，用来区分「离线（没有心跳）」和「空档（在线但无使用记录）」喵
        heartbeats = queries.day_heartbeats(connection, device_ids, start, end)
        # 设备 ID 到展示名的映射，给聚合泳道标设备名喵
        device_names = queries.device_name_map(connection)
        # 同应用不同窗口标题的区间，指针悬浮时显示标题用喵
        title_spans = queries.day_title_spans(
            connection, device_ids, start, end, clamp_end=min(end, utc_now())
        )
        # 喵~注意：时间轴一屏几十上百段，图标键必须一次查全表，逐段查库会拖慢接口喵
        icon_keys = icons.current_icon_keys(connection)
    finally:
        # 关闭连接喵
        connection.close()
    # 本地时区喵
    local_tz = timezone(timedelta(minutes=tz_offset_minutes))
    # 24 个小时桶喵
    hour_totals = [0.0] * 24
    # 逐段按比例摊到小时桶里喵
    for segment in segments:
        span = max(1.0, (segment.end - segment.start).total_seconds())
        ratio = segment.seconds / span
        cursor = segment.start
        while cursor < segment.end:
            local_moment = cursor.astimezone(local_tz)
            next_hour_local = local_moment.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            chunk_end = min(segment.end, next_hour_local.astimezone(timezone.utc))
            hour_totals[local_moment.hour] += (chunk_end - cursor).total_seconds() * ratio
            cursor = chunk_end
    # 喵~注意：总时长按时间轴并集算，不能把 segment.seconds 直接相加——
    # 段被窗口夹过之后仍保留原始采样时长，直接相加会把重叠部分重复计入喵
    total_seconds = queries.union_seconds(segments)
    # 喵~防御：心跳只保留 retention.detail_days 天，更早的日期没有心跳可查，判不出离线喵
    if end > utc_now() - timedelta(days=config.retention.detail_days):
        # 喵~防御：今天的窗口只算到此刻，否则未来的时间会被当成离线喵
        presence_end = min(end, utc_now()) if end > utc_now() else end
        # 按分钟判定在线状态，得到离线区间与空档区间喵
        states, offline_seconds, afk_seconds = presence.build_presence(
            heartbeats,
            start,
            presence_end,
            timeout_seconds=HEARTBEAT_TIMEOUT_SECONDS,
            usage_spans=[(segment.start, segment.end) for segment in segments],
            # 喵~注意：旧方案 A 的"按容差补缝"已停用，空档边界改用客户端给的 afk_since / active_since 喵
        )
    else:
        # 超出心跳保留期，状态一律留空，避免看板编造「离线 24 小时」喵
        states, offline_seconds, afk_seconds = [], 0, 0
    # 空档沿用 idle_seconds 字段名，语义是「在线但无使用记录」喵
    idle_seconds = afk_seconds
    # 组装返回喵
    return {
        "devices": list(device_ids),
        "date": date_text,
        "tz_offset_minutes": tz_offset_minutes,
        "merge_gap_seconds": merge_gap_seconds,
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
        "total_seconds": total_seconds,
        "idle_seconds": idle_seconds,
        "offline_seconds": offline_seconds,
        "afk_seconds": afk_seconds,
        "heartbeat_timeout_seconds": HEARTBEAT_TIMEOUT_SECONDS,
        # 服务端授时时钟的"现在"，看板据此画现在线，不信任浏览器时钟喵
        "server_now": get_clock().now().isoformat().replace("+00:00", "Z"),
        # 授时状态：来源、偏移、是否已对齐喵
        "clock": {
            "source": clock_snapshot.source,
            "offset_seconds": clock_snapshot.offset_seconds,
            "synced": clock_snapshot.synced,
        },
        "states": [
            {
                "kind": interval.kind,
                "start": interval.start.isoformat().replace("+00:00", "Z"),
                "end": interval.end.isoformat().replace("+00:00", "Z"),
                "seconds": interval.seconds,
            }
            for interval in states
        ],
        "hours": [int(round(value)) for value in hour_totals],
        "segments": [
            {
                "app": segment.app,
                "package": segment.package,
                # 喵~注意：没有图标的应用给空串，前端退回色块，不会去请求一个假键喵
                "icon_key": _icon_key_of(icon_keys, segment.app, segment.package),
                "start": segment.start.isoformat().replace("+00:00", "Z"),
                "end": segment.end.isoformat().replace("+00:00", "Z"),
                "seconds": segment.seconds,
                "device_name": device_names.get(segment.device_id, segment.device_id),
            }
            for segment in segments
        ],
        # 喵~注意：应用轴专用的一份数据，保留每台设备的完整记录、不按优先级裁剪。
        # 顶层色块仍用上面的 segments（裁剪过的），两者分工不同喵
        "lane_segments": [
            {
                "app": segment.app,
                "package": segment.package,
                "icon_key": _icon_key_of(icon_keys, segment.app, segment.package),
                "start": segment.start.isoformat().replace("+00:00", "Z"),
                "end": segment.end.isoformat().replace("+00:00", "Z"),
                "seconds": segment.seconds,
                "device_name": device_names.get(segment.device_id, segment.device_id),
            }
            for segment in lane_segments
        ],
        "title_spans": [
            {
                "app": span.app,
                "title": span.title,
                "start": span.start.isoformat().replace("+00:00", "Z"),
                "end": span.end.isoformat().replace("+00:00", "Z"),
            }
            for span in title_spans
        ],
    }


def _set_device_role(config: AppConfig, device_id: str, role: str) -> bool:
    """线程内更新设备角色喵。"""
    # 打开连接喵
    connection = db.connect(config.server.db_path)
    try:
        # 复用查询层的更新函数喵
        return queries.set_device_role(connection, device_id, role)
    finally:
        # 关闭连接喵
        connection.close()


# 模块级应用实例，供 `uvicorn app.main:app` 使用喵
app = create_app()


def _run_server() -> None:
    """按配置里的监听参数直接启动服务，供重启功能与本地调试使用喵。"""
    # 延迟导入 uvicorn，避免只做导入时拉起依赖喵
    import uvicorn

    # 读一份最新配置喵
    config = load_config()
    # 直接传应用对象，避免 uvicorn 再导入一次模块喵
    uvicorn.run(app, host=config.server.host, port=config.server.port, log_level=config.server.log_level)


if __name__ == "__main__":
    # 支持 `python -m app.main` 直接起服务喵
    _run_server()
