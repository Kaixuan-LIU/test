import os
import json
import argparse
from app_config import config
from interaction_test_tool import InteractionTester
from Agent_builder import AgentBuilder
from database import TEST_DB_CONFIG, MySQLDB, DB_CONFIG
from event_loop_tool import get_intro_event

os.environ["APP_ENV"] = "testing"
API_KEY = "sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV"


def run_single_agent_test(agent_id: int = None, agent_config: str = None,
                         daily_tests: int = 3, event_tests: int = 2):
    """一键运行单个智能体测试，优先使用指定的agent_id"""
    print("=" * 50)
    print("启动智能体测试流程")
    print("=" * 50)

    # 初始化测试工具
    tester = InteractionTester(init_test_db=False)
    # 步骤1：获取智能体ID（优先使用指定的已有智能体）
    if not agent_id:
        agent_id = create_test_agent(agent_config)
        if not agent_id:
            print("❌ 智能体创建失败，测试终止")
            return
    else:
        # 验证指定的agent_id是否存在
        with MySQLDB(** TEST_DB_CONFIG) as db:
            agent = db.get_agent_by_id(agent_id)
            if not agent:
                print(f"❌ 数据库中未找到agent_id: {agent_id}")
                return
        print(f"✅ 使用已有智能体进行测试! ID: {agent_id}")

    # 步骤2：测试日常对话
    print("\n🔍🔍 测试日常对话交互...")
    tester.test_daily_interaction(agent_id, num_tests=daily_tests)

    # # 步骤3：测试事件交互
    # print("\n🔍🔍 测试事件交互...")
    # event_id = get_first_event(agent_id)
    # if event_id:
    #     tester.test_event_interaction(agent_id, event_id, num_tests=event_tests)
    # else:
    #     print("⚠️ 未找到初始事件，跳过事件测试")

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
    with MySQLDB(** TEST_DB_CONFIG) as db:
        events_data = db.get_agent_event_chains(agent_id)
        if not events_data:
            return None

        # 解析事件树
        event_tree = json.loads(events_data[0]['chain_json'])
        intro_event = get_intro_event(event_tree.get('event_tree', []))

        return intro_event.get('event_id') if intro_event else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行智能体日常事件测试")
    parser.add_argument("--agent_id", type=int, help="指定已有智能体ID（可选）")
    parser.add_argument("--agent_config", type=str, help="智能体配置（可选，当不指定agent_id时使用）")
    parser.add_argument("--daily_tests", type=int, default=3, help="日常测试次数")
    parser.add_argument("--event_tests", type=int, default=2, help="事件测试次数")
    args = parser.parse_args()

    run_single_agent_test(
        agent_id=args.agent_id,
        agent_config=args.agent_config,
        daily_tests=args.daily_tests,
        event_tests=args.event_tests
    )

