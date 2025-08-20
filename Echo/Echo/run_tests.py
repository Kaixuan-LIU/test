import os
import json
import argparse
from config import config
from interaction_test_tool import InteractionTester
from Agent_builder import AgentBuilder
from database import TEST_DB_CONFIG, MySQLDB
from event_loop_tool import get_intro_event

os.environ["APP_ENV"] = "testing"
API_KEY = "sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV"


def run_single_agent_test(agent_config: str = None,daily_tests: int = 3,event_tests: int = 2):
    """一键运行单个智能体测试"""
    print("=" * 50)
    print("启动智能体测试流程")
    print("=" * 50)

    # 初始化测试工具
    tester = InteractionTester()

    # 步骤1：创建智能体
    agent_id = create_test_agent(agent_config)
    if not agent_id:
        print("❌ 智能体创建失败，测试终止")
        return

    # 步骤2：测试日常对话
    print("\n🔍🔍 测试日常对话交互...")
    tester.test_daily_interaction(agent_id, num_tests=daily_tests)

    # 步骤3：测试事件交互
    print("\n🔍🔍 测试事件交互...")
    event_id = get_first_event(agent_id)
    if event_id:
        tester.test_event_interaction(agent_id, event_id, num_tests=event_tests)
    else:
        print("⚠️ 未找到初始事件，跳过事件测试")

    # 步骤4：显示测试结果
    print("\n📋 测试结果摘要:")
    tester.show_test_summary()

    print("=" * 50)
    print("测试流程完成")
    print("=" * 50)
    return True


def create_test_agent(agent_config=None):
    """创建测试用智能体"""
    builder = AgentBuilder(api_key=API_KEY, user_id=0)  # 测试用户ID=0

    # 智能体基础设定
    user_input = agent_config if agent_config else """
    世界观：现代都市
    姓名：测试员小智
    年龄：25
    职业：软件测试工程师
    爱好：发现bug、编写测试用例
    性格：严谨细致，善于分析
    """

    print("🧪 正在生成测试智能体...")
    agent_data = builder.build_agent(user_input)

    if not agent_data or "agent_id" not in agent_data:
        print("❌ 智能体创建失败")
        return None

    agent_id = agent_data["agent_id"]
    print(f"✅ 测试智能体创建成功! ID: {agent_id}")
    return agent_id


def get_first_event(agent_id):
    """获取智能体的初始事件ID"""
    with MySQLDB(**TEST_DB_CONFIG) as db:
        events_data = db.get_agent_event_chains(agent_id)
        if not events_data:
            return None

        # 解析事件树
        event_tree = json.loads(events_data[0]['chain_json'])
        intro_event = get_intro_event(event_tree.get('event_tree', []))

        return intro_event.get('event_id') if intro_event else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="智能体测试工具")
    parser.add_argument('--agent-config', help='智能体配置文件路径')
    parser.add_argument('--daily-tests', type=int, default=3, help='日常对话测试轮数')
    parser.add_argument('--event-tests', type=int, default=2, help='事件交互测试轮数')

    args = parser.parse_args()

    # 处理自定义配置
    agent_config_content = None
    if args.agent_config:
        try:
            with open(args.agent_config, 'r', encoding='utf-8') as f:
                agent_config_content = f.read()
        except Exception as e:
            print(f"❌❌ 读取智能体配置文件失败: {e}")
            exit(1)

    # 运行测试（传递所有参数）
    run_single_agent_test(
        agent_config=agent_config_content,
        daily_tests=args.daily_tests,
        event_tests=args.event_tests)

