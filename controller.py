# controller.py
import time
import subprocess as sp
from pathlib import Path


# 稳定调用 ADB（不会被路径空格影响）
def _run(adb_path, *args, check=False):
    """以列表参数方式调用 adb，避免空格路径问题。"""
    return sp.run([adb_path, *map(str, args)], capture_output=True, text=True, check=check)


# 截屏：先 exec-out，失败则回退 shell+pull
def get_screenshot(adb_path, save_path):
    """
    抓取屏幕并保存到 ./screenshot/screenshot.png
    成功后返回保存路径（字符串）。
    """
    out_path = Path(save_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # exec-out 直接写本地文件
    try:
        with open(out_path, "wb") as f:
            sp.run([adb_path, "exec-out", "screencap", "-p"], stdout=f, stderr=sp.PIPE, check=True)
    except sp.CalledProcessError as e:
        # 回退到 shell 保存到设备 + pull 回来
        dev_tmp = "/sdcard/screenshot.png"
        _run(adb_path, "shell", "rm", "-f", dev_tmp)  # 清理旧文件，忽略失败
        time.sleep(0.2)
        _run(adb_path, "shell", "screencap", "-p", dev_tmp, check=True)
        time.sleep(0.2)
        _run(adb_path, "pull", dev_tmp, str(out_path), check=True)
        _run(adb_path, "shell", "rm", "-f", dev_tmp)

    # 最终校验
    if (not out_path.exists()) or out_path.stat().st_size == 0:
        raise FileNotFoundError(f"ADB screencap failed; file not found: {out_path}")
    return str(out_path)


def tap(adb_path, x, y):
    _run(adb_path, "shell", "input", "tap", int(x), int(y))


def type(adb_path, text):
    text = text.replace("\\n", "_").replace("\n", "_")
    for char in text:
        if char == ' ':
            _run(adb_path, "shell", "input", "text", "%s")
        elif char == '_':
            _run(adb_path, "shell", "input", "keyevent", "66")  # ENTER
        elif char.isalnum():
            _run(adb_path, "shell", "input", "text", char)
        elif char in '-.,!?@\'°/:;()':
            _run(adb_path, "shell", "input", "text", char)
        else:
            # 复杂字符：走广播法（配合 ADB Keyboard）
            _run(adb_path, "shell", "am", "broadcast",
                 "-a", "ADB_INPUT_TEXT", "--es", "msg", char)


def slide(adb_path, x1, y1, x2, y2):
    _run(adb_path, "shell", "input", "swipe",
         int(x1), int(y1), int(x2), int(y2), "500")


def back(adb_path):
    _run(adb_path, "shell", "input", "keyevent", "4")


def home(adb_path):
    _run(adb_path, "shell", "am", "start",
         "-a", "android.intent.action.MAIN",
         "-c", "android.intent.category.HOME")
