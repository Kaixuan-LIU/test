import os
import json
import sys
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from api_handler import ChatFireAPIClient
from database import MySQLDB, TEST_DB_CONFIG,DB_CONFIG


def safe_input(prompt):
    print(prompt, end='', flush=True)
    return sys.stdin.readline().rstrip('\n')
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
            if "status" not in temp_event:
                temp_event["status"] = "未完成"
            # 确保event_id格式正确（原逻辑保留）
            if not temp_event.get("event_id", "").startswith("TEMP_"):
                temp_event["event_id"] = f"TEMP_{datetime.now().strftime('%Y%m%d%H%M')}"
            return temp_event
        else:
            raise ValueError("无有效JSON结构")
    except Exception as e:
        print(f"⚠️ 生成临时事件失败，使用默认事件")
        # 【核心修改】默认事件添加status
        return {
            "event_id": f"TEMP_{datetime.now().strftime('%Y%m%d%H%M')}",
            "type": "临时事件",
            "name": f"{agent_name}的日常互动",
            "status": "未完成",  # 新增默认状态
            "time": datetime.now().strftime("%Y年%m月%d日 %H:%M"),
            "location": "日常场景",
            "characters": [agent_name, "用户"],
            "cause": "基于当前互动需要",
            "process": "与用户进行日常交流",
            "result": "",
            "impact": {"心理状态变化": "友好", "知识增长": "0", "亲密度变化": "+1"},
            "importance": 2,
            "urgency": 2,
            "tags": ["日常", "互动"],
            "trigger_conditions": ["需要延续对话"],
            "dependencies": []
        }


def create_session(user_id: int, agent_id: int, event_tree: list, initial_event_id: str) -> str:
    """创建新会话并返回session_id"""
    session_id = str(uuid.uuid4())
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 初始化会话数据
    dialog_json = {
        "event_tree": event_tree,
        "dialog_history": []
    }

    with MySQLDB(**DB_CONFIG) as db:
        db._execute_update(
            """
            INSERT INTO dialogs (session_id, user_id, agent_id, event_id, status,
                                 start_time, current_event_id, event_status, dialog_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                int(user_id),
                int(agent_id),
                initial_event_id,
                "active",
                current_time,
                initial_event_id,
                "进行中",
                json.dumps(dialog_json, ensure_ascii=False)
            )
        )
    print(f"✅ 会话已创建，session_id: {session_id}（请保存用于继续对话）")
    return session_id


def load_session(session_id: str) -> Tuple[Dict, bool]:
    """加载已有会话，返回会话数据和是否已结束"""
    with MySQLDB(**DB_CONFIG) as db:
        session_detail = db._execute_query(
            """
            SELECT current_event_id, event_status, dialog_json, end_time
            FROM dialogs
            WHERE session_id = %s
            """,
            (session_id,)
        )
        if not session_detail:
            raise ValueError(f"无效的session_id：{session_id}（会话不存在）")

        session_db_data = session_detail[0]
        is_ended = session_db_data["event_status"] == "已结束" or session_db_data["end_time"] is not None
        dialog_json = json.loads(session_db_data["dialog_json"])

        session_data = {
            "current_event_id": session_db_data["current_event_id"],
            "event_tree": dialog_json.get("event_tree", []),
            "dialog_history": dialog_json.get("dialog_history", []),
            "event_status": session_db_data["event_status"]
        }
        return session_data, is_ended


def update_session(session_id: str, session_data: Dict, is_ended: bool) -> None:
    """更新会话数据到数据库"""
    updated_dialog_json = {
        "event_tree": session_data["event_tree"],
        "dialog_history": session_data["dialog_history"]
    }

    with MySQLDB(**DB_CONFIG) as db:
        if is_ended:
            update_sql = """
                         UPDATE dialogs
                         SET current_event_id = %s, \
                             event_status     = %s, \
                             dialog_json      = %s,
                             end_time         = NOW(), \
                             updated_at       = NOW()
                         WHERE session_id = %s \
                         """
        else:
            update_sql = """
                         UPDATE dialogs
                         SET current_event_id = %s, \
                             event_status     = %s, \
                             dialog_json      = %s,
                             updated_at       = NOW()
                         WHERE session_id = %s \
                         """

        db._execute_update(
            update_sql,
            (
                session_data["current_event_id"],
                session_data["event_status"],
                json.dumps(updated_dialog_json, ensure_ascii=False),
                session_id
            )
        )


def run_event_loop(
        user_id: int,
        agent_id: int,
        event_id: Optional[str] = None,
        user_input: str = None,
        session_id: Optional[str] = None,
        event_tree: Optional[list] = None
) -> Dict:
    """运行事件循环（集成会话管理）"""
    client = ChatFireAPIClient(api_key="sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV")
    db_config = TEST_DB_CONFIG if os.getenv("APP_ENV") == "testing" else DB_CONFIG

    # 1. 处理会话逻辑（新建/加载）
    if not session_id:
        # 1.1 首次对话：创建新会话
        if not event_tree:
            # 从数据库加载事件链（如果未传入）
            with MySQLDB(**db_config) as db:
                events_data = db.get_agent_event_chains(agent_id)
                if not events_data:
                    raise ValueError(f"未找到agent_id={agent_id}的事件链数据")
                chain_json = events_data[0]['chain_json']
                event_tree = json.loads(chain_json).get('event_tree', [])

        # 初始化事件ID
        initial_event_id = event_id or get_intro_event(event_tree).get("event_id") or f"EVT_{uuid.uuid4()}"

        # 创建会话
        session_id = create_session(
            user_id=user_id,
            agent_id=agent_id,
            event_tree=event_tree,
            initial_event_id=initial_event_id
        )

        # 初始化会话数据
        session_data = {
            "current_event_id": initial_event_id,
            "event_tree": event_tree,
            "dialog_history": [],
            "event_status": "进行中"
        }
        is_ended = False

    else:
        # 1.2 继续对话：加载已有会话
        session_data, is_ended = load_session(session_id)
        if is_ended:
            return {
                "error": "对话已结束",
                "session_id": session_id,
                "is_ended": True
            }

    # 2. 加载智能体信息
    with MySQLDB(**db_config) as db:
        agent_info = db.get_agent(agent_id)
        if not agent_info:
            raise ValueError(f"未找到agent_id={agent_id}的智能体信息")
        formatted_text = json.loads(agent_info[0]["full_json"])
        agent_name = agent_info[0]["agent_name"]

        # 读取智能体目标
        agent_goals = db.get_agent_goals(agent_id)
        goals = json.loads(agent_goals[0]["goals_json"]) if agent_goals else []

    # 3. 查找当前事件
    current_event = None
    current_event_id = session_data["current_event_id"]
    for stage in session_data["event_tree"]:
        events = stage.get("事件列表", [])
        for event in events:
            if event.get("event_id") == current_event_id:
                current_event = event
                break
        if current_event:
            break

    if not current_event:
        raise ValueError(f"未找到事件ID: {current_event_id}")

    # 4. 准备消息列表
    messages = []
    dialog_history = session_data["dialog_history"]

    system_prompt = {
        "role": "system",
        "content": f"""
        你正在扮演智能体{agent_name}，一个真实的{formatted_text.get('职业', '专业人士')}，请遵循以下设定：
        1. 你的背景信息：{json.dumps(formatted_text, ensure_ascii=False)}
        2. 核心目标：{json.dumps(goals, ensure_ascii=False)}
        3. 当前事件：{current_event.get('name')}（{current_event.get('event_id')}）
        4. 事件场景：{generate_scene_description(current_event)}
        5. 请注意：
- 对话要求：
-- 保持角色一致性：始终以{agent_name}的身份和视角进行回应。
-- 禁止出现纹身、疤痕、胎记等身体特征描写。
-- 拒绝神秘背景设定，不走玄幻路线。避免用物品象征情感，所有情感表达要直接真实。
-- 杜绝使用数字梗，不以数字代替情感表达。拒绝伏笔和暗喻，情节发展清晰明了。
-- 避免使用专业术语，语言通俗易懂。情节推进依靠对话和动作。拒绝回忆式情节，直接展开当下故事。
-- 描写要场景化、情感化、故事化、具体化，多用动作和语言描写，人物互动要生动鲜活。
-- 对话要有来有回，富有生活气息，避免生硬。不分章节，情节自然衔接，流畅推进。
-- 围绕日常小事展开，贴近生活，真实自然。事件之间要有内在联系，情节发展环环相扣。请说人话。
-- 回复要像真实的人在说话，避免使用明显的编号列表（如1. 2. 3.）或过于结构化的表达
-- 尽量使用自然的句子和段落，就像在和朋友聊天一样
-- 表达观点时可以使用"我觉得"、"在我看来"、"我注意到"等更自然的表达方式
- 鼓励用户回应或参与决策，不要控制用户行为，只引导和互动
- 当事件目标达成时，必须返回【事件结束：成功】作为结束语后缀
- 当事件目标明确无法达成时，必须返回【事件结束：失败】作为结束语后缀
- 当事件明显有结束的倾向时，立即判断事件成功还是失败，并返回【事件结束：成功】或者【事件结束：失败】作为结束语后缀
- 当用户和智能体进行告别时，根据核心目标判断事件成功还是失败，并立即返回【事件结束：成功】或者【事件结束：失败】作为结束语后缀
- 【事件结束：成功】或【事件结束：失败】是唯一结束标志，出现后对话立即终止
        """
    }

    has_system_prompt = any(msg.get("role") == "system" for msg in dialog_history)
    if not has_system_prompt:
        messages.append(system_prompt)

    # 添加历史对话
    messages.extend(dialog_history)

    # 5. 处理用户输入
    user_msg = {
        "role": "user",
        "content": user_input,
        "issue_id": current_event_id,
        "timestamp": datetime.now().isoformat()
    }
    messages.append(user_msg)
    dialog_history.append(user_msg)
    session_data["dialog_history"] = dialog_history

    # 6. 调用大模型获取回复
    agent_reply = ""
    event_status = "进行中"
    is_ended = False

    try:
        response = client.call_api(messages)
        agent_reply = response['choices'][0]['message']['content'].strip()

        # 添加智能体回复
        agent_msg = {
            "role": "assistant",
            "content": agent_reply,
            "issue_id": current_event_id,
            "timestamp": datetime.now().isoformat()
        }
        messages.append(agent_msg)
        dialog_history.append(agent_msg)
        session_data["dialog_history"] = dialog_history

        # 检测事件结束标志
        if "事件结束" in agent_reply:
            is_ended = True
            if "成功" in agent_reply:
                event_status = "成功"
            elif "失败" in agent_reply:
                event_status = "失败"

    except Exception as e:
        error_msg = f"大模型调用失败: {str(e)}"
        print(f"❌❌ {error_msg}")
        agent_reply = error_msg

    # 7. 更新事件状态
    with MySQLDB(**db_config) as db:
        try:
            db.update_event_status(
                agent_id=agent_id,
                event_id=current_event_id,
                status=event_status
            )
        except Exception as e:
            print(f"❌ 数据库状态更新失败: {str(e)}")

    # 8. 确定下一个事件
    next_event = get_next_event_from_chain(session_data["event_tree"], dialog_history,
                                           client) if event_status == "成功" else None
    next_event_id = next_event["event_id"] if next_event else current_event_id
    session_data["current_event_id"] = next_event_id
    session_data["event_status"] = event_status

    # 9. 保存会话更新
    update_session(session_id, session_data, is_ended)

    # 10. 返回结果
    return {
        "content": agent_reply,
        "issue_id": next_event_id,
        "event_status": event_status,
        "is_ended": is_ended,
        "session_id": session_id,
        "dialog_history": dialog_history
    }
