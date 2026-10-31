"""命令行调试工具：不经过 QQ，直接看某条命令会渲染出什么。

用途：改文案或排查"群里没反应"时，先在这里确认渲染逻辑本身是好的喵。

用法：
    python -m scripts.demo_bot "/happy设备"
    python -m scripts.demo_bot "/happy干了什么"
"""

from __future__ import annotations

import sys
from dataclasses import replace

from app import db
from app.bot import router
from app.config import load_config

# 调试用的假群号与假用户号喵
DEMO_GROUP = 111111
DEMO_USER = 333333


def build_event(text: str, self_qq: str) -> dict:
    """构造一条 @机器人 的群消息事件喵。"""
    # 结构与 NapCat 推送的真实事件保持一致喵
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": DEMO_GROUP,
        "user_id": DEMO_USER,
        "self_id": int(self_qq),
        "message": [
            {"type": "at", "data": {"qq": self_qq}},
            {"type": "text", "data": {"text": text}},
        ],
    }


def main(argv: list[str]) -> int:
    """把命令渲染结果打印到控制台喵。"""
    # 喵~防御：没给命令时提示用法喵
    if not argv:
        print("用法：python -m scripts.demo_bot \"/happy设备\"")
        return 2
    # 读配置喵
    config = load_config()
    # 调试时临时把当前群加进白名单，避免"因为白名单为空所以不回复"干扰判断喵
    debug_config = replace(
        config,
        acl=replace(config.acl, whitelist_groups=(DEMO_GROUP,)),
    )
    # 构造事件喵
    event = build_event(argv[0], config.napcat.self_qq)
    # 走一遍真实的路由逻辑，拿到去掉前缀的命令文本喵
    should_reply, command_text, group_id, user_id = router.inspect_event(event, debug_config)
    # 打印路由判断结果喵
    print(f"should_reply={should_reply} group_id={group_id} user_id={user_id}")
    # 喵~防御：不该响应时不用查库，直接返回喵
    if not should_reply:
        return 1
    # 打开数据库连接喵
    connection = db.connect(debug_config.server.db_path)
    try:
        # 复用真实的渲染逻辑，输出与群里看到的一致喵
        reply_text = router.build_reply(connection, debug_config, command_text)
    finally:
        # 关闭连接喵
        connection.close()
    # 打印渲染结果喵
    print("-" * 40)
    print(reply_text)
    return 0


if __name__ == "__main__":
    # 用命令行参数作为命令文本喵
    sys.exit(main(sys.argv[1:]))
