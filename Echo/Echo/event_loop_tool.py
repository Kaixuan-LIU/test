import os
import json
from datetime import datetime
from typing import List, Dict, Optional
from api_handler import ChatFireAPIClient
from database import MySQLDB

def get_intro_event(event_tree: list) -> dict:
    # 检查是否是分层结构（包含阶段）
    if isinstance(event_tree[0], dict) and "事件列表" in event_tree[0]:
        # 分层结构：遍历阶段找事件
        for stage in event_tree:
            events = stage.get("事件列表", [])
            for event in events:
                if isinstance(event, dict) and event.get("event_id") == "E001":
                    return event
    else:
        # 平铺结构：直接遍历事件列表
        for event in event_tree:
            if isinstance(event, dict) and event.get("event_id") == "E001":
                return event


def generate_scene_description(event_data) -> str:
    # 确保传入的是字典
    event = event_data if isinstance(event_data, dict) else {}

    location = event.get("location", "未知地点")
    time = event.get("time", "未知时间")
    characters = ", ".join(event.get("characters", ["用户", "智能体"]))

    time_descriptions = {
        "清晨": "阳光透过窗户洒进来，空气中带着清新的气息",
        "上午": "办公室里传来键盘敲击声，一切都充满活力",
        "中午": "阳光炽热，周围弥漫着午休的轻松氛围",
        "下午": "阳光逐渐柔和，工作节奏稍显舒缓",
        "傍晚": "夕阳西下，天边泛起绚丽的晚霞",
        "夜晚": "月光如水，城市灯火阑珊"
        }

    time_desc = next((desc for t, desc in time_descriptions.items() if t in time), "时间描述未知")
    character_desc = f"现场有：{characters}"

    return f"""
今天的时间是{time}，我们正位于{location}。
{time_desc}。
{character_desc}。
    """


def get_next_event_from_chain(
        event_chain: List[Dict],
        dialog_history: List[Dict],
        client: ChatFireAPIClient
) -> Optional[Dict]:
    """调用大模型从事件链中选择下一个合适的事件"""
    if not event_chain:
        return None

    # 准备对话历史摘要
    history_summary = "\n".join([
        f"{m['role']}: {m['content'][:100]}..."
        for m in dialog_history[-5:]  # 取最近5条对话
    ]) if dialog_history else "无历史对话"

    # 准备事件链详细信息
    event_details = []
    for stage_idx, stage in enumerate(event_chain):
        stage_name = stage.get("阶段", f"阶段{stage_idx + 1}")
        events = stage.get("事件列表", [])
        for event_idx, event in enumerate(events):
            event_info = {
                "stage": stage_name,
                "event_index": event_idx,
                "event_id": event.get("event_id", ""),
                "name": event.get("name", ""),
                "trigger_conditions": event.get("trigger_conditions", []),
                "description": f"{event.get('name', '')} - {event.get('cause', '')[:100]}"
            }
            event_details.append(event_info)

    # 构建提示词
    prompt = f"""
你需要根据对话历史和事件链信息，从提供的事件列表中选择最合适的下一个事件。

对话历史摘要:
{history_summary}

可用事件列表（请从中选择一个）:
{json.dumps(event_details, ensure_ascii=False, indent=2)}

选择要求:
1. 必须从提供的事件列表中选择，不能生成新事件
2. 选择的事件应与对话历史有逻辑关联
3. 优先考虑触发条件与对话内容匹配的事件
4. 请返回事件在列表中的索引位置（整数），只返回数字，不要包含任何其他内容

如果没有合适的事件，请返回-1
"""

    try:
        # 调用大模型获取选择结果
        response = client.call_api([{"role": "user", "content": prompt}])
        content = response['choices'][0]['message']['content'].strip()

        # 解析返回的索引
        selected_idx = int(content)

        # 验证索引有效性
        if 0 <= selected_idx < len(event_details):
            # 找到对应的事件
            target_event_info = event_details[selected_idx]
            target_stage_idx = None
            for i, stage in enumerate(event_chain):
                if stage.get("阶段", f"阶段{i + 1}") == target_event_info["stage"]:
                    target_stage_idx = i
                    break

            if target_stage_idx is not None:
                stage = event_chain[target_stage_idx]
                events = stage.get("事件列表", [])
                if 0 <= target_event_info["event_index"] < len(events):
                    return events[target_event_info["event_index"]]

        # 索引无效时返回None
        return None

    except Exception as e:
        print(f"⚠️ 大模型选择下一个事件失败: {e}")
        return None

def generate_temporary_event_by_llm(
        client: ChatFireAPIClient,
        agent_name: str,
        agent_profile: str,
        goals: str,
        event_chain: List[Dict],
        dialog_history: List[Dict]
) -> Dict:
    """调用大模型生成临时事件"""
    # 准备对话历史摘要
    history_summary = "\n".join([
        f"{m['role']}: {m['content'][:100]}..."
        for m in dialog_history[-5:]  # 取最近5条对话
    ]) if dialog_history else "无历史对话"

    # 准备事件链摘要
    event_chain_summary = []
    for i, stage in enumerate(event_chain[:2]):  # 取前2个阶段
        events = [f"- {e['name']} (ID: {e['event_id']})" for e in stage.get("事件列表", [])[:3]]
        event_chain_summary.append(f"阶段{i + 1}: {', '.join(events)}")
    event_chain_summary = "\n".join(event_chain_summary) or "无事件链数据"

    # 构建生成临时事件的提示词
    prompt = f"""
你需要根据以下信息为智能体生成一个符合其设定的临时互动事件。

智能体信息：
- 名称: {agent_name}
- 基本资料: {json.dumps(agent_profile, ensure_ascii=False)[:500]}
- 核心目标: {json.dumps(goals, ensure_ascii=False)[:500]}

现有事件链摘要:
{event_chain_summary}

最近对话历史:
{history_summary}

生成要求:
1. 事件需符合智能体的性格设定和目标
2. 事件应与最近的对话内容有逻辑关联
3. 事件需要包含完整的结构:
   - event_id: 事件唯一标识（格式为TEMP_前缀+时间戳，例如TEMP_202408151230）
   - type: "临时事件"
   - name: 事件标题（简洁明了）
   - time: 具体时间
   - location: 具体地点
   - characters: 涉及角色列表（至少包含智能体和用户）
   - cause: 事件起因
   - process: 事件经过（包含可交互的节点）
   - result: 可能的结果（留空待用户互动后确定）
   - impact: 包含心理状态变化、知识增长、亲密度变化
   - importance: 1-5的重要性评分
   - urgency: 1-5的紧急度评分
   - tags: 相关关键词标签
   - trigger_conditions: 触发条件（基于当前对话）
   - dependencies: 依赖的前置事件ID（可留空）

请严格按照JSON格式输出，不要包含任何额外文本。
"""

    # 调用大模型生成事件
    try:
        response = client.call_api(messages=[{"role": "user", "content": prompt}], max_tokens=3000)
        content = response['choices'][0]['message']['content'].strip()

        # 提取并解析JSON
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1:
            event_json = content[start:end + 1]
            temp_event = json.loads(event_json)

            # 确保event_id格式正确
            if not temp_event.get("event_id", "").startswith("TEMP_"):
                temp_event["event_id"] = f"TEMP_{datetime.datetime.now().strftime('%Y%m%d%H%M')}"

            return temp_event
        else:
            raise ValueError("大模型返回内容不包含有效的JSON结构")

    except Exception as e:
        print(f"⚠️ 大模型生成临时事件失败，使用默认事件: {e}")
        # 生成默认临时事件作为 fallback
        return {
            "event_id": f"TEMP_{datetime.datetime.now().strftime('%Y%m%d%H%M')}",
            "type": "临时事件",
            "name": f"{agent_name}的日常互动",
            "time": datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M"),
            "location": "日常场景",
            "characters": [agent_name, "用户"],
            "cause": "基于当前互动需要",
            "process": "与用户进行日常交流，讨论近期情况",
            "result": "",
            "impact": {"心理状态变化": "友好", "知识增长": "0", "亲密度变化": "+1"},
            "importance": 2,
            "urgency": 2,
            "tags": ["日常", "互动"],
            "trigger_conditions": ["需要延续对话"],
            "dependencies": []
        }


# def run_event_loop(
#         user_id: int,
#         agent_id: int,
#         event_id: str,
#         user_input: str,
# ):
#     client = ChatFireAPIClient(api_key="sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV")
#     DB_CONFIG = {
#         "host": "101.200.229.113",
#         "user": "gongwei",
#         "password": "Echo@123456",
#         "database": "echo",
#         "port": 3306,
#         "charset": "utf8mb4"
#     }
#     with MySQLDB(**DB_CONFIG) as db:
#         # 1. 获取用户ID和智能体ID（实际应用中从前端接收）
#         user_id = user_id  # 临时固定值，实际应改为前端传入
#         agent_id = agent_id  # 临时固定值，实际应改为前端传入
#
#         try:
#             # 2. 从数据库读取智能体基础信息
#             print(f"🔍 正在读取agent_id={agent_id}的基础信息...")
#             agent_info = db.get_agent(agent_id)
#             if not agent_info:
#                 raise ValueError(f"未找到agent_id={agent_id}的智能体信息")
#             # 解析基础信息（full_json字段）
#             formatted_text = json.loads(agent_info[0]["full_json"])
#             agent_name = agent_info[0]["agent_name"]  # 从智能体信息中获取名称
#
#             # 3. 从数据库读取智能体目标
#             print(f"🔍 正在读取agent_id={agent_id}的目标信息...")
#             agent_goals = db.get_agent_goals(agent_id)
#             if not agent_goals:
#                 print(f"⚠️ 未找到agent_id={agent_id}的目标信息，使用默认目标")
#                 goals = {"goals": []}
#             else:
#                 # 解析目标信息（goals_json字段）
#                 goals = json.loads(agent_goals[0]["goals_json"])
#
#             # 4. 从数据库读取智能体事件链（修正表名引用错误）
#             print(f"🔍 正在读取agent_id={agent_id}的事件链...")
#             event_chains = db.get_agent_event_chains(agent_id)
#             if not event_chains:
#                 raise ValueError(f"未找到agent_id={agent_id}的事件链数据")
#
#             # 解析事件链（chain_json字段）
#             tree_data = json.loads(event_chains[0]["chain_json"])
#             tree = tree_data.get("event_tree", [])  # 提取事件链数组
#
#         except Exception as e:
#             print(f"操作失败: {str(e)}")
#
#     # 1. 从数据库查询对话历史
#     dialog_memories = db.get_user_agent_dialogs(user_id, agent_id)
#     is_first_interaction = len(dialog_memories) == 0
#
#     # 初始化对话数据和当前事件ID
#     messages = []
#     current_event_id = None  # 用于存储当前推送事件的event_id
#
#     # 2. 加载历史对话（如果存在）
#     if not is_first_interaction and dialog_memories:
#         latest_memory = dialog_memories[0]
#         dialog_json = json.loads(latest_memory["dialog_json"])
#         messages = dialog_json.get("dialogs", [])
#         print(f"📖 已加载最新对话历史，共{len(messages)}条记录")
#
#     # 3. 加载事件链
#     event_tree_data = json.loads(tree) if isinstance(tree, str) else tree
#     if not isinstance(event_tree_data, list):
#         event_tree_data = [event_tree_data]
#
#     # 4. 首次交互：使用初始事件
#     if is_first_interaction:
#         intro_event = get_intro_event(event_tree_data)
#         if not intro_event or "event_id" not in intro_event:
#             raise ValueError("事件树中未找到有效的初始事件（缺少event_id）")
#
#         # 记录当前事件ID（作为后续对话的issue_id）
#         current_event_id = intro_event["event_id"]
#
#         scene_description = generate_scene_description(intro_event)
#         system_prompt = {
#             "role": "system",
#             "content": f"""
# 你是角色 {agent_name}，请根据以下初识事件与用户展开沉浸式对话，主动引导用户进入事件中。
# 事件如下：
# {json.dumps(intro_event, ensure_ascii=False, indent=2)}
#
# 当前场景描述：
# {scene_description}
#
# 请注意：
# - 使用生活化语言、场景化对话，不讲解设定
# - 鼓励用户回应或参与决策
# - 不要控制用户行为，只引导和互动
# - 最后请以【事件结算】输出影响结果
#             """,
#             "event_id": current_event_id
#         }
#         messages.append(system_prompt)
#         print(f"🎯 首次互动，当前事件：{intro_event['name']}（event_id: {current_event_id}）")
#
#     # 5. 非首次交互：从事件链选择下一个事件
#     else:
#         next_event = get_next_event_from_chain(
#             event_chain=event_tree_data,
#             dialog_history=messages,
#             client=client  # 传入已初始化的ChatFireAPIClient实例
#         )
#
#         # 没有合适事件时调用大模型生成临时事件
#         if not next_event:
#             print("⚠️ 未找到合适的后续事件，正在调用大模型生成临时事件...")
#             next_event = generate_temporary_event_by_llm(
#                 client=client,
#                 agent_name=agent_name,
#                 agent_profile=formatted_text ,
#                 goals=goals,
#                 event_chain=event_tree_data,
#                 dialog_history=messages
#             )
#
#             # 将大模型生成的临时事件添加到事件链
#             for stage in event_tree_data:
#                 if "事件列表" in stage:
#                     stage["事件列表"].append(next_event)
#                     break
#             else:
#                 event_tree_data.append({"阶段": "临时阶段", "事件列表": [next_event]})
#
#             # 更新数据库中的事件链
#             updated_chain = {
#                 "version": "1.0",
#                 "event_tree": event_tree_data
#             }
#             db.insert_agent_event_chain(
#                 user_id=user_id,
#                 agent_id=agent_id,
#                 chain_json=json.dumps(updated_chain, ensure_ascii=False)
#             )
#             print(f"✅ 大模型生成的临时事件已添加到事件链：{next_event['name']}（event_id: {next_event['event_id']}）")
#
#         # 验证事件ID存在
#         if "event_id" not in next_event:
#             raise ValueError("选中的事件缺少必要的event_id字段")
#
#         # 记录当前事件ID
#         current_event_id = next_event["event_id"]
#
#         # 设置下一个事件的系统提示
#         system_prompt = {
#             "role": "system",
#             "content": f"""
# 你是角色 {agent_name}，请根据以下事件继续与用户互动。
# 事件如下：
# {json.dumps(next_event, ensure_ascii=False, indent=2)}
#
# 对话历史参考：
# {json.dumps(messages[-5:], ensure_ascii=False, indent=2)}
#
# 请注意：
# - 延续之前的对话风格
# - 推动事件发展，同时响应用户输入
# - 不要控制用户行为
# - 最后请以【事件结算】输出影响结果
#             """,
#             "event_id": current_event_id
#         }
#         messages.append(system_prompt)
#         print(f"🎯 下一个事件：{next_event['name']}（event_id: {current_event_id}）")
#
#     # 6. 对话交互循环（使用event_id作为issue_id）
#     step = 0
#     try:
#         while True:
#             if not current_event_id:
#                 print("❌ 未获取到有效的事件ID，无法继续对话")
#                 break
#
#             user_input = input("用户> ").strip()
#             if user_input.lower() in ["exit", "quit", "退出"]:
#                 print("👋 退出对话")
#                 break
#
#             step += 1
#             # 添加用户输入（使用当前事件ID作为issue_id）
#             messages.append({
#                 "role": "user",
#                 "content": user_input,
#                 "issue_id": current_event_id,
#                 "timestamp": datetime.datetime.now().isoformat()
#             })
#
#             # 调用大模型获取回复
#             response = client.call_api(messages)
#             reply = response['choices'][0]['message']['content']
#             print(f"\n{agent_name}> {reply}\n")
#
#             # 添加智能体回复
#             messages.append({
#                 "role": "assistant",
#                 "content": reply,
#                 "issue_id": current_event_id,
#                 "timestamp": datetime.datetime.now().isoformat()
#             })
#
#             # 检查事件结算或步骤上限
#             if "【事件结算】" in reply or step >= 100:
#                 print("✅ 事件交互完成")
#                 break
#
#     finally:
#         # 检查连接是否有效
#         if not db.connection or db.connection._closed:  # 不同驱动的关闭状态属性可能不同，需根据实际调整
#             print("⚠️ 数据库连接已关闭，无法保存对话历史")
#             return messages, agent_name, current_event_id
#         # 7. 保存对话到数据库
#         dialog_data = {
#             "version": "1.0",
#             "dialogs": messages,
#             "current_event_id": current_event_id
#         }
#         memory_id = db.insert_dialog_memory(
#             user_id=user_id,
#             agent_id=agent_id,
#             dialog_json=json.dumps(dialog_data, ensure_ascii=False)
#         )
#         if memory_id:
#             print(f"✅ 对话历史已保存到数据库（memory_id: {memory_id}，关联事件ID: {current_event_id}）")
#         else:
#             print("❌ 对话历史保存到数据库失败")
#
#     return messages
def run_event_loop(
        user_id: int,
        agent_id: int,
        event_id: str,  # 对应issue_id
        user_input: str,
):
    client = ChatFireAPIClient(api_key="sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV")
    DB_CONFIG = {
        "host": "101.200.229.113",
        "user": "gongwei",
        "password": "Echo@123456",
        "database": "echo",
        "port": 3306,
        "charset": "utf8mb4"
    }

    with MySQLDB(**DB_CONFIG) as db:
        try:
            # 1. 读取智能体基础信息
            print(f"🔍 正在读取agent_id={agent_id}的基础信息...")
            agent_info = db.get_agent(agent_id)
            if not agent_info:
                raise ValueError(f"未找到agent_id={agent_id}的智能体信息")
            formatted_text = json.loads(agent_info[0]["full_json"])
            agent_name = agent_info[0]["agent_name"]

            # 2. 读取智能体目标
            print(f"🔍 正在读取agent_id={agent_id}的目标信息...")
            agent_goals = db.get_agent_goals(agent_id)
            goals = json.loads(agent_goals[0]["goals_json"]) if agent_goals else {"goals": []}

            # 3. 读取智能体事件链
            print(f"🔍 正在读取agent_id={agent_id}的事件链...")
            event_chains = db.get_agent_event_chains(agent_id)
            if not event_chains:
                raise ValueError(f"未找到agent_id={agent_id}的事件链数据")
            tree_data = json.loads(event_chains[0]["chain_json"])
            event_tree_data = tree_data.get("event_tree", [])
            if not isinstance(event_tree_data, list):
                event_tree_data = [event_tree_data]

        except Exception as e:
            print(f"操作失败: {str(e)}")
            return {"agent_id": str(agent_id), "issue_id": event_id or "", "content": f"获取智能体信息失败: {str(e)}"}

        # 4. 处理事件逻辑（核心修改部分）
        current_event = None
        current_event_id = event_id  # 初始化当前事件ID为传入的issue_id

        # 4.1 若issue_id不为空，尝试从事件链中查找对应事件
        if event_id:
            # 遍历事件链查找匹配的事件
            for stage in event_tree_data:
                if "事件列表" in stage:
                    for event in stage["事件列表"]:
                        if event.get("event_id") == event_id:
                            current_event = event
                            break
                    if current_event:
                        break
            # 事件链中未找到对应事件，调用大模型生成临时事件
            if not current_event:
                print(f"⚠️ 事件链中未找到event_id={event_id}的事件，生成临时事件...")
                current_event = generate_temporary_event_by_llm(
                    client=client,
                    agent_name=agent_name,
                    agent_profile=formatted_text,
                    goals=goals,
                    event_chain=event_tree_data,
                    dialog_history=[]
                )
                current_event_id = current_event["event_id"]  # 更新为临时事件ID
                # 将临时事件添加到事件链并更新数据库
                for stage in event_tree_data:
                    if "事件列表" in stage:
                        stage["事件列表"].append(current_event)
                        break
                else:
                    event_tree_data.append({"阶段": "临时阶段", "事件列表": [current_event]})
                updated_chain = {"version": "1.0", "event_tree": event_tree_data}
                db.insert_agent_event_chain(
                    user_id=user_id,
                    agent_id=agent_id,
                    chain_json=json.dumps(updated_chain, ensure_ascii=False)
                )

        # 4.2 若issue_id为空，使用初始事件
        else:
            current_event = get_intro_event(event_tree_data)
            if not current_event or "event_id" not in current_event:
                error_msg = "事件树中未找到有效的初始事件"
                print(f"❌ {error_msg}")
                return {"agent_id": str(agent_id), "issue_id": "", "content": error_msg}
            current_event_id = current_event["event_id"]
            print(f"🎯 使用初始事件: {current_event['name']}（event_id: {current_event_id}）")

        # 5. 加载对话历史
        dialog_memories = db.get_user_agent_dialogs(user_id, agent_id)
        messages = []
        if dialog_memories:
            latest_memory = dialog_memories[0]
            dialog_json = json.loads(latest_memory["dialog_json"])
            messages = dialog_json.get("dialogs", [])
            print(f"📖 已加载最新对话历史，共{len(messages)}条记录")

        # 6. 构建系统提示
        scene_description = generate_scene_description(current_event) if current_event else "无场景描述"
        system_prompt = {
            "role": "system",
            "content": f"""
你是角色 {agent_name}，请根据以下事件与用户展开沉浸式对话。
事件如下：
{json.dumps(current_event, ensure_ascii=False, indent=2)}

当前场景描述：
{scene_description}

对话历史参考：
{json.dumps(messages[-5:], ensure_ascii=False, indent=2)}

请注意：
- 使用生活化语言、场景化对话，不讲解设定
- 鼓励用户回应或参与决策
- 不要控制用户行为，只引导和互动
- 最后请以【事件结算】输出影响结果
            """,
            "event_id": current_event_id
        }
        messages.append(system_prompt)

        # 7. 添加用户输入
        messages.append({
            "role": "user",
            "content": user_input,
            "issue_id": current_event_id,
            "timestamp": datetime.now().isoformat()
        })

        # 8. 调用大模型获取回复
        try:
            response = client.call_api(messages)
            agent_reply = response['choices'][0]['message']['content']
            print(f"\n{agent_name}> {agent_reply}\n")

            # 添加智能体回复到对话历史
            messages.append({
                "role": "assistant",
                "content": agent_reply,
                "issue_id": current_event_id,
                "timestamp": datetime.now().isoformat()
            })

            # 保存对话到数据库
            dialog_data = {
                "version": "1.0",
                "dialogs": messages,
                "current_event_id": current_event_id
            }
            db.insert_dialog_memory(
                user_id=user_id,
                agent_id=agent_id,
                dialog_json=json.dumps(dialog_data, ensure_ascii=False)
            )
            print(f"✅ 对话历史已保存（event_id: {current_event_id}）")

        except Exception as e:
            error_msg = f"大模型调用失败: {str(e)}"
            print(f"❌ {error_msg}")
            agent_reply = error_msg

        # 9. 按指定格式返回结果
        return {
            "agent_id": str(agent_id),
            "issue_id": current_event_id,
            "content": agent_reply
        }