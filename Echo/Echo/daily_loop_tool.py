import json
import os
import time
import copy
from datetime import datetime
import requests
from database import MySQLDB, DB_CONFIG
from api_handler import ChatFireAPIClient
from event_loop_tool import get_intro_event
from memory import generate_issue_id
from schedule_generator import generate_agent_schedule, generate_default_schedule

def run_daily_loop(agent_profile: dict, goals: str, event_tree: str, agent_id: int, user_id: int,
                   user_input: str = None, session_data: dict = None):
    # 初始化会话状态
    if session_data is None:
        session_data = {
            'conversation_counter': 0,
            'pending_messages': [],
            'waiting_for_input': False,
            'last_activity': None,
            'last_status': None,
            'schedule_displayed': False,
            'initialized': False,
            'name': None,
            'parsed_schedule': None,
            'conversation_history': [],
            'exit_requested': False  # 新增退出标志
        }

        # 检查退出请求
    if session_data.get('exit_requested'):
        print(f"🛑 已终止与 {session_data['name']} 的对话")
        return None, None, session_data

    # 创建数据库连接 - 每次运行都需要
    db = MySQLDB(**DB_CONFIG)

    # 1. 只在首次运行时加载数据
    if not session_data.get('initialized'):
        print(f"🚀 启动日常互动（agent_id: {agent_id}, user_id: {user_id}）")

        # 从数据库加载智能体信息
        with db as db_conn:
            agent_data = db_conn.get_agent_by_id(agent_id)
            if agent_data:
                try:
                    agent_profile = json.loads(agent_data['full_json'])
                    session_data['name'] = agent_profile.get("姓名", "未知智能体")
                    print(f"✅ 从数据库加载智能体信息成功（agent_id: {agent_id}）")
                except json.JSONDecodeError as e:
                    print(f"❌❌❌❌ 智能体信息JSON解析失败: {e}")
                    return None, None, session_data
            else:
                print(f"⚠️ 数据库中未找到智能体信息（agent_id: {agent_id}）")
                return None, None, session_data

        # 从数据库加载目标
        with db as db_conn:
            goals_data = db_conn.get_agent_goals(agent_id)
            if goals_data:
                try:
                    goals = json.loads(goals_data[0]['goals_json'])
                    print(f"✅ 从数据库加载目标成功（agent_id: {agent_id}）")
                except json.JSONDecodeError as e:
                    print(f"❌❌❌❌ 目标JSON解析失败: {e}")
            else:
                print(f"⚠️ 数据库中未找到目标（agent_id: {agent_id}）")

        # 从数据库加载事件链
        with db as db_conn:
            events_data = db_conn.get_agent_event_chains(agent_id)
            if events_data:
                try:
                    event_tree = json.loads(events_data[0]['chain_json'])
                    print(f"✅ 从数据库加载事件链成功（agent_id: {agent_id}）")
                except json.JSONDecodeError as e:
                    print(f"❌❌❌❌ 事件链JSON解析失败: {e}")
            else:
                print(f"⚠️ 数据库中未找到事件链（agent_id: {agent_id}）")

        # 从数据库加载日程表
        full_schedule = None
        with db as db_conn:
            schedules = db_conn.get_agent_daily_schedules(agent_id)
            if schedules:
                try:
                    full_schedule = json.loads(schedules[0]['schedule_json'])
                    print(f"✅ 从数据库加载周日程表成功（agent_id: {agent_id}）")
                except json.JSONDecodeError as e:
                    print(f"❌❌❌❌ 日程表JSON解析失败: {e}")
            else:
                print(f"⚠️ 数据库中未找到日程表（agent_id: {agent_id}）")
                # 生成默认日程并保存到数据库
                try:
                    full_schedule = generate_agent_schedule(agent_profile,
                                                            "sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV")
                    schedule_json = json.dumps(full_schedule, ensure_ascii=False)
                    schedule_id = db_conn.insert_agent_daily_schedule(
                        user_id=user_id,
                        agent_id=agent_id,
                        schedule_json=schedule_json
                    )
                    if schedule_id:
                        print(f"✅ 新日程表已存入数据库（schedule_id: {schedule_id}）")
                    else:
                        print("❌❌❌❌ 日程表存入数据库失败")
                except Exception as e:
                    print(f"❌❌❌❌ 生成默认日程失败: {str(e)}")
                    full_schedule = generate_default_schedule()

        # 从数据库加载对话历史
        conversation_history = []
        with db as db_conn:
            try:
                conversation_history = db_conn.get_agent_dialog_memory(user_id, agent_id)
                if conversation_history:
                    print(f"✅ 从数据库加载历史对话成功（agent_id: {agent_id}）")
                else:
                    print(f"⚠️ 数据库中未找到历史对话（agent_id: {agent_id}）")
            except Exception as e:
                print(f"❌❌❌❌ 加载对话历史失败: {e}")

        session_data['conversation_history'] = conversation_history

        # 如果未加载到完整日程表，生成默认的
        if not full_schedule:
            print("⚠️ 周日程表加载失败，生成默认日程")
            full_schedule = generate_default_schedule()

        # 获取当前星期几
        weekday = datetime.now().strftime("%A")
        weekdays_map = {
            "Monday": "周一",
            "Tuesday": "周二",
            "Wednesday": "周三",
            "Thursday": "周四",
            "Friday": "周五",
            "Saturday": "周六",
            "Sunday": "周日"
        }
        weekday_cn = weekdays_map.get(weekday, "周一")

        # 从完整周日程表中提取当天的日程
        schedule = full_schedule.get(weekday_cn, [])

        # 预解析时间表
        parsed_schedule = []
        for slot in schedule:
            try:
                parsed_slot = {
                    "start_time": slot["start_time"],
                    "end_time": slot["end_time"],
                    "activity": slot["activity"],
                    "status": slot["status"]
                }
                parsed_schedule.append(parsed_slot)
            except Exception as e:
                print(f"⚠️ 时间表解析异常: {e}")

        session_data['parsed_schedule'] = parsed_schedule

        # 打印互动标题 - 只打印一次
        print(f"🧠🧠🧠 开始与 {session_data['name']} 的日常互动 (输入 exit 退出)")

        # 显示日程表 - 只显示一次
        print("⏰⏰⏰ 今日日程：")
        for slot in parsed_schedule:
            print(f"  - {slot['start_time']}-{slot['end_time']}: {slot['activity']} ({slot['status']})")

        session_data['initialized'] = True

    # 后续运行使用已加载的数据
    name = session_data['name']
    parsed_schedule = session_data['parsed_schedule']
    conversation_history = session_data['conversation_history']

    # 初始化当前对话记录（深拷贝）
    current_dialog = copy.deepcopy(conversation_history)

    # 获取当前时间和状态
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")  # 用于显示
    current_time_obj = now.time()

    # 设置默认状态
    current_activity = "自由时间"
    current_status = "空闲"


    # 创建临时解析的时间对象列表
    temp_parsed_schedule = []
    for slot in session_data['parsed_schedule']:
        try:
            start_time_obj = datetime.strptime(slot["start_time"], "%H:%M").time()
            end_time_obj = datetime.strptime(slot["end_time"], "%H:%M").time()
            temp_slot = {
                "start_time": slot["start_time"],
                "end_time": slot["end_time"],
                "activity": slot["activity"],
                "status": slot["status"],
                "start_time_obj": start_time_obj,
                "end_time_obj": end_time_obj
            }
            temp_parsed_schedule.append(temp_slot)
        except Exception as e:
            print(f"⚠️ 时间表解析异常: {e}")
            continue

    def evaluate_state_change(messages, agent_profile, goals, event_tree):
        base_attrs = agent_profile.get("基础属性", {})
        memory_level = base_attrs.get("记忆力", 5)

        prompt = f"""
    【角色基础属性】
    记忆力等级：{memory_level}/9
        """

    # 在构建系统提示词时加入时间约束
    system_prompt = {
        "role": "system",
        "content": f"""
    你正在扮演{name}，一个真实的{agent_profile.get('职业', '自由职业者')}。请严格遵守以下规则：
    1. 回应时必须考虑当前时间：{now.strftime("%H:%M")} 和当前活动状态
    2. 如果当前是工作时间，回复要简短专业
    3. 如果是休息时间，回复可以更随意
    4. 不要问候与当前时间不符的内容（如晚上不说"早上好"）
    5. 当前活动状态：{current_activity} ({current_status})

    【智能体特征】
    {json.dumps(agent_profile, ensure_ascii=False, indent=2)}

    【今日日程】
    {[f"{slot['start_time']}-{slot['end_time']}: {slot['activity']} ({slot['status']})" for slot in parsed_schedule][:5]}

    【回复要求】
    - 根据当前活动状态调整回复长度和内容
    - 如果正在工作，回答要简短（1-2句话）
    - 如果处于空闲状态，可以多聊几句
    - 用括号标注动作，例如：(看手表)
    - 句子长度根据活动状态调整
    """
    }

    # 初始化消息列表
    messages = [system_prompt] + conversation_history[-10:]  # 只保留最近10条历史记录

    # 检查是否在等待用户输入
    if session_data.get('waiting_for_input'):
        if user_input is None:
            return None, None, session_data
        else:
            session_data['waiting_for_input'] = False

    # 处理待处理消息（如果有）
    while session_data['pending_messages']:
        msg = session_data['pending_messages'].pop(0)
        # 添加到当前对话
        messages.append(msg)
        current_dialog.append(msg)

        # 保存到数据库
        with db as db_conn:
            try:
                success = db_conn.insert_agent_message(
                    user_id=user_id,
                    agent_id=agent_id,
                    role=msg["role"],
                    content=msg["content"],
                    issue_id=msg.get("issue_id", generate_issue_id()),
                    timestamp=msg["timestamp"],
                    activity=msg.get("activity", "未知"),
                    status=msg.get("status", "空闲")
                )
                if not success:
                    print(f"⚠️ {msg['role']}消息保存失败")
            except Exception as e:
                print(f"⚠️ 保存{msg['role']}消息异常: {e}")

    max_conversation_turns = 10
    try:
        user_input_text = user_input if user_input is not None else ""

        # 获取当前时间和状态
        now = datetime.now()
        current_time = now.time()
        current_activity = "空闲时间"
        current_status = "空闲"

        # 查找当前时间段的活动
        for slot in session_data['parsed_schedule']:
            # 解析槽位时间为时间对象
            slot_start = datetime.strptime(slot["start_time"], "%H:%M").time()
            slot_end = datetime.strptime(slot["end_time"], "%H:%M").time()
            if slot_start <= current_time_obj <= slot_end:
                current_activity = slot["activity"]
                current_status = slot["status"]
                break

        # 检查活动状态是否发生变化
        if current_activity != session_data.get('last_activity') or current_status != session_data.get('last_status'):
            print(f"⏰⏰⏰ 当前时间: {now.strftime('%H:%M')} | 活动: {current_activity} | 状态: {current_status}")

        # 更新最后一次的状态
        session_data['last_activity'] = current_activity
        session_data['last_status'] = current_status

        # 获取用户输入
        if current_status != "空闲":
            if not user_input_text.strip():  # 检查非空闲状态是否有输入
                session_data['waiting_for_input'] = True
                return messages, name, session_data
            else:
                # 显示用户输入
                print(f"{name}处于忙碌状态，稍等一下")

        if user_input_text.strip():
            now = datetime.now()
            user_message = {
                "role": "user",
                "content": user_input_text,
                "issue_id": generate_issue_id(),
                "timestamp": now.isoformat(),
                "activity": current_activity,
                "status": current_status
            }
            if user_input_text.lower() == "exit":
                print(f"⏹⏹⏹ 用户请求结束与 {name} 的对话")
                session_data['exit_requested'] = True
                session_data['waiting_for_input'] = False

                # ===== 新增状态评估和保存逻辑 =====
                # 1. 调用状态评估函数
                from main import evaluate_state_change
                state_result = evaluate_state_change(
                    messages,
                    agent_profile,
                    goals,
                    event_tree
                )

                # 2. 更新数据库状态
                from main import state_update
                state_update(
                    agent_id,
                    state_result,
                    agent_profile,  # 原 formatted_text
                    goals,
                    event_tree
                )

                # 3. 保存完整的对话记录
                with db as db_conn:
                    for msg in current_dialog:
                        if 'saved' not in msg:
                            db_conn.insert_agent_message(
                                user_id=user_id,
                                agent_id=agent_id,
                                role=msg["role"],
                                content=msg["content"],
                                issue_id=msg.get("issue_id", generate_issue_id()),
                                timestamp=msg["timestamp"],
                                activity=msg.get("activity", "未知"),
                                status=msg.get("status", "空闲")
                            )

                return messages, name, session_data

            # 保存用户消息
            with db as db_conn:
                try:
                    success = db_conn.insert_agent_message(
                        user_id=user_id,
                        agent_id=agent_id,
                        role="user",
                        content=user_input_text,
                        issue_id=user_message["issue_id"],
                        timestamp=user_message["timestamp"],
                        activity=current_activity,
                        status=current_status
                    )
                    if success:
                        messages.append(user_message)
                        current_dialog.append(user_message)
                    else:
                        print("⚠️ 用户输入保存失败，将继续尝试")
                        session_data['pending_messages'].append(user_message)
                except Exception as e:
                    print(f"⚠️ 保存用户输入异常: {e}")
                    session_data['pending_messages'].append(user_message)

            # 处理AI回复
            try:
                if current_status == "忙碌":
                    time.sleep(3)
                elif current_status == "一般忙碌":
                    time.sleep(1)

                # 创建API客户端
                try:
                    client = ChatFireAPIClient(
                        api_key="sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV",
                        base_url="https://api.chatfire.cn",
                        default_model="deepseek-chat"
                    )
                except Exception as e:
                    print(f"⚠️ 创建API客户端失败: {e}")
                    return [{
                        "role": "system",
                        "content": "对话服务初始化失败",
                        "timestamp": datetime.now().isoformat()
                    }], name, session_data

                # 调用API获取响应
                response = client.call_api(messages)
                reply_content = response['choices'][0]['message']['content']

                # 显示AI回复
                print(f"\n{name}: {reply_content}\n")

                # 记录AI响应
                assistant_message = {
                    "role": "assistant",
                    "content": reply_content,
                    "issue_id": user_message["issue_id"] if user_input_text.strip() else generate_issue_id(),
                    "timestamp": datetime.now().isoformat(),
                    "activity": current_activity,
                    "status": current_status
                }

                # 保存AI响应
                with db as db_conn:
                    try:
                        success = db_conn.insert_agent_message(
                            user_id=user_id,
                            agent_id=agent_id,
                            role="assistant",
                            content=reply_content,
                            issue_id=assistant_message["issue_id"],
                            timestamp=assistant_message["timestamp"],
                            activity=current_activity,
                            status=current_status
                        )
                        if success:
                            messages.append(assistant_message)
                            current_dialog.append(assistant_message)
                        else:
                            print("⚠️ AI响应保存失败，将继续尝试")
                            session_data['pending_messages'].append(assistant_message)
                    except Exception as e:
                        print(f"⚠️ 保存AI响应异常: {e}")
                        session_data['pending_messages'].append(assistant_message)

                # 更新会话状态
                session_data['conversation_counter'] += 1

                # 检查是否继续对话
                if session_data['conversation_counter'] >= max_conversation_turns:
                    print(f"⚠️ 达到最大对话轮数 {max_conversation_turns}，结束对话")
                    session_data['waiting_for_input'] = False
                    return messages, name, session_data

                if current_status != "空闲":
                    print(f"{name}: 我得继续{current_activity}了，我们晚点再聊")
                    session_data['waiting_for_input'] = False
                    return messages, name, session_data

                # 设置等待用户输入状态
                session_data['waiting_for_input'] = True
                return messages, name, session_data

            except Exception as e:
                print(f"⚠️ 处理AI响应失败: {str(e)}")
                session_data['waiting_for_input'] = True
                return messages, name, session_data

    except Exception as e:
        print(f"⚠️ 主循环发生错误: {e}")
        try:
            # 保存当前对话状态
            print("💾💾💾💾💾 尝试保存异常状态下的对话记录...")
            for msg in current_dialog[-2:]:  # 只保存最后两条未保存的消息
                if 'saved' not in msg:
                    with db as db_conn:
                        success = db_conn.insert_agent_message(
                            user_id=user_id,
                            agent_id=agent_id,
                            role=msg["role"],
                            content=msg["content"],
                            issue_id=msg.get("issue_id", generate_issue_id()),
                            timestamp=msg["timestamp"],
                            activity=msg.get("activity", "未知"),
                            status=msg.get("status", "空闲")
                        )
                    if success:
                        msg['saved'] = True
        except Exception as save_error:
            print(f"❌❌❌❌ 无法保存异常状态: {save_error}")

        session_data['waiting_for_input'] = True
        return messages, name, session_data

    # 最终保存完整的对话记录到数据库（已增量保存，此处只做确认）
    try:
        unsaved_count = sum(1 for msg in current_dialog if 'saved' not in msg)
        if unsaved_count > 0:
            print(f"⚠️ 检测到 {unsaved_count} 条未保存消息，尝试最终保存...")
            for msg in current_dialog:
                if 'saved' not in msg:
                    with db as db_conn:
                        success = db_conn.insert_agent_message(
                            user_id=user_id,
                            agent_id=agent_id,
                            role=msg["role"],
                            content=msg["content"],
                            issue_id=msg.get("issue_id", generate_issue_id()),
                            timestamp=msg["timestamp"],
                            activity=msg.get("activity", "未知"),
                            status=msg.get("status", "空闲")
                        )
                    if success:
                        msg['saved'] = True
    except Exception as e:
        print(f"❌❌❌ 最终保存对话记录失败: {e}")

    session_data['waiting_for_input'] = True
    return messages, name, session_data