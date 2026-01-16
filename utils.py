import difflib
import hashlib


def normalize_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s)   # 中英数字保留
    s = re.sub(r"\s+", " ", s).strip()
    return s


def similarity(a: str, b: str) -> float:  # 轻量的匹配，判断词是否一样，形状是否类似
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    # token Jaccard + SequenceMatcher 混合
    A, B = set(na.split()), set(nb.split())
    jacc = len(A & B) / max(1, len(A | B))
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    return 0.6 * jacc + 0.4 * seq


def make_skill_key(app_name: str, canonical_desc: str) -> str:
    base = normalize_text(canonical_desc)
    h = hashlib.md5((app_name + "||" + base).encode("utf-8")).hexdigest()[:10]  # 截断避免太长
    return f"{base[:50]}__{h}"


def retrieve_skill_matches(memory_db, app_name: str, query_subtask: str, top_k=3, min_score=0.35):
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
            "hint": "",
            "avoid": "",
            "stats": {"success": 0, "fail": 0},
            "disabled": False,
        })
        best = skill_key
        rec["_key"] = best  # 临时
        memory_db[app_name][best] = rec

    # 解析模型输出（如果你 get_memory_prompt 输出 JSON）
    hint, avoid = "", ""
    try:
        m = re.search(r"\{.*\}", hint_json_text, flags=re.S)
        if m:
            obj = json.loads(m.group(0))
            hint = obj.get("hint", "") or ""
            avoid = obj.get("avoid", "") or ""
    except Exception:
        pass

    if hint:
        rec["hint"] = hint
    if avoid:
        rec["avoid"] = avoid
    rec["desc"] = rec.get("desc") or subtask
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

    # 先禁用再删除（更稳）
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