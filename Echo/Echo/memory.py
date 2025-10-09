# memory.py
import json
import os
import uuid

MEMORY_FILE_NAME = "history.json"  # 固定记忆文件名

def load_conversation_history(memory_path: str):
    """
    从指定路径加载历史对话记录。
    """
    if os.path.isdir(memory_path):
        memory_file = os.path.join(memory_path, MEMORY_FILE_NAME)
    else:
        memory_file = memory_path

    if not os.path.exists(memory_file):
        print(f"⚠️ 未找到记忆文件 {memory_file}，使用默认空值初始化")
        return {
            "messages": [],
            "affinity": 0,
            "knowledge": []
        }

    try:
        with open(memory_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {"messages": [], "affinity": 0, "knowledge": []}
            return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        print(f"❌ 读取记忆失败：{e}")
        return {"messages": [], "affinity": 0, "knowledge": []}


def save_conversation_history(data: dict, path: str):
    """
    将对话历史保存到指定路径下的 history.json 文件中。
    """
    if os.path.isdir(path):
        file_path = os.path.join(path, MEMORY_FILE_NAME)
    else:
        file_path = path

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ 记忆已保存至 {file_path}")
    except IOError as e:
        print(f"❌ 写入记忆失败：{e}")


# def update_affinity(user_input, assistant_reply, current_affinity,):
#     """
#     根据对话内容更新亲密度
#     :param user_input: 用户输入
#     :param assistant_reply: 智能体回复
#     :param current_affinity: 当前亲密度
#     :return: 新的亲密度值
#     """
#     # 示例逻辑：检测关键词提升亲密度
#     keywords = ["谢谢", "喜欢", "很棒", "真好", "关心", "感动", "一起", "陪我", "了解我", "重要"]
#     if any(kw in user_input for kw in keywords):
#         return current_affinity + 1
#     return current_affinity

def generate_issue_id() -> str:
    """生成唯一的 issue_id"""
    return str(uuid.uuid4())

def update_affinity(intro_event: dict, affinity_change: int = 0) -> int:
    """
    更新亲密度值
    :param intro_event: 包含初始亲密度的 intro_event 字典
    :param affinity_change: 亲密度变化值，默认为 0
    :return: 当前亲密度值
    """
    # 从 intro_event 中读取初始亲密度，若不存在则默认为 0
    current_affinity = intro_event.get("affinity", 0)

    # 如果没有变化，直接返回当前值
    if affinity_change == 0:
        print(f"🔁 亲密度无变化，当前值：{current_affinity}")
        return current_affinity

    # 更新亲密度
    new_affinity = current_affinity + affinity_change
    intro_event["affinity"] = new_affinity  # 保存回 intro_event

    print(f"💖 亲密度更新：{current_affinity} → {new_affinity}")
    return new_affinity
