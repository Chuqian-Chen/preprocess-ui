"""pytest 共享配置：把 server/ 加入 import 路径（后端模块用裸名互相 import）。"""

import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))
