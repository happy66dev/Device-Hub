"""让 `python -m agent` 可以直接启动采集端喵。

注意：这里用绝对导入，因为 PyInstaller 打包后本文件会被当成顶层脚本执行，
相对导入（from .main）会报 "attempted relative import with no known parent package" 喵。
"""

from __future__ import annotations

import sys

from agent.main import main

# 把命令行参数转交给 main，并用其返回值作为进程退出码喵
if __name__ == "__main__":
    sys.exit(main())
