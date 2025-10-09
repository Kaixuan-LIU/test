import argparse
import os
import io
import sys
import json
import uuid
import re
import requests
import time
from datetime import datetime
from Agent_builder import AgentBuilder
from Event_builder import EventTreeGenerator
from api_handler import ChatFireAPIClient
from daily_loop_tool import run_daily_loop
from database import MySQLDB, DB_CONFIG
from event_loop_tool import run_event_loop, get_intro_event


API_KEY = "sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV"

sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def safe_input(prompt):
    print(prompt, end='', flush=True)
    return sys.stdin.readline().rstrip('\n')


def run_full_pipeline(user_input: str, user_id: int):
    print("🧠 开始构建智能体...")
    builder = AgentBuilder(api_key=API_KEY, user_id=user_id)
    agent_data = builder.build_agent(user_input)

    if not agent_data or "agent_id" not in agent_data:
        print("❌❌ 智能体构建失败。")
        return None

    agent_id = agent_data["agent_id"]
    name = agent_data["agent_name"]
    # 注意：这里不再直接调用generate_and_save，而是依靠AgentBuilder中的后台线程机制
    print("✅初始化完成，智能体角色与初始事件构建完毕")
    print(f"✅ 智能体构建成功，ID: {agent_data['agent_id']}")

    # 创建数据库连接
    db = MySQLDB(**DB_CONFIG)

    # 1. 从数据库获取智能体完整信息
    with db as db_conn:
        agent_info = db_conn.get_agent_by_id(agent_id)
        if agent_info:
            try:
                formatted_dict = json.loads(agent_info['full_json'])
                print(f"✅ 从数据库加载智能体信息成功（agent_id: {agent_id}）")
            except json.JSONDecodeError as e:
                print(f"❌ 智能体信息JSON解析失败: {e}")
                return None
        else:
            print(f"⚠️ 数据库中未找到智能体信息（agent_id: {agent_id}）")
            return None

    # 2. 从数据库获取目标
    goals = ""
    with MySQLDB(**DB_CONFIG) as db_conn:  # 使用新的数据库连接实例
        goals_data = db_conn.get_agent_goals(agent_id)
        if goals_data:
            try:
                goals = json.loads(goals_data[0]['goals_json'])
                print(f"✅ 从数据库加载目标成功（agent_id: {agent_id}）")
            except json.JSONDecodeError as e:
                print(f"❌ 目标JSON解析失败: {e}")
        else:
            print(f"⚠️ 数据库中未找到目标（agent_id: {agent_id}）")

    # 3. 从数据库获取事件树
    event_tree = []
    with MySQLDB(**DB_CONFIG) as db_conn:  # 使用新的数据库连接实例
        events_data = db_conn.get_agent_event_chains(agent_id)
        if events_data:
            try:
                event_tree = json.loads(events_data[0]['chain_json'])
                print(f"✅ 从数据库加载事件链成功（agent_id: {agent_id}）")
            except json.JSONDecodeError as e:
                print(f"❌ 事件链JSON解析失败: {e}")
        else:
            print(f"⚠️ 数据库中未找到事件链（agent_id: {agent_id}）")

    # 返回agent_id用于等待后台任务
    return agent_id


def evaluate_state_change(messages, agent_profile, goals, event_tree):
    client = ChatFireAPIClient(api_key=API_KEY, default_model="gpt-4o")

    # 按 issue_id 分组对话
    conversations = {}
    for msg in messages:
        if "issue_id" in msg:
            issue_id = msg["issue_id"]
            if issue_id not in conversations:
                conversations[issue_id] = []
            conversations[issue_id].append(msg)

    # 构建提示词
    prompt = f"""
请根据以下内容评估事件结束后智能体的状态变化，并按issue_id分组评估：

【智能体设定】
{json.dumps(agent_profile, ensure_ascii=False, indent=2)}

【目标信息】
{json.dumps(goals, ensure_ascii=False, indent=2)}

【事件链】
{json.dumps(event_tree, ensure_ascii=False, indent=2)}

【对话分组】："""

    for issue_id, msgs in conversations.items():
        prompt += f"\nIssue ID: {issue_id}\n"
        for msg in msgs:
            role = msg["role"]
            content = msg["content"]
            prompt += f"{role}: {content}\n"

    prompt += """
输出格式如下：
{
  "心理状态变化": {
    "心情": "+/-整数",
    "心理健康度": "+/-整数",
    "求知欲": "+/-整数",
    "社交能量": "+/-整数"
  },
  "知识储备变化": {
    "增加": ["新知识1", "新知识2"]
  },
  "事件树状态": {
    "事件ID": "事件编号",
    "状态": "完成/失败/跳过"
  }
}

请严格按照以下JSON格式输出，不要包含任何额外文本：
{
  "心理状态变化": {...},
  "知识储备变化": {...},
  "事件树状态": {...}
}
重要：不要使用Markdown代码块，直接输出纯JSON！
"""

    # 创建默认评估结果
    def create_default_evaluation() -> dict:
        return {
            "心理状态变化": {
                "心情": 0,
                "心理健康度": 0,
                "求知欲": 0,
                "社交能量": 0
            },
            "知识储备变化": {
                "增加": []
            },
            "事件树状态": {
                "事件ID": "",
                "状态": "未完成"
            }
        }

    max_retries = 2
    for attempt in range(max_retries):
        try:
            # 调用API
            response = client.call_api([{"role": "user", "content": prompt}], max_tokens=1500)

            if not response or 'choices' not in response or not response['choices']:
                print(f"⚠️ API响应无效 (尝试#{attempt + 1})")
                continue

            content = response["choices"][0]["message"]["content"]
            print(f"📊 状态评估响应 (尝试#{attempt + 1}):\n{content}\n")

            # 尝试提取JSON内容
            try:
                # 尝试直接解析整个内容
                if content.strip().startswith('{'):
                    return json.loads(content)

                # 尝试提取JSON对象
                start_index = content.find('{')
                end_index = content.rfind('}')
                if start_index != -1 and end_index != -1 and end_index > start_index:
                    json_str = content[start_index:end_index + 1]
                    return json.loads(json_str)

                # 尝试解析代码块
                if '```json' in content:
                    start = content.find('```json') + 7
                    end = content.find('```', start)
                    if end == -1:
                        json_str = content[start:]
                    else:
                        json_str = content[start:end]
                    return json.loads(json_str.strip())

                if '```' in content:
                    start = content.find('```') + 3
                    end = content.find('```', start)
                    if end == -1:
                        json_str = content[start:]
                    else:
                        json_str = content[start:end]
                    return json.loads(json_str.strip())

            except json.JSONDecodeError as e:
                print(f"❌ JSON解析失败 (尝试#{attempt + 1}): {e}")
                continue

        except requests.exceptions.Timeout:
            print(f"⚠️ API请求超时 (尝试#{attempt + 1})")
            time.sleep(1)
        except requests.exceptions.RequestException as e:
            print(f"⚠️ API请求失败 (尝试#{attempt + 1}): {str(e)}")
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ 未知错误 (尝试#{attempt + 1}): {str(e)}")
            time.sleep(1)

    # 所有重试失败后的处理
    print("❌❌ 所有状态评估尝试失败，使用默认评估")
    return create_default_evaluation()


def state_update(agent_id: int, state_result: dict, formatted_text: str, goals: str, event_tree: str):
    # 创建数据库连接
    db = MySQLDB(**DB_CONFIG)

    # 更新数据库
    try:
        # 更新智能体信息
        with db as db_conn:
            update_sql = """
                UPDATE agents 
                SET full_json = %s 
                WHERE agent_id = %s
            """
            params = (json.dumps(formatted_text), agent_id)
            db_conn._execute_update(update_sql, params)
            print("✅ 智能体信息已更新到数据库")

        # 更新目标
        with db as db_conn:
            # 获取最新的goal_id
            goals_list = db_conn.get_agent_goals(agent_id)
            if goals_list:
                latest_goal_id = goals_list[0]["goal_id"]
                update_sql = """
                    UPDATE agent_goals_json 
                    SET goals_json = %s 
                    WHERE goal_id = %s
                """
                params = (json.dumps(goals), latest_goal_id)
                db_conn._execute_update(update_sql, params)
                print("✅ 目标已更新到数据库")

        # 更新事件链
        with db as db_conn:
            # 获取最新的chain_id
            chains_list = db_conn.get_agent_event_chains(agent_id)
            if chains_list:
                latest_chain_id = chains_list[0]["chain_id"]
                update_sql = """
                    UPDATE agent_event_chains 
                    SET chain_json = %s 
                    WHERE chain_id = %s
                """
                params = (json.dumps(event_tree), latest_chain_id)
                db_conn._execute_update(update_sql, params)
                print("✅ 事件链已更新到数据库")

    except Exception as e:
        print(f"❌ 数据库更新失败: {e}")

    return {
        "formatted": formatted_text,
        "goals": goals,
        "full_event_tree": event_tree
    }


def select_next_event(full_event_tree) -> dict:
    if not full_event_tree:
        return None

    current_time = datetime.now().strftime("%H:%M")

    for stage in full_event_tree:
        # 检查阶段时间范围有效性
        if not is_valid_time_range(stage.get("时间范围", "")):
            continue

        for event in stage.get("事件列表", []):
            event_status = event.get("状态", "未开始")
            event_time = event.get("event_time", "")

            # 只返回当前时间段内未完成的事件
            if (event_status != "完成" and
                    event_time <= current_time):
                return event

    return None  # 无有效事件

def get_intro_event(event_tree: list) -> dict:
    # 检查是否是分层结构（包含阶段）
    if isinstance(event_tree[0], dict) and "事件列表" in event_tree[0]:
        for stage in event_tree:
            events = stage.get("事件列表", [])
            for event in events:
                if isinstance(event, dict) and event.get("event_id") == "E001":
                    return event
    else:
        for event in event_tree:
            if isinstance(event, dict) and event.get("event_id") == "E001":
                return event
    return None

def is_valid_time_range(time_range: str) -> bool:
    """验证时间范围格式是否正确"""
    if not time_range or "~" not in time_range:
        return False

    try:
        start, end = time_range.split("~")
        datetime.strptime(start.strip(), "%H:%M")
        datetime.strptime(end.strip(), "%H:%M")
        return True
    except:
        return False


def check_event_chain_status(agent_id: int, user_id: int = 1):
    """检查指定智能体的事件链生成状态"""
    # 获取智能体名称
    db = MySQLDB(**DB_CONFIG)
    with db as db_conn:
        agent_info = db_conn.get_agent_by_id(agent_id)
        if not agent_info:
            print(f"❌ 未找到agent_id={agent_id}的智能体")
            return

        try:
            agent_data = json.loads(agent_info['full_json'])
            agent_name = agent_data.get('姓名', '未知')
        except json.JSONDecodeError:
            print(f"❌ 解析agent_id={agent_id}的智能体信息失败")
            return

    # 创建事件树生成器实例
    generator = EventTreeGenerator(
        agent_name=agent_name,
        api_key=API_KEY,
        agent_id=agent_id,
        user_id=user_id,
        agent_builder=None  # 此处不需要agent_builder实例
    )

    # 检查生成状态
    status = generator.check_background_generation_status()

    status_messages = {
        "not_started": "尚未开始生成",
        "in_progress": "正在后台生成中",
        "completed": "生成已完成",
        "failed": "生成失败"
    }

    print(f"📊 智能体 {agent_name} (ID: {agent_id}) 的事件链生成状态: {status_messages.get(status, '未知状态')}")
    return status


def wait_for_background_task_completion(agent_id: int, timeout: int = 300):
    """等待后台任务完成"""
    from Event_builder import EventTreeGenerator
    from Agent_builder import AgentBuilder

    print(f"⏳ 等待后台事件链生成完成 (agent_id: {agent_id})，超时时间: {timeout}秒")

    # 创建事件树生成器实例用于检查状态
    db = MySQLDB(**DB_CONFIG)
    try:
        with db as db_conn:
            agent_info = db_conn.get_agent_by_id(agent_id)
            if agent_info:
                import json
                agent_data = json.loads(agent_info['full_json'])
                agent_name = agent_data.get('姓名', '未知')
            else:
                agent_name = "未知"
    except:
        agent_name = "未知"

    generator = EventTreeGenerator(
        agent_name=agent_name,
        api_key=API_KEY,
        agent_id=agent_id,
        user_id=1,
        agent_builder=None
    )

    start_time = time.time()
    while time.time() - start_time < timeout:
        status = generator.check_background_generation_status()
        if status == "completed":
            print(f"✅ 后台事件链生成已完成 (agent_id: {agent_id})")
            return True
        elif status == "failed":
            print(f"❌ 后台事件链生成失败 (agent_id: {agent_id})")
            return False
        else:
            print(f"🔄 后台事件链生成中... 当前状态: {status}")
            time.sleep(10)  # 每10秒检查一次

    print(f"⏰ 等待超时，后台事件链生成可能仍在进行中 (agent_id: {agent_id})")
    return False


def main():
    parser = argparse.ArgumentParser(description="AI 虚拟智能体主程序")
    parser.add_argument('--init', action='store_true', help='初始化主角与事件链')
    parser.add_argument('--daily', action='store_true', help='进入日常互动')
    parser.add_argument('--event', action='store_true', help='运行独立事件循环')
    parser.add_argument('--check-status', action='store_true', help='检查事件链生成状态')
    parser.add_argument('--wait-background', action='store_true', help='等待后台事件链生成完成')
    parser.add_argument('--user_id', type=int, default=1, help='用户ID')
    parser.add_argument('--agent_id', type=int, help='智能体ID（用于日常互动）')
    parser.add_argument('--event_id', type=str, help='事件ID')
    parser.add_argument('--session_id', type=str, help='会话ID（用于继续对话）')
    args = parser.parse_args()

    if args.init:
        print("🧠 初始化智能体...")
        print("请输入角色设定（示例：世界观：现实世界 姓名：萧炎 年龄：16 职业：高中生 爱好：音乐、吉他）")
        user_input = safe_input(">>> ")
        agent_id = run_full_pipeline(user_input, args.user_id)

        # 如果指定了等待后台任务完成
        if args.wait_background and agent_id:
            wait_for_background_task_completion(agent_id)

    elif args.daily:
        if not args.agent_id:
            print("❌ 请提供智能体ID（使用 --agent_id 参数）")
            return
        print(f"🚀 启动日常互动（agent_id: {args.agent_id}, user_id: {args.user_id}）")
        db = MySQLDB(**DB_CONFIG)

        # 获取智能体信息
        with db as db_conn:
            agent_info = db_conn.get_agent_by_id(args.agent_id)
            if agent_info:
                try:
                    formatted_dict = json.loads(agent_info['full_json'])
                    print(f"✅ 从数据库加载智能体信息成功（agent_id: {args.agent_id}）")
                except json.JSONDecodeError as e:
                    print(f"❌ 智能体信息JSON解析失败: {e}")
                    return
            else:
                print(f"⚠️ 数据库中未找到智能体信息（agent_id: {args.agent_id}）")
                return

        # 获取目标
        goals = ""
        with db as db_conn:
            goals_data = db_conn.get_agent_goals(args.agent_id)
            if goals_data:
                try:
                    goals = json.loads(goals_data[0]['goals_json'])
                    print(f"✅ 从数据库加载目标成功（agent_id: {args.agent_id}）")
                except json.JSONDecodeError as e:
                    print(f"❌ 目标JSON解析失败: {e}")
            else:
                print(f"⚠️ 数据库中未找到目标（agent_id: {args.agent_id}）")

        # 获取事件树
        event_tree = []
        with db as db_conn:
            events_data = db_conn.get_agent_event_chains(args.agent_id)
            if events_data:
                try:
                    event_tree = json.loads(events_data[0]['chain_json'])
                    print(f"✅ 从数据库加载事件链成功（agent_id: {args.agent_id}）")
                except json.JSONDecodeError as e:
                    print(f"❌ 事件链JSON解析失败: {e}")
            else:
                print(f"⚠️ 数据库中未找到事件链（agent_id: {args.agent_id}）")

        session_data = None
        conversation_active = True

        messages, name, session_data, session_id = run_daily_loop(
            formatted_dict,
            goals,
            event_tree,
            args.agent_id,
            args.user_id,
            None,  # 首次不传递用户输入
            session_data
        )

        # 主交互循环
        while conversation_active:
            # 检查退出请求
            if session_data and session_data.get('exit_requested', False):
                print("✅ 对话已正常退出")
                break

            # 仅在等待输入时才提示用户
            if session_data.get('waiting_for_input', True):
                user_input = safe_input(f"你对 {name} 说：")
            else:
                user_input = None

            # 运行日常互动
            messages, name, session_data, session_id = run_daily_loop(
                formatted_dict,
                goals,
                event_tree,
                args.agent_id,
                args.user_id,
                user_input,
                session_data
            )

            should_exit = (
                    not session_data.get('waiting_for_input', True) or
                    session_data.get('exit_requested', False)
            )
            if should_exit:
                conversation_active = False

        if not session_data.get('exit_requested', False):
            if messages:
                print("📊 开始状态评估...")
                state_result = evaluate_state_change(messages, formatted_dict, goals, event_tree)

                # 状态更新
                print("🔄 更新智能体状态...")
                state_update(args.agent_id, state_result, formatted_dict, goals, event_tree)

            else:
                print("⚠️ 无对话消息，跳过状态评估")

        else:
            print("ℹ️ 可用命令: --init | --daily")

    elif args.check_status:
        if not args.agent_id:
            print("❌ 请提供智能体ID（使用 --agent_id 参数）")
            return
        check_event_chain_status(args.agent_id, args.user_id)

    elif args.event:
        if not args.agent_id or not args.event_id:
            print("❌ 请提供智能体ID和事件ID（使用 --agent_id 和 --event_id 参数）")
            return

        # 加载智能体信息
        with MySQLDB(**DB_CONFIG) as db_conn:
            agent_data = db_conn.get_agent(args.agent_id)
            if not agent_data:
                print(f"❌ 未找到智能体（agent_id: {args.agent_id}）")
                return

            try:
                formatted_dict = json.loads(agent_data[0]["full_json"])
                name = formatted_dict.get("姓名", "智能体")
                print(f"✅ 从数据库加载智能体信息成功（agent_id: {args.agent_id}）")
            except Exception as e:
                print(f"❌ 解析智能体信息失败: {e}")
                return

            # 加载目标
            goals_data = db_conn.get_agent_goals(args.agent_id)
            goals = []
            if goals_data:
                try:
                    goals = json.loads(goals_data[0]['goals_json'])
                    print(f"✅ 从数据库加载目标成功（agent_id: {args.agent_id}）")
                except Exception as e:
                    print(f"⚠️ 解析目标失败: {e}")
            else:
                print(f"⚠️ 数据库中未找到目标（agent_id: {args.agent_id}）")

            # 加载事件链
            event_tree = []
            events_data = db_conn.get_agent_event_chains(args.agent_id)
            if events_data:
                try:
                    chain_data = json.loads(events_data[0]['chain_json'])
                    event_tree = chain_data.get('event_tree', [])
                    if event_tree:
                        print(f"✅ 从数据库加载事件链成功（agent_id: {args.agent_id}）")
                    else:
                        print(f"⚠️ 数据库中事件链为空（agent_id: {args.agent_id}）")
                except json.JSONDecodeError as e:
                    print(f"❌ 事件链JSON解析失败: {e}")
            else:
                print(f"⚠️ 数据库中未找到事件链（agent_id: {args.agent_id}）")

        # 查找目标事件
        target_event = None
        if args.event_id == "E001":
            target_event = get_intro_event(event_tree)
        else:
            # 遍历所有阶段查找事件
            for stage in event_tree:
                if isinstance(stage, dict) and "事件列表" in stage:
                    for event in stage["事件列表"]:
                        if isinstance(event, dict) and event.get("event_id") == args.event_id:
                            target_event = event
                            break
                    if target_event:
                        break

        # 检查是否找到了目标事件
        if not target_event:
            print(f"❌❌❌ 未找到事件ID: {args.event_id}")
            # 检查事件树是否为空
            if not event_tree:
                print("⚠️ 事件树为空，请确认智能体是否已正确初始化并生成了事件链")
            return

        # 获取用户输入
        user_input = safe_input(f"请输入对话内容 (事件:{target_event.get('name', '未命名事件')}): ")

        # 运行事件循环
        result = run_event_loop(
            user_id=args.user_id,
            agent_id=args.agent_id,
            event_id=args.event_id,
            user_input=user_input,
            session_id=args.session_id,  # 添加session_id参数
            event_tree=event_tree if not args.session_id else None  # 如果有session_id则不需要event_tree
        )

        # 打印智能体回复
        if "content" in result:
            print(f"\n{name}> {result['content']}\n")
        else:
            print(f"❌ 未收到智能体回复: {result}")

if __name__ == "__main__":
    main()