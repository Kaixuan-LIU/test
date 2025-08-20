import os
import json
import random
import time
import pymysql
from config import config
from datetime import datetime
from database import MySQLDB, DB_CONFIG, TEST_DB_CONFIG
from api_handler import ChatFireAPIClient
from daily_loop_tool import run_daily_loop
from event_loop_tool import run_event_loop
from main import API_KEY


class InteractionTester:
    def __init__(self, api_key: str = None):
        """
        初始化测试工具
        参数:
            api_key: API密钥
            db_config: 数据库配置
        """
        self.api_key = api_key or config.API_KEY
        self.db = MySQLDB(**config.DB_CONFIG, test_mode=True)
        self.client = ChatFireAPIClient(api_key=api_key)
        self.test_log = {
            "start_time": datetime.now().isoformat(),
            "tests": []
        }
        self._init_test_db()

    def _get_test_db_config(self, prod_config: dict) -> dict:
        """生成测试数据库配置（添加_test后缀）"""
        return {
            "host": prod_config["host"],
            "user": prod_config["user"],
            "password": prod_config["password"],
            "database": prod_config["database"] + "_test",  # 关键区别
            "port": prod_config["port"],
            "charset": prod_config["charset"]
        }

    def _init_test_db(self):
        """初始化测试数据库：创建表结构 & 插入基础数据"""
        print("\n🔧 初始化测试数据库...")
        with self.db as db_conn:
            try:
                # 1. 创建测试专用表
                db_conn._execute_update("""
                                        CREATE TABLE IF NOT EXISTS test_agents
                                        (agent_id INT AUTO_INCREMENT PRIMARY KEY,
                                        name VARCHAR (100) NOT NULL,
                                        profession VARCHAR (50) NOT NULL)
                                        """)

                # 2. 清空历史测试数据
                db_conn._execute_update("TRUNCATE TABLE test_agents")

                # 3. 插入基础测试数据
                test_agents = [
                    ("医生小李", "医生"),
                    ("作家小王", "小说家"),
                    ("律师老张", "律师")
                ]
                for name, profession in test_agents:
                    db_conn._execute_update(
                        "INSERT INTO test_agents (name, profession) VALUES (%s, %s)",
                        (name, profession)
                    )

                print("✅ 测试数据库初始化完成 (插入3条测试智能体记录)")

            except Exception as e:
                print(f"❌ 测试数据库初始化失败: {str(e)}")
                raise
    def _log_test(self, test_type: str, agent_id: int, event_id: str = None, conversation: list = None):
        """记录测试日志"""
        test_entry = {
            "timestamp": datetime.now().isoformat(),
            "test_type": test_type,
            "agent_id": agent_id,
            "event_id": event_id,
            "conversation": conversation or []
        }
        self.test_log["tests"].append(test_entry)

        # 实时保存日志
        self.save_test_log()

    def save_test_log(self, filename: str = "interaction_test_log.json"):
        """保存测试日志到文件"""
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.test_log, f, ensure_ascii=False, indent=2)

    def test_daily_interaction(self, agent_id: int, num_tests: int = 3):
        """
        测试日常对话交互功能
        参数:
            agent_id: 智能体ID
            num_tests: 测试次数
        """
        print(f"\n{'=' * 50}")
        print(f"开始测试日常对话交互 (agent_id: {agent_id})")
        print(f"{'=' * 50}")

        # 从测试数据库获取数据
        with self.db as db_conn:
            agent_data = db_conn._execute_query(
                "SELECT * FROM test_agents WHERE agent_id = %s",
                (agent_id,)
            )
        if not agent_data:
            print(f"❌ 未找到测试智能体 ID: {agent_id}")
            return

        agent_info = agent_data[0]
        if not agent_info:
            print(f"❌ 无法加载智能体信息 (agent_id: {agent_id})")
            return

        # 加载智能体目标
        goals = self._load_agent_goals(agent_id)
        if not goals:
            print(f"⚠️ 无法加载智能体目标，使用空目标 (agent_id: {agent_id})")
            goals = {"goals": []}

        # 加载事件链
        event_tree = self._load_event_chain(agent_id)
        if not event_tree:
            print(f"⚠️ 无法加载事件链，使用空事件链 (agent_id: {agent_id})")
            event_tree = []

            # 生成智能体特定的测试用例
            test_cases = self._generate_daily_test_cases(agent_info, num_tests)

            for i, test_case in enumerate(test_cases):
                print(f"\n测试 #{i + 1}/{num_tests} - 主题: {test_case['theme']}")
                conversation_log = []

                # 模拟日常对话交互
                session_data = None
                user_input = test_case["initial_input"]

                for step in range(3):  # 模拟3轮对话
                    # 记录用户输入
                    conversation_log.append({
                        "role": "user",
                        "content": user_input,
                        "step": step,
                        "timestamp": datetime.now().isoformat()
                    })

                    # 执行日常交互
                    messages, _, session_data = run_daily_loop(
                        agent_profile=agent_info,
                        goals=goals,
                        event_tree=event_tree,
                        agent_id=agent_id,
                        user_id=0,  # 测试用户ID
                        user_input=user_input,
                        session_data=session_data
                    )

                    # 记录智能体回复
                    if messages:
                        ai_replies = [msg for msg in messages if msg['role'] == 'assistant']
                        if ai_replies:
                            last_reply = ai_replies[-1]
                            conversation_log.append({
                                "role": "assistant",
                                "content": last_reply['content'],
                                "step": step,
                                "timestamp": datetime.now().isoformat()
                            })
                            print(f"智能体回复: {last_reply['content']}")

                    # 检查是否结束对话
                    if not session_data or session_data.get('exit_requested'):
                        print("🛑 对话已结束")
                        break

                        # 生成下一轮用户输入
                    if step < 2:  # 最后一轮不需要生成新输入
                        user_input = self._generate_followup_response(
                            conversation_log,
                            agent_info,
                            test_case["theme"]
                        )
                        print(f"用户输入: {user_input}")

                    # 记录本次测试
                self._log_test("daily", agent_id, conversation=conversation_log)

                # 评估对话质量
                self._evaluate_conversation(conversation_log, agent_info)

            print(f"\n{'=' * 50}")
            print("日常对话交互测试完成")
            print(f"{'=' * 50}")

    def _load_agent_goals(self, agent_id: int) -> dict:
        """从数据库加载智能体目标"""
        try:
            with self.db as db:
                goals_data = db.get_agent_goals(agent_id)
                if goals_data and len(goals_data) > 0:
                    return json.loads(goals_data[0]['goals_json'])
        except Exception as e:
            print(f"❌ 加载智能体目标失败: {e}")
        return None

    def test_event_interaction(self, agent_id: int, event_id: str, num_tests: int = 2):
        """测试事件交互功能"""
        print(f"\n{'=' * 50}")
        print(f"开始测试事件交互 (agent_id: {agent_id}, event_id: {event_id})")
        print(f"{'=' * 50}")

        # 加载智能体信息
        agent_info = self._load_agent_info(agent_id)
        if not agent_info:
            print(f"❌ 无法加载智能体信息 (agent_id: {agent_id})")
            return

        # 加载事件链
        event_chain = self._load_event_chain(agent_id)
        if not event_chain:
            print(f"❌ 无法加载事件链 (agent_id: {agent_id})")
            return

        # 查找目标事件
        target_event = self._find_event(event_chain, event_id)
        if not target_event:
            print(f"❌ 未找到事件ID: {event_id}")
            return

        # 生成事件特定的测试用例
        test_cases = self._generate_event_test_cases(target_event, num_tests)

        for i, test_case in enumerate(test_cases):
            print(f"\n测试 #{i + 1}/{num_tests} - 场景: {test_case['scene']}")
            conversation_log = []

            # 执行事件交互
            for step in range(3):  # 模拟3轮对话
                user_input = test_case["inputs"][step] if step < len(test_case["inputs"]) else ""

                # 记录用户输入
                conversation_log.append({
                    "role": "user",
                    "content": user_input,
                    "step": step,
                    "timestamp": datetime.now().isoformat()
                })

                # 执行事件交互
                response = run_event_loop(
                    user_id=0,  # 测试用户ID
                    agent_id=agent_id,
                    event_id=event_id,
                    user_input=user_input
                )

                # 记录智能体回复
                if response and "content" in response:
                    conversation_log.append({
                        "role": "assistant",
                        "content": response["content"],
                        "step": step,
                        "timestamp": datetime.now().isoformat()
                    })
                    print(f"智能体回复: {response['content']}")

            # 记录本次测试
            self._log_test("event", agent_id, event_id, conversation_log)

            # 评估对话质量
            self._evaluate_conversation(conversation_log, agent_info, target_event)

        print(f"\n{'=' * 50}")
        print("事件交互测试完成")
        print(f"{'=' * 50}")

    def _generate_daily_test_cases(self, agent_info: dict, num_cases: int) -> list:
        """生成智能体特定的日常测试用例"""
        profession = agent_info.get("职业", "未知")
        characteristics = agent_info.get("特征标签", [])

        # 基于职业和特征的测试用例
        test_cases = []
        for i in range(num_cases):
            theme = f"{profession}相关的日常话题"
            if characteristics:
                theme += f" ({random.choice(characteristics)})"

            test_cases.append({
                "theme": theme,
                "initial_input": self._generate_daily_initial_input(agent_info),
                "followup_strategy": random.choice(["深入追问", "话题转移", "情感回应"])
            })

        return test_cases

    def _generate_event_test_cases(self, event: dict, num_cases: int) -> list:
        """生成事件特定的测试用例"""
        test_cases = []
        event_type = event.get("type", "一般事件")

        for i in range(num_cases):
            # 生成事件场景描述
            scene = self._generate_scene_description(event)

            # 生成测试输入序列
            inputs = []
            for step in range(3):
                if step == 0:
                    inputs.append(self._generate_event_initial_input(event))
                else:
                    inputs.append(self._generate_event_followup_input(event))

            test_cases.append({
                "scene": scene,
                "inputs": inputs
            })

        return test_cases

    def _evaluate_conversation(self, conversation: list, agent_info: dict, event_info: dict = None):
        """评估对话质量"""
        # 简单分析对话特征
        user_turns = [msg["content"] for msg in conversation if msg["role"] == "user"]
        ai_turns = [msg["content"] for msg in conversation if msg["role"] == "assistant"]

        # 基本指标
        metrics = {
            "turn_count": len(conversation),
            "user_avg_length": sum(len(t) for t in user_turns) / len(user_turns) if user_turns else 0,
            "ai_avg_length": sum(len(t) for t in ai_turns) / len(ai_turns) if ai_turns else 0,
            "coherence_score": self._calculate_coherence(conversation)
        }

        print(f"\n对话评估结果:")
        print(f"- 对话轮次: {metrics['turn_count']}")
        print(f"- 用户平均输入长度: {metrics['user_avg_length']:.1f}字符")
        print(f"- 智能体平均回复长度: {metrics['ai_avg_length']:.1f}字符")
        print(f"- 连贯性评分: {metrics['coherence_score']}/5.0")

        # 记录评估结果
        self.test_log["tests"][-1]["evaluation"] = metrics

    def _load_agent_info(self, agent_id: int) -> dict:
        """从数据库加载智能体信息"""
        try:
            with self.db as db:
                agent_data = db.get_agent_by_id(agent_id)
                if agent_data and len(agent_data) > 0:
                    return json.loads(agent_data[0]['full_json'])
        except Exception as e:
            print(f"❌ 加载智能体信息失败: {e}")
        return None

    def _load_agent_goals(self, agent_id: int) -> dict:
        """从数据库加载智能体目标"""
        try:
            with self.db as db:
                goals_data = db.get_agent_goals(agent_id)
                if goals_data and len(goals_data) > 0:
                    return json.loads(goals_data[0]['goals_json'])
        except Exception as e:
            print(f"❌ 加载智能体目标失败: {e}")
        return None
    def _load_event_chain(self, agent_id: int) -> list:
        """从数据库加载事件链"""
        try:
            with self.db as db:
                event_data = db.get_agent_event_chains(agent_id)
                if event_data and len(event_data) > 0:
                    chain_json = json.loads(event_data[0]['chain_json'])
                    return chain_json.get('event_tree', [])
        except Exception as e:
            print(f"❌ 加载事件链失败: {e}")
        return []

    def _find_event(self, event_chain: list, event_id: str) -> dict:
        """在事件链中查找特定事件"""
        for stage in event_chain:
            if isinstance(stage, dict) and "事件列表" in stage:
                for event in stage["事件列表"]:
                    if isinstance(event, dict) and event.get("event_id") == event_id:
                        return event
        return None


class DailyInteractionGenerator:
    """生成日常对话测试内容"""

    def __init__(self, agent_profile: dict, api_key: str):
        self.agent_profile = agent_profile
        self.client = ChatFireAPIClient(api_key=api_key)
        self.profession = agent_profile.get('职业', '未知')

        # 职业到话题的映射
        self.profession_topics = {
            "医生": ["健康咨询", "疾病预防", "医疗建议", "体检注意事项"],
            "小说家": ["创作灵感", "文学讨论", "故事构思", "写作技巧"],
            "律师": ["法律咨询", "合同问题", "纠纷解决", "知识产权"],
            "健身教练": ["训练计划", "饮食建议", "运动技巧", "康复训练"],
            "教师": ["教育方法", "学习建议", "课程内容", "考试技巧"],
            "程序员": ["技术难题", "编码实践", "系统架构", "新技术趋势"]
        }

    def generate_daily_context(self) -> str:
        """生成日常对话场景描述"""
        scenarios = {
            "医生": "在医院候诊室偶遇",
            "小说家": "在书店签售会现场",
            "健身教练": "在健身房锻炼时",
            "律师": "在法院大厅等候时",
            "教师": "在学校家长会期间",
            "程序员": "在技术交流会上"
        }
        return scenarios.get(self.profession, "在日常生活中的偶遇")

    def generate_user_input(self) -> str:
        """生成初始用户输入"""
        topics = self.profession_topics.get(self.profession, ["日常话题"])
        topic = random.choice(topics)

        prompts = [
            f"关于{topic}，你有什么建议吗？",
            f"最近我在考虑{topic}相关的事情，你有什么看法？",
            f"我对{topic}很感兴趣，能分享一下你的经验吗？",
            f"我遇到了{topic}的问题，你能帮忙看看吗？"
        ]
        return random.choice(prompts)

    def generate_followup_input(self) -> str:
        """生成后续用户输入"""
        follow_ups = [
            "能详细解释一下吗？",
            "这很有意思，还有其他的吗？",
            "我有个相关问题...",
            "谢谢你的建议！",
            "这对我很有帮助！",
            "我明白了，那么下一步应该怎么做？"
        ]
        return random.choice(follow_ups)


class EventInteractionGenerator:
    """生成事件交互测试内容"""

    def __init__(self, agent_profile: dict, api_key: str):
        self.agent_profile = agent_profile
        self.client = ChatFireAPIClient(api_key=api_key)
        self.profession = agent_profile.get('职业', '未知')

    def _generate_daily_initial_input(self, agent_info: dict) -> str:
        """生成符合智能体特征的初始输入"""
        profession = agent_info.get("职业", "专业人士")
        topics = {
            "医生": ["健康咨询", "疾病预防", "医疗建议"],
            "作家": ["创作灵感", "文学讨论", "写作技巧"],
            "律师": ["法律咨询", "合同问题", "知识产权"],
            # 其他职业...
        }.get(profession, ["专业问题", "行业趋势", "工作经验"])

        topic = random.choice(topics)
        prompts = [
            f"关于{topic}，你有什么建议吗？",
            f"最近我在考虑{topic}相关的事情，你有什么看法？",
            f"我对{topic}很感兴趣，能分享一下你的经验吗？"
        ]
        return random.choice(prompts)

    def _generate_event_initial_input(self, event: dict) -> str:
        """生成事件相关的初始输入"""
        event_type = event.get("type", "一般事件")
        event_name = event.get("name", "当前事件")

        if event_type == "主线事件":
            return random.choice([
                f"关于{event_name}，我需要你的专业意见",
                f"我们应该如何处理{event_name}？"
            ])
        elif event_type == "支线事件":
            return random.choice([
                f"我发现了一个关于{event_name}的细节",
                f"这个{event_name}似乎有问题"
            ])
        else:  # 日常事件
            return random.choice([
                "今天过得怎么样？",
                "最近有什么新鲜事吗？"
            ])

    def _generate_followup_response(self, conversation: list, agent_info: dict, theme: str) -> str:
        """生成基于上下文的后续回应"""
        # 获取最近的对话上下文
        last_ai = next((msg for msg in reversed(conversation) if msg["role"] == "assistant"), None)
        last_user = next((msg for msg in reversed(conversation) if msg["role"] == "user"), None)

        if not last_ai:
            return "请继续说..."

        # 基于AI的最后回复生成后续问题
        prompts = [
            "能详细解释一下吗？",
            "这很有意思，还有其他的吗？",
            "我有个相关问题...",
            "谢谢你的建议！",
            "这对我很有帮助！",
            "我明白了，那么下一步应该怎么做？"
        ]

        # 特定主题的深入问题
        if "健康" in theme:
            prompts.extend(["这种症状应该注意什么？", "有哪些预防措施？"])
        elif "法律" in theme:
            prompts.extend(["这种情况的法律后果是什么？", "有哪些法律依据？"])

        return random.choice(prompts)

def run_tests():
    """运行所有测试"""
    tester = InteractionTester()

    print("\n>>> 测试医生智能体的日常交互")
    tester.test_daily_interaction(agent_id=1)

    print("\n>>> 测试作家智能体的日常交互")
    tester.test_daily_interaction(agent_id=2)

    print("\n>>> 测试医生智能体的事件交互")
    tester.test_event_interaction(agent_id=1, event_id="E001")

    print("\n>>> 测试律师智能体的事件交互")
    tester.test_event_interaction(agent_id=3, event_id="E101")

if __name__ == "__main__":
    run_tests()