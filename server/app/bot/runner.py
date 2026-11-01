"""把机器人通道、命令路由与数据库组装成可启动的后台任务。

服务端是一个进程：FastAPI 处理上报，本模块在同一个事件循环里跑机器人，
好处是部署简单，坏处是机器人异常不能影响上报接口，所以这里做了完整兜底喵。

通道是可插拔的：NapCat（OneBot 11）与官方 QQ Bot 并存，
业务层只认 NormalizedMessage，不关心底层协议喵。
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

from .. import db, queries
from ..config import AppConfig
from . import router, users
from .channel import (
    CHANNEL_NAPCAT,
    CHANNEL_QQBOT,
    SCOPE_GROUP,
    BotChannel,
    ChannelError,
    NormalizedMessage,
)
from .napcat import NapCatChannel
from .qqbot import QQBotChannel

# 模块日志器喵
LOGGER = logging.getLogger("device_hub.bot")

# 清理过期数据的间隔秒数，一小时一次喵
PRUNE_INTERVAL_SECONDS = 3600

# 发送失败时可以退回文本的异常集合喵
SEND_ERRORS = (ConnectionError, asyncio.TimeoutError, ChannelError, OSError)

# 忙时回给群里的话喵
# 喵~注意：这里只是「告诉对方现在忙」，没有任何排队或稍后补发的机制喵
BUSY_REPLY_TEXT = "稍等，正在处理上一个命令，这条先不处理了，等会再发一次吧。"


class BotRunner:
    """机器人后台任务，负责启动通道、处理消息、定期清理喵。"""

    def __init__(self, config: AppConfig) -> None:
        # 保存配置引用喵
        self._config = config
        # 已启用的通道，键是通道名喵
        self._channels: dict[str, BotChannel] = {}
        # 命令与截图同一时刻只允许跑一个喵
        # 喵~注意：截图要起无头浏览器，一次 4–9 秒还吃满一个 CPU 核；
        # 两个命令撞在一起时浏览器互相抢资源，容易双双超时拍出空白图喵
        # 这里用普通布尔标志而不是 asyncio.Lock：需要的是「抢不到就立刻让路」，
        # 而 Lock 的获取是协程，await 前后会留出竞态空档喵
        self._busy = False
        # 当前正在处理的消息摘要，日志和排查用喵
        self._busy_text = ""
        # NapCat 通道，配置关闭时不创建喵
        if config.napcat.enabled:
            self._channels[CHANNEL_NAPCAT] = NapCatChannel(config, self._handle_message)
        # 官方 QQ Bot 通道，默认关闭喵
        if config.qqbot.enabled:
            self._channels[CHANNEL_QQBOT] = QQBotChannel(config, self._handle_message)

    def channel_names(self) -> list[str]:
        """当前启用的通道名列表喵。"""
        # 保持插入顺序，NapCat 在前喵
        return list(self._channels)

    def is_connected(self) -> bool:
        """任意一个通道连上就算在线，供看板显示喵。"""
        # 逐个通道判断喵
        return any(channel.is_connected() for channel in self._channels.values())

    def channel_status(self) -> list[dict[str, object]]:
        """逐通道的连接状态，供看板分开展示喵。"""
        # 组装成前端好用的结构喵
        return [
            {"name": name, "connected": channel.is_connected()}
            for name, channel in self._channels.items()
        ]

    async def run(self) -> None:
        """启动机器人主循环，直到被取消喵。"""
        # 喵~防御：一个通道都没启用时只跑清理任务，避免留下悬挂协程喵
        if not self._channels:
            LOGGER.warning("没有启用任何机器人通道（napcat.enabled 与 qqbot.enabled 都是 false）")
            await self._prune_loop()
            return
        # 把生效的白名单写进日志，方便主人核对喵
        self._log_access_control()
        # 每个通道一个任务喵
        channel_tasks = [
            asyncio.create_task(channel.run(), name=f"bot-channel-{name}")
            for name, channel in self._channels.items()
        ]
        # 清理任务喵
        prune_task = asyncio.create_task(self._prune_loop(), name="prune-loop")
        try:
            # 任一任务异常都会在这里抛出喵
            await asyncio.gather(*channel_tasks, prune_task)
        finally:
            # 退出时取消所有子任务，避免留下悬挂协程喵
            for task in (*channel_tasks, prune_task):
                task.cancel()
            # 等待取消真正生效喵
            await asyncio.gather(*channel_tasks, prune_task, return_exceptions=True)

    def _log_access_control(self) -> None:
        """把每个通道的白名单打进日志喵。"""
        # NapCat 用整数群号喵
        if CHANNEL_NAPCAT in self._channels:
            # 喵~防御：白名单为空时提前把原因写进日志喵
            if not self._config.acl.whitelist_groups:
                LOGGER.warning("acl.whitelist_groups 为空，NapCat 通道不会响应任何群消息")
            else:
                LOGGER.info(
                    "NapCat 白名单群：%s",
                    ", ".join(str(group_id) for group_id in self._config.acl.whitelist_groups),
                )
        # 官方通道用 openid 喵
        if CHANNEL_QQBOT in self._channels:
            # 喵~防御：openid 白名单为空时群里 @ 也不会响应喵
            if not self._config.acl.whitelist_group_openids:
                LOGGER.warning("acl.whitelist_group_openids 为空，官方 QQ Bot 不会响应任何群消息")
            else:
                LOGGER.info("官方 QQ Bot 白名单群：%s", ", ".join(self._config.acl.whitelist_group_openids))

    async def _handle_message(self, message: NormalizedMessage) -> None:
        """处理一条归一化消息喵。"""
        # 判断是否该响应，并取出命令文本与原因码喵
        should_reply, command_text, reason = router.inspect_normalized(message, self._config)
        # 喵~注意：开着 debug_events 时把准入结论打出来，能直接看出卡在哪一道闸门喵
        if self._config.qqbot.debug_events:
            LOGGER.info(
                "准入决策：channel=%s text=%r mentioned=%s should_reply=%s reason=%s 命令=%r",
                message.channel,
                message.text,
                message.mentioned,
                should_reply,
                reason,
                command_text,
            )
        # 喵~防御：不该响应的消息直接返回，保持安静喵
        if not should_reply:
            LOGGER.debug("忽略 %s 消息（%s）", message.channel, reason)
            return
        # 找到消息所属通道喵
        channel = self._channels.get(message.channel)
        # 喵~防御：通道被关掉后残留的消息直接丢弃喵
        if channel is None:
            return
        # 喵~注意：命令与截图同一时刻只跑一个，忙的时候这条直接丢弃喵
        # 喵~防御：判断与占位必须在同一段同步代码里做完，中间不能 await，
        # 否则两条消息同时到达时两边都看到「空闲」，于是各跑各的喵
        if not self._try_occupy_busy():
            LOGGER.info(
                "已有命令在处理（%s），丢弃并发命令：%s", self._busy_text or "未知", command_text
            )
            await self._send_busy(channel, message)
            return
        self._busy_text = command_text
        try:
            await self._run_command(channel, message, command_text)
        finally:
            # 喵~防御：无论成功失败都要让出位置，否则机器人会永远卡在忙喵
            self._busy_text = ""
            self._release_busy()

    def _try_occupy_busy(self) -> bool:
        """同步地抢占忙位，抢不到立刻返回 False 喵。

        输入：无。
        输出：True 表示这次由我来跑，False 表示别人正在跑。
        边界：纯同步、无 await，所以判断与占位之间不会有交错喵。
        """
        # 已经有人在跑就直接让路喵
        if self._busy:
            return False
        # 喵~注意：普通赋值就是原子的，这里占住之后别的消息会看到 True 喵
        self._busy = True
        return True

    def _release_busy(self) -> None:
        """释放忙位喵。

        输入：无。
        输出：无。
        边界：没被占用时什么也不做喵。
        """
        # 复位标志，下一条消息就能跑喵
        self._busy = False

    async def _send_busy(self, channel: BotChannel, message: NormalizedMessage) -> None:
        """忙时告诉对方这条不处理了喵。

        输入：通道、原始消息。
        输出：无。
        边界：只发一次提示，**不排队、不重试、不承诺补发**喵。

        喵~注意：多任务同时进来时不做队列，除了正在跑的那条，其余全部丢弃。
        截图一次要起浏览器、占满一个核，排队只会让所有人一起等，
        还不如让对方过会儿自己再发一次喵。
        """
        # 群里回复时尽量 @ 提问的人，单聊不需要喵
        mention_key = message.user_key if message.scope == SCOPE_GROUP else None
        try:
            # 发送「稍等」提示喵
            await channel.send_text(
                message.group_key,
                BUSY_REPLY_TEXT,
                scope=message.scope,
                reply_token=message.reply_token,
                mention_user_key=mention_key,
            )
        except SEND_ERRORS as send_error:
            # 喵~防御：忙时提示发不出去也不影响主流程喵
            LOGGER.warning("回复 %s 的「稍等」失败：%s", message.group_key, send_error)

    async def _run_command(
        self,
        channel: BotChannel,
        message: NormalizedMessage,
        command_text: str,
    ) -> None:
        """真正执行一条命令：记账、出图或出文本、发送喵。

        输入：通道、原始消息、命令文本。
        输出：无。
        边界：调用方必须已持有 busy 锁喵。
        """
        # 喵~注意：只记真正执行了命令的人，方便在看板里反查 openid 拉黑喵
        # 这一步放在 ACL 之后，被拦下的消息不会占存储喵
        await asyncio.to_thread(self._record_seen, message)
        # 先尝试生成图片，命令里带"图"字才会真的渲染喵
        image_bytes = await asyncio.to_thread(self._build_image, command_text)
        # 有图片就发图片，发送成功即可结束喵
        if image_bytes is not None:
            try:
                # 发送图片消息喵
                await channel.send_image(
                    message.group_key,
                    image_bytes,
                    scope=message.scope,
                    reply_token=message.reply_token,
                )
                return
            except SEND_ERRORS as image_error:
                # 喵~防御：图片发送失败时退回文本回复，不能什么都不回喵
                LOGGER.warning("回复 %s 的图片失败，改用文本：%s", message.group_key, image_error)
        # 查询与排版放在线程里执行，避免阻塞事件循环影响上报接口喵
        reply_text = await asyncio.to_thread(self._build_reply, command_text)
        # 喵~防御：没有内容可回时不发空消息喵
        if not reply_text:
            return
        # 群里回复时尽量 @ 提问的人，官方通道没有 at 字段会自动忽略喵
        mention_key = message.user_key if message.scope == SCOPE_GROUP else None
        try:
            # 发送回复喵
            await channel.send_text(
                message.group_key,
                reply_text,
                scope=message.scope,
                reply_token=message.reply_token,
                mention_user_key=mention_key,
            )
        except SEND_ERRORS as send_error:
            # 喵~防御：发送失败只记录日志，不能让机器人任务整体崩掉喵
            LOGGER.warning("回复 %s 失败：%s", message.group_key, send_error)

    def _build_image(self, command_text: str) -> bytes | None:
        """在线程里打开数据库并尝试生成图片喵。

        输入：命令文本。
        输出：PNG 字节流；命令不需要图片时返回 None。
        边界：数据库异常时返回 None，让调用方退回文本回复喵。
        """
        # 打开连接喵
        connection = db.connect(self._config.server.db_path)
        try:
            # 交给路由层判断是否需要图片喵
            return router.build_image(connection, self._config, command_text)
        except sqlite3.Error as database_error:
            # 喵~防御：图片渲染阶段的数据库异常同样只记日志并退回文本喵
            LOGGER.exception("渲染命令图片时数据库出错：%s", database_error)
            return None
        except OSError as render_error:
            # 喵~防御：字体或图片编码失败时退回文本，不能让命令彻底没回应喵
            LOGGER.warning("渲染命令图片失败：%s", render_error)
            return None
        finally:
            # 关闭连接喵
            connection.close()

    def _record_seen(self, message: NormalizedMessage) -> None:
        """在线程里记下这个发言人，供看板反查 openid 喵。

        输入：归一化消息。
        输出：无。
        边界：数据库异常只记日志，绝不能因为记账失败而不回复命令喵。
        """
        # 每条消息独立开连接，和 _build_reply 保持一致喵
        connection = db.connect(self._config.server.db_path)
        try:
            # 喵~注意：记的是「谁执行了命令」，昵称能拿到就存，拿不到留空喵
            users.record_seen(
                connection,
                message.channel,
                message.user_key,
                display_name=message.display_name,
                group_key=message.group_key,
                role=message.role,
                now=db.utc_now(),
            )
        except sqlite3.Error as database_error:
            # 喵~防御：记账失败不影响业务，打条日志就够喵
            LOGGER.warning("记录发言人失败：%s", database_error)
        finally:
            # 关闭连接喵
            connection.close()

    def _build_reply(self, command_text: str) -> str:
        """在线程里打开数据库并生成回复文本喵。"""
        # 每次命令独立开连接，SQLite 本地开销很小且天然线程安全喵
        connection = db.connect(self._config.server.db_path)
        try:
            # 交给路由层生成文本喵
            return router.build_reply(connection, self._config, command_text)
        except sqlite3.Error as database_error:
            # 喵~防御：数据库异常时给用户一句可读提示，同时把堆栈写进日志喵
            LOGGER.exception("处理命令时数据库出错：%s", database_error)
            return "服务端查询数据时出错，请稍后再试。"
        finally:
            # 关闭连接喵
            connection.close()

    async def _prune_loop(self) -> None:
        """定期清理过期数据喵。"""
        while True:
            # 先等待一个周期再清理，避免刚启动就占用数据库喵
            await asyncio.sleep(PRUNE_INTERVAL_SECONDS)
            try:
                # 清理动作放到线程里执行喵
                deleted_counts = await asyncio.to_thread(self._prune_once)
                # 记录本次清理结果喵
                LOGGER.info(
                    "清理过期数据：原始上报 %s 条，使用时长 %s 条，电量 %s 条",
                    deleted_counts.get("reports", 0),
                    deleted_counts.get("usage_samples", 0),
                    deleted_counts.get("battery_samples", 0),
                )
            except sqlite3.Error as prune_error:
                # 喵~防御：清理失败不影响主流程，下一个周期继续尝试喵
                LOGGER.warning("清理过期数据失败：%s", prune_error)

    def _prune_once(self) -> dict[str, int]:
        """执行一次清理并返回删除行数喵。"""
        # 打开连接喵
        connection = db.connect(self._config.server.db_path)
        try:
            # 复用查询层的清理函数喵
            counts = queries.prune_expired(
                connection,
                detail_days=self._config.retention.detail_days,
                aggregate_days=self._config.retention.aggregate_days,
            )
            # 喵~注意：发言人名单也按明细保留期清理，不然会无限长喵
            stale_cutoff = db.days_ago_text(self._config.retention.detail_days)
            counts["bot_seen_users"] = users.prune_seen_users(connection, stale_cutoff)
            return counts
        finally:
            # 关闭连接喵
            connection.close()
