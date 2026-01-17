import os, re
import time
import json
from PIL import Image
import difflib
import hashlib

import controller
from api import call

from controller import get_screenshot, tap, slide, type, back, home
from prompt import get_decision_prompt, get_reflect_prompt, get_memory_prompt, get_planning_prompt
from chat import init_decision_chat, init_chat, add_response, add_response_two_image


# Setting
# ADB path
adb_path = "D:/Program Files/Netease/MuMuPlayer/nx_main/adb.exe"

# instruction
# instruction = "open setting, then turn off the Wifi"
instruction = "open setting, then turn on Dark theme in Display"
# instruction = "open QQ, then enter '好友动态'"
# instruction = "Open Maps, search for White House, then get navigation directions from my current location, and start navigation."

# important things need Agent to find and remember
insight = ""
# operational knowledge to help Agent operate more accurately
add_info = ""
# "If you want to tap an icon of an app, use the action \"Open app\". "
# "If you want to exit an app, use the action \"Home\". "
# "If the last operation produced no change, do not choose the same coordinates again."

# GPT API URL and token
api_url = ""
key = ""


def extract_json_obj(text: str) -> dict:
    """
    Extract the first JSON object from model output. Enforces robustness when the model accidentally adds extra tokens.
    """
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("Planning output has no JSON object.")
    return json.loads(m.group(0))


def normalize_text(s: str) -> str:  # 抽取中英文文字
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s)   # 中英数字保留
    s = re.sub(r"\s+", " ", s).strip()
    return s


def similarity(a: str, b: str) -> float:  # 轻量的匹配，判断单词是否一样，形状是否类似
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    # token Jaccard + SequenceMatcher 混合
    A, B = set(na.split()), set(nb.split())
    jacc = len(A & B) / max(1, len(A | B))
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    return 0.6 * jacc + 0.4 * seq


def make_skill_key(app_name: str, canonical_desc: str) -> str:  # 为子任务生成唯一的key，来辨别
    base = normalize_text(canonical_desc)
    h = hashlib.md5((app_name + "||" + base).encode("utf-8")).hexdigest()[:10]  # 截断避免太长
    return f"{base[:50]}__{h}"


def retrieve_skill_matches(memory_db, app_name: str, query_subtask: str, top_k=3, min_score=0.35):
    # TODO 考虑优化
    # 从记忆中匹配，按照相似度得分计算top k
    matches = []
    app_mem = memory_db.get(app_name, {})
    for skill_key, rec in app_mem.items():
        if rec.get("disabled", False):
            continue
        score = similarity(query_subtask, rec.get("desc", ""))
        if score >= min_score:
            matches.append((score, skill_key, rec))
    matches.sort(reverse=True, key=lambda x: x[0])
    return matches[:top_k]

# TODO 放在决策的prompt中
def format_memory_for_prompt(matches):
    if not matches:
        return ""
    lines = []
    lines.append("Relevant long-term skills (REFERENCE ONLY; do NOT copy coordinates blindly):")
    for score, skill_key, rec in matches:
        hint = (rec.get("hint", "") or "").replace("\n", " ").strip()
        avoid = (rec.get("avoid", "") or "").replace("\n", " ").strip()
        desc = (rec.get("desc", "") or "").replace("\n", " ").strip()
        lines.append(f"- [score={score:.2f}] key='{skill_key}' desc='{desc}'")
        if hint:
            lines.append(f"  hint: {hint}")
        if avoid:
            lines.append(f"  avoid: {avoid}")
    return "\n".join(lines)


def upsert_skill_success(app_name, subtask, hint_json_text):
    memory_db.setdefault(app_name, {})
    # 如果本轮已有匹配 skill，就更新那个；否则新建
    if best_skill_key and best_skill_key in memory_db[app_name]:
        rec = memory_db[app_name][best_skill_key]
    else:
        skill_key = make_skill_key(app_name, subtask)
        rec = memory_db[app_name].get(skill_key, {
            "desc": subtask,
            "when_to_use": "",
            "hint": "",
            "avoid": "",
            "stats": {"success": 0, "fail": 0},
            "disabled": False,
        })
        best = skill_key
        rec["_key"] = best  # 临时
        memory_db[app_name][best] = rec

    # 解析模型输出
    when_to_use, hint, avoid = "", "", ""
    try:
        m = re.search(r"\{.*\}", hint_json_text, flags=re.S)
        if m:
            obj = json.loads(m.group(0))
            when_to_use = obj.get("when_to_use", "") or ""
            hint = obj.get("hint", "") or ""
            avoid = obj.get("avoid", "") or ""

    except Exception:
        pass
    if when_to_use:
        rec["when_to_use"] = when_to_use
    if hint:
        rec["hint"] = hint
    if avoid:
        rec["avoid"] = avoid
    rec["stats"]["success"] = rec.get("stats", {}).get("success", 0) + 1
    rec["updated_at"] = time.time()
    rec.pop("_key", None)


def punish_skill_failure(app_name):
    # 本轮使用了了 memory skill；有明确的 best_skill_key； skill 仍然存在 时惩罚
    if not (used_memory and best_skill_key and app_name in memory_db and best_skill_key in memory_db[app_name]):
        return
    rec = memory_db[app_name][best_skill_key]
    rec["stats"]["fail"] = rec.get("stats", {}).get("fail", 0) + 1
    rec["updated_at"] = time.time()

    # 先禁用再删除
    if rec["stats"]["fail"] >= 2:
        rec["disabled"] = True
    if rec["stats"]["fail"] >= 4:
        del memory_db[app_name][best_skill_key]


def load_memory_db(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory_db(path, memory_db):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(memory_db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


operation_history = []
action_history = []
important_content = ""

operation = ""
action = ""
keyboard = False

planning_json = None
completed = ""

last_reflect_label = ""     # A / B / C
last_reflect_reason = ""    # optional short text
error = False

MEMORY_PATH = "./memory_db.json"
memory_db = load_memory_db(MEMORY_PATH)
if not os.path.exists("screenshot"):
    os.mkdir("screenshot")

i = 0
all_start = time.time()
while True:
    step_start = time.time()
    i += 1
    print("\n\n\n*** Step:", i, "***")
    # 获取截图
    screenshot_file = f"./screenshot/before_step_{i}.png"
    get_screenshot(adb_path, screenshot_file)
    width, height = Image.open(screenshot_file).size

    # 规划 planning
    start = time.time()
    # TODO：增加全局记忆到planning中
    prompt_planning = get_planning_prompt(
        instruction=instruction,
        planning_json=planning_json,
        operation_history=operation_history,
        action_history=action_history,
        completed_summary=completed,
        last_reflect_label=last_reflect_label,
        last_reflect_reason=last_reflect_reason,
        error=error,
    )
    chat_planning = init_chat()
    chat_planning = add_response("user", prompt_planning, chat_planning)
    output_planning = call(chat_planning, "gpt-4-turbo", api_url, key)
    chat_planning = add_response("assistant", output_planning, chat_planning)

    planning_json = extract_json_obj(output_planning)  # 提取集合json
    completed = planning_json["progress"].get("completed_summary", completed)
    completed_ids = planning_json["progress"].get("completed_ids")
    current_app_name = planning_json["progress"].get("current_app_name", "")
    current_subtask = planning_json["progress"].get("current_subtask", "")

    if len(completed_ids) == len(planning_json["subtasks"]):  # 结束判断
        print("[Planner] No remaining subtask. Stopping.")
        all_end = time.time()
        print("\n" + "=" * 110)
        print(f"All operations use time: {all_end - all_start:.1f} s")
        break

    end = time.time()
    print("\n" + "=" * 50 + " Planning " + "=" * 50)
    print(f"Planning uses time: {end - start:.1f} s\n")
    print(planning_json)  # 打印计划字典

    # TODO 优化记忆命中代码
    matches = retrieve_skill_matches(memory_db, current_app_name, current_subtask, top_k=3, min_score=0.35)
    retrieved_memory_text = format_memory_for_prompt(matches)
    # 用于后续更新/惩罚，记录本轮最相关的 skill（若有）
    used_memory = len(matches) > 0
    best_skill_key = matches[0][1] if used_memory else None

    # 决策 Decision #################################
    start = time.time()
    prompt_decision = get_decision_prompt(
        instruction=instruction,
        width=width,
        height=height,
        keyboard=keyboard,
        operation_history=operation_history,
        action_history=action_history,
        last_operation=operation,
        last_action=action,
        add_info=add_info,
        error=error,
        completed=completed,
        current_app_name=current_app_name,  # 来自 planning
        current_subtask=current_subtask,  # 来自 planning
        important_content=important_content,
        retrieved_memory=retrieved_memory_text,  # 检索到的记忆
    )

    chat_decision = init_decision_chat()
    chat_decision = add_response("user", prompt_decision, chat_decision, screenshot_file)
    output_decision = call(chat_decision, "gpt-4o", api_url, key)
    chat_decision = add_response("assistant", output_decision, chat_decision)

    end = time.time()
    print("\n" + "=" * 50 + " Decision " + "=" * 50)
    print(f"Decision uses time: {end - start:.1f} s\n")
    print(output_decision)

    thought = output_decision.split("### Thought ###")[-1].split("### Action ###")[0].replace("\n", " ").replace(":", "").replace("  ", " ").strip()
    action = output_decision.split("### Action ###")[-1].split("### Description ###")[0].replace("\n", " ").replace("  ", " ").strip()
    operation = output_decision.split("### Description ###")[-1].replace("\n", " ").replace("  ", " ").strip()

    # 执行 Executor #####################################################
    if "Open app" in action:
        coordinate = action.split("(")[-1].split(")")[0].split(", ")
        x, y = int(coordinate[0]), int(coordinate[1])
        tap(adb_path, x, y)
    
    elif "Tap" in action:
        coordinate = action.split("(")[-1].split(")")[0].split(", ")
        x, y = int(coordinate[0]), int(coordinate[1])
        tap(adb_path, x, y)
    
    elif "Swipe" in action:
        coordinate1 = action.split("Swipe (")[-1].split("), (")[0].split(", ")
        coordinate2 = action.split("), (")[-1].split(")")[0].split(", ")
        x1, y1 = int(coordinate1[0]), int(coordinate1[1])
        x2, y2 = int(coordinate2[0]), int(coordinate2[1])
        slide(adb_path, x1, y1, x2, y2)
        
    elif "Type" in action:
        if "(text)" not in action:
            text = action.split("(")[-1].split(")")[0]
        else:
            text = action.split(" \"")[-1].split("\"")[0]
        type(adb_path, text)
    
    elif "Back" in action:
        back(adb_path)
    
    elif "Home" in action:
        home(adb_path)
        
    elif "Stop" in action:
        all_end = time.time()
        print("\n" + "=" * 110)
        print(f"All operations use time: {all_end-all_start:.1f} s")
        break

    # todo：增加ui刷新的判断
    time.sleep(3)  # 等待设备ui刷新

    # 新截图用于反思
    last_screenshot_file = screenshot_file
    last_keyboard = keyboard
    screenshot_file = f"./screenshot/after_step_{i}.png"
    get_screenshot(adb_path, screenshot_file)
    width, height = Image.open(screenshot_file).size

    # TODO：判断操作后的键盘状态
    keyboard = False

    # 反思 reflection
    start = time.time()
    prompt_reflect = get_reflect_prompt(instruction, width, height, last_keyboard, keyboard, operation, action, add_info)
    chat_reflect = init_chat()
    chat_reflect = add_response_two_image("user", prompt_reflect, chat_reflect, [last_screenshot_file, screenshot_file])
    output_reflect = call(chat_reflect, 'gpt-4o', api_url, key)
    chat_reflect = add_response("assistant", output_reflect, chat_reflect)
    end = time.time()

    print("\n"+"=" * 50 + " Reflection " + "=" * 48)
    print(f"Reflection uses time: {end-start:.1f} s\n")
    print(output_reflect)  # thought

    last_reflect_reason = output_reflect.split("### Thought ###")[-1].split("### Answer ###")[0].replace("\n", " ").replace(":","").replace("  ", " ").strip()
    reflect = output_reflect.split("### Answer ###")[-1].replace("\n", " ").strip()

    if 'A' in reflect:
        last_reflect_label = 'A'
        operation_history.append(operation)
        action_history.append(action)
        error = False

        # 生成/刷新“长期技能记忆”
        prompt_memory = get_memory_prompt(instruction, current_app_name, current_subtask,
                                          last_reflect_reason, operation, action)
        chat_memory = init_chat()
        chat_memory = add_response("user", prompt_memory, chat_memory)
        output_memory = call(chat_memory, "gpt-4o", api_url, key)
        chat_memory = add_response("assistant", output_memory, chat_memory)

        upsert_skill_success(current_app_name, current_subtask, output_memory)
        save_memory_db(MEMORY_PATH, memory_db)

    elif 'B' in reflect:
        last_reflect_label = 'B'
        error = True
        controller.back(adb_path)

        punish_skill_failure(current_app_name)
        save_memory_db(MEMORY_PATH, memory_db)

    elif 'C' in reflect:
        last_reflect_label = 'C'
        error = True

        punish_skill_failure(current_app_name)
        save_memory_db(MEMORY_PATH, memory_db)

    step_end = time.time()
    print("\n"+"=" * 110)
    print(f"This iteration uses time: {step_end-step_start:.1f} s")
