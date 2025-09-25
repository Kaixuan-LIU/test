import argparse
import os
import json
import random
import re
import time
import pymysql
from app_config import config
from datetime import datetime
from database import TEST_DB_CONFIG, MySQLDB, DB_CONFIG
from api_handler import ChatFireAPIClient
from daily_loop_tool import run_daily_loop
from event_loop_tool import run_event_loop
from main import API_KEY


class InteractionTester:
    def __init__(self, api_key: str = None, user_api_key: str = None, init_test_db: bool = False):
        """
        初始化测试工具
        参数:
            init_test_db: 是否初始化测试数据库（默认不初始化，避免删除数据）
        """
        self.api_key = api_key or config.API_KEY
        self.user_api_key = user_api_key or self.api_key
        self.client = ChatFireAPIClient(api_key=self.api_key)
        self.user_model_client = ChatFireAPIClient(api_key=self.user_api_key)
        self.db = MySQLDB(** TEST_DB_CONFIG)
        self.test_log = {
            "start_time": datetime.now().isoformat(),
            "tests": []
        }
        # 仅当 init_test_db 为 True 时才执行初始化
        if init_test_db:
            self._init_test_db()
        self.report_dir = "test_reports"
        if not os.path.exists(self.report_dir):
            os.makedirs(self.report_dir)
            print(f"✅ 创建测试报告文件夹: {self.report_dir}")

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
                                        CREATE TABLE IF NOT EXISTS agents
                                        (agent_id INT AUTO_INCREMENT PRIMARY KEY,
                                        name VARCHAR (100) NOT NULL,
                                        profession VARCHAR (50) NOT NULL)
                                        """)

                # 2. 清空历史测试数据
                db_conn._execute_update("TRUNCATE TABLE agents")

                # 3. 插入基础测试数据
                test_agents = [
                    ("医生小李", "医生"),
                    ("作家小王", "小说家"),
                    ("律师老张", "律师")
                ]
                for name, profession in test_agents:
                    db_conn._execute_update(
                        "INSERT INTO agents (name, profession) VALUES (%s, %s)",
                        (name, profession)
                    )

                print("✅ 测试数据库初始化完成 (插入3条测试智能体记录)")

            except Exception as e:
                print(f"❌ 测试数据库初始化失败: {str(e)}")
                raise
    def _log_test(self, test_type: str, agent_id: int, session_id: str = None, conversation: list = None):
        """记录测试日志"""
        test_entry = {
            "timestamp": datetime.now().isoformat(),
            "test_type": test_type,
            "agent_id": agent_id,
            "session_id": session_id,
            "conversation": conversation or []
        }
        self.test_log["tests"].append(test_entry)

        # 实时保存日志
        self.save_test_log()

    def save_test_log(self, filename: str = None):
        """保存测试日志到文件"""
        # 如果没有提供文件名，则生成带时间戳的唯一文件名
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"interaction_test_log_{timestamp}.json"
        
        filepath = os.path.join(self.report_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.test_log, f, ensure_ascii=False, indent=2)
        print(f"💾 测试日志已保存至 {filepath}")

    def test_daily_interaction(self, agent_id: int, num_tests: int = 3, max_turns: int = 10):
        print(f"\n{'=' * 50}")
        print(f"开始双模型日常对话交互测试 (agent_id: {agent_id})")
        print(f"{'=' * 50}")
        termination_keywords = [
            "我们晚点再聊",
            "我得继续",
            "先不聊了",
            "结束对话",
            "下次再聊"
        ]

        with self.db as db_conn:
            agent_info = db_conn.get_agent_by_id(agent_id)
        if not agent_info:
            print(f"❌ 未找到智能体 ID: {agent_id}")
            return

        try:
            full_json = json.loads(agent_info['full_json'])
            agent_name = full_json.get('姓名', '未知姓名')  # 从 full_json 取姓名
            profession = full_json.get('职业', '未知职业')  # 从 full_json 取职业
        except json.JSONDecodeError:
            agent_name = '未知姓名'
            profession = '未知职业'

        agent_parsed_info = {
            'agent_id': agent_id,
            'agent_name': agent_name,
            'profession': profession,
            'full_json': agent_info.get('full_json', '{}')
        }

        goals = self._load_agent_goals(agent_id) or {"goals": []}
        event_tree = self._load_event_chain(agent_id) or []
        # 生成测试用例时传入解析后的信息
        test_cases = self._generate_daily_test_cases(agent_parsed_info, num_tests)

        for i, test_case in enumerate(test_cases):
            print(f"\n测试 #{i + 1}/{num_tests} - 主题: {test_case['theme']}")
            conversation_log = []
            session_id = None
            turn_count = 0
            conversation_active = True
            agent_busy_and_unwilling = False  # 新增：标记智能体忙碌且不愿继续

            user_input = test_case["initial_input"]
            print(f"用户初始输入: {user_input}")

            while conversation_active and turn_count < max_turns and not agent_busy_and_unwilling:
                conversation_log.append({
                    "role": "user",
                    "content": user_input,
                    "turn": turn_count,
                    "timestamp": datetime.now().isoformat()
                })

                # 调用日常对话循环
                messages, _, new_session_data, session_id = run_daily_loop(
                    agent_profile=full_json,
                    goals=goals,
                    event_tree=event_tree,
                    agent_id=agent_id,
                    user_id=0,
                    user_input=user_input,
                    session_id=session_id
                )

                if messages:
                    ai_replies = [msg for msg in messages if msg['role'] == 'assistant']
                    if ai_replies:
                        last_reply = ai_replies[-1]
                        conversation_log.append({
                            "role": "assistant",
                            "content": last_reply['content'],
                            "turn": turn_count,
                            "timestamp": datetime.now().isoformat()
                        })
                        print(f"智能体回复: {last_reply['content']}")

                        # 1. 检查智能体状态是否为忙碌
                        is_busy = new_session_data.get('last_status') == '忙碌' or \
                                 any(status in last_reply['content'] for status in ['忙碌', '忙着'])
                        # 2. 检查回复中是否包含终止关键词
                        has_termination = any(kw in last_reply['content'] for kw in termination_keywords)

                        if is_busy and has_termination:
                            print("🛑 检测到智能体忙碌且无继续交流意愿，终止对话")
                            agent_busy_and_unwilling = True
                            conversation_active = False
                            break

                if self._check_termination_condition(conversation_log):
                    print("🛑 检测到终止关键词，对话结束")
                    conversation_active = False
                    break

                turn_count += 1
                # 生成后续回复
                user_input = self._generate_followup_response(
                    conversation_log,
                    agent_parsed_info,
                    test_case["theme"]
                )
                print(f"用户输入 (轮次 {turn_count}): {user_input}")

            self._log_test("daily", agent_id, session_id=session_id, conversation=conversation_log)
            # 不再进行评估，只保存对话记录
            print(f"\n{'=' * 50}")
            print("双模型日常对话交互测试完成")
            print(f"{'=' * 50}")

    def _check_termination_condition(self, conversation_log) -> bool:
        """检查对话是否需要终止（基于关键词）"""
        if not conversation_log:
            return False

        # 提取最后两条回复
        last_two = conversation_log[-2:] if len(conversation_log) >= 2 else conversation_log

        # 终止关键词列表
        termination_keywords = [
            "再见", "拜拜", "结束对话", "下次聊", "先这样吧",
            "对话结束", "我要走了", "改天再聊"
        ]

        # 检查是否包含终止关键词
        for msg in last_two:
            content = msg.get("content", "").lower()
            if any(keyword in content for keyword in termination_keywords):
                return True
        return False

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
            session_id = None  # 定义session_id变量

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
            self._log_test("event", agent_id, session_id, conversation_log)

            # 评估对话质量
            self._evaluate_conversation(conversation_log, agent_info, target_event)

        print(f"\n{'=' * 50}")
        print("事件交互测试完成")
        print(f"{'=' * 50}")

    def _generate_daily_test_cases(self, agent_info, num_tests: int) -> list:
        """生成日常对话测试用例（主题 + 由用户模型生成的初始输入）"""
        test_cases = []
        # 为每个测试用例生成不同主题
        themes = [
            "日常问候与近况交流",
            "职业相关话题讨论",
            "兴趣爱好分享",
            "近期生活琐事聊天",
            "未来计划与安排"
        ]
        # 确保测试用例数量不超过主题池
        selected_themes = random.sample(themes, min(num_tests, len(themes)))

        for theme in selected_themes:
            # 由用户模型生成初始输入（首次对话由用户发起）
            initial_input = self._generate_initial_user_input(agent_info, theme)
            test_cases.append({
                "theme": theme,
                "initial_input": initial_input
            })
        return test_cases

    def _generate_initial_user_input(self, agent_info: dict, theme: str) -> str:
        prompt = f"""
        你需要生成与{agent_info['agent_name']}（职业：{agent_info['profession']}）对话的初始句子。
        对话主题是：{theme}
        要求：
        1. 自然友好，符合日常对话逻辑
        2. 能引导智能体展开话题，话题围绕其职业、兴趣等日常内容
        3. 用户输入要自然生活化，包含场景细节（如"刚下班看到你分享的文章，很有启发"）
        4. 对话要有来有回，富有生活气息（如加入语气词、口语化表达）
        5. 对话简洁亲和，每句话传递的信息不超过3个。
        """
        # 调用用户侧模型生成初始输入
        response = self.user_model_client.call_api(
            [{"role": "user", "content": prompt}],
            max_tokens=100
        )
        if response and 'choices' in response:
            return response['choices'][0]['message']['content'].strip()
        return f"你好，{agent_info['agent_name']}，我们来聊聊{theme}吧。"

    def _generate_followup_response(self, conversation_log: list, agent_info: dict, theme: str) -> str:
        if not conversation_log:
            return "你好，我们继续聊聊吧。"

        context = "\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in conversation_log[-5:]
        ])

        prompt = f"""
        你现在需要模拟与{agent_info['agent_name']}（职业：{agent_info['profession']}）对话的用户。
        对话主题是：{theme}
        请根据以下对话历史，生成自然的后续回复，推动对话继续：

        {context}

        回复要求：
        1. 符合日常对话逻辑，不要太突兀
        2. 长度适中（1-3句话）
        3. 保持与主题相关
        4. 不要使用任何Markdown格式
        """
        # 调用用户侧模型生成后续回复
        response = self.user_model_client.call_api(
            [{"role": "user", "content": prompt}],
            max_tokens=100
        )
        if response and 'choices' in response:
            return response['choices'][0]['message']['content'].strip()
        return "听起来很有意思，能多说说吗？"

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

    def _evaluate_conversation(self, conversation_log: list, agent_parsed_info: dict, test_type: str = "daily"):
        """
        评估对话质量，根据测试类型使用不同的评估标准
        """
        if not conversation_log:
            return {"error": "无对话内容可评估"}

        # 根据测试类型选择不同的评估提示词
        if test_type == "daily":
            prompt = f"""
            你是对话质量评估专家，需基于以下对话内容和智能体信息，从三个核心维度进行精准评分（0-100分，0分最差，100分最优）。评分需结合智能体设定（如职业、性格），并严格遵循各维度细分规则：

            【评估维度及细分规则】
            1. 内容相关性（0-100分的整数）
               - 主题匹配度：对话是否围绕用户发起的核心主题展开，无无关跳转（如用户问"编程技巧"，智能体不应突然聊"烹饪方法"）
               - 关键词呼应：是否有效回应用户提到的关键信息（如用户提"数据分析工具"，智能体应回应该类工具的具体内容）
               - 信息有效性：提供的内容是否与话题相关且有实际意义（避免"不清楚"等无效回应）
               - 无偏离性：是否避免引入与当前话题无关的新话题（如用户讨论"项目进度"，不应突然聊"周末计划"）

            2. 角色一致性（0-100分的整数）
               - 职业特征：是否体现该职业的专业知识、常用术语或行为习惯（如医生应提及"诊断""治疗方案"，而非程序员术语）
               - 性格匹配：语言风格是否符合设定性格（如内向性格应避免过于热情外放的表达）
               - 背景契合：是否与设定的背景经历一致（如"机械表维修师"应熟悉钟表结构，而非讨论航天技术细节）
               - 行为合理性：括号内动作描写（如"拿起螺丝刀"）是否符合角色身份（医生适合"翻看病历"而非"挥舞扳手"）

            3. 对话自然度（0-100分的整数）
               - 口语化表达：是否符合日常交流习惯，无书面化、模板化语句（避免"综上所述""首先"等正式表述）
               - 逻辑连贯性：回复是否基于前文自然延续，无突兀转折（如用户说"天气冷"，不应直接跳转到"工作忙"）
               - 互动适配：是否根据用户语气调整回应风格（用户热情时应积极回应，用户困惑时应耐心解释）
               - 冗余控制：是否简洁明了，无重复内容（如不反复说"是的，你说得对"）

            【智能体信息】
            {json.dumps(agent_parsed_info, ensure_ascii=False, indent=2)}

            【对话内容】
            {json.dumps(conversation_log, ensure_ascii=False, indent=2)}

            【输出格式要求】
            输出格式如下示例：
            【内容相关性】
            评分：80
            理由：主题匹配度高，能有效回应用户提到的"编程技巧"关键词，但存在1次无关跳转（讨论周末计划）
            例子：用户问"Python循环优化技巧"，智能体回复"循环优化可以用列表推导式...对了，周末去爬山吗？"
            
            【角色一致性】
            评分：90
            理由：职业特征明显（多次使用"代码调试""语法检查"等程序员术语），性格符合设定的"严谨内敛"
            例子：智能体说"（推了推眼镜，仔细查看代码）这里的循环条件可能有问题"
            
            【对话自然度】
            评分：75
            理由：口语化表达较好，但存在1次逻辑断裂（用户说"天气冷"，智能体直接跳转至"工作进度"）
            例子：用户说"今天降温了"，智能体回复"本周的开发任务还剩3个模块未完成"

            【整体评价】
            - 总结三个维度的核心表现
            - 指出最突出的优势和最需改进的点
            - 结合智能体设定给出针对性建议

            注意：评分必须基于对话实际内容，理由需具体到细分规则；例子必须是对话中真实存在的片段，不允许虚构。
            """
        else:  # event interaction
            prompt = f"""
            你是对话质量评估专家，需基于以下对话内容、智能体信息和事件背景，从三个核心维度进行精准评分（0-100分，0分最差，100分最优）。

            【评估维度及细分规则】
            1. 内容相关性（0-100分的整数）
               - 事件匹配度：对话是否围绕当前事件主题展开
               - 背景贴合度：是否充分利用事件背景信息进行互动
               - 逻辑连贯性：回复是否符合事件发展逻辑

            2. 角色一致性（0-100分的整数）
               - 职业特征：是否体现该职业的专业知识和行为习惯
               - 性格匹配：语言风格是否符合设定性格
               - 背景契合：是否与设定的背景经历一致

            3. 交互有效性（0-100分的整数）
               - 用户引导：是否有效引导用户参与事件发展
               - 决策点设置：是否在合适时机提供用户决策选项
               - 事件推进：是否有效推进事件进程

            【智能体信息】
            {json.dumps(agent_parsed_info, ensure_ascii=False, indent=2)}

            【对话内容】
            {json.dumps(conversation_log, ensure_ascii=False, indent=2)}

            【输出格式要求】
            输出格式如下示例：
            【内容相关性】
            评分：80
            理由：对话紧密围绕事件主题，充分利用了事件背景信息，但在第2轮出现了轻微偏题
            
            【角色一致性】
            评分：90
            理由：智能体很好地体现了职业特征，语言风格符合设定性格，行为逻辑合理
            
            【交互有效性】
            评分：75
            理由：在关键节点提供了用户决策选项，但事件推进略显缓慢

            【整体评价】
            - 总结三个维度的核心表现
            - 指出最突出的优势和最需改进的点
            - 结合事件背景给出针对性建议

            注意：评分必须基于对话实际内容，理由需具体到细分规则。
            """

        try:
            # 调用大模型进行评估
            response = self.client.call_api(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500
            )
            content = response["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"❌ 评估大模型调用失败: {str(e)}")
            return {"error": f"评估失败: {str(e)}"}

        # 初始化评估结果字典 - 只使用中文字段
        evaluation = {
            "agent_id": agent_parsed_info.get("agent_id"),
            "agent_name": agent_parsed_info.get("agent_name", "未知"),
            "test_type": test_type,
            "总对话轮次": len(conversation_log) // 2,  # 每两轮为一个完整对话回合
            "内容相关性": 0,
            "内容相关性分数原因": "未提取到相关信息",
            "角色一致性": 0,
            "角色一致性分数原因": "未提取到相关信息",
            "对话自然度" if test_type == "daily" else "交互有效性": 0,
            "对话自然度分数原因" if test_type == "daily" else "交互有效性分数原因": "未提取到相关信息",
            "整体评价": "未提取到整体评价",
            "timestamp": datetime.now().isoformat()
        }

        dim_mapping = {
            "内容相关性": ("内容相关性", "内容相关性分数原因"),
            "角色一致性": ("角色一致性", "角色一致性分数原因"),
            "对话自然度" if test_type == "daily" else "交互有效性": 
                ("对话自然度", "对话自然度分数原因") if test_type == "daily" 
                else ("交互有效性", "交互有效性分数原因")
        }

        # 解析每个维度的评分、理由、例子
        for dim, (score_key, reason_key) in dim_mapping.items():
            if test_type == "daily":
                dim_pattern = re.compile(
                    rf"【{dim}】\s*"
                    r"评分：(\d+)\s*"
                    r"理由：(.*?)\s*"
                    r"例子：(.*?)(?=\s*【|$)",  # 终止条件：下一个维度标签或文本结束
                    re.DOTALL  # 允许.匹配换行符
                )
            else:
                dim_pattern = re.compile(
                    rf"【{dim}】\s*"
                    r"评分：(\d+)\s*"
                    r"理由：(.*?)(?=\s*【|$)",
                    re.DOTALL
                )
            
            match = dim_pattern.search(content)
            if match:
                try:
                    # 提取并转换评分
                    score = int(match.group(1))
                    score = max(0, min(100, score))  # 确保评分在0-100范围内
                    
                    # 提取理由和例子
                    reason = match.group(2).strip()
                    
                    if test_type == "daily":
                        example = match.group(3).strip()
                        evaluation[score_key] = score
                        evaluation[reason_key] = f"{reason}（例子：{example}）"
                    else:
                        evaluation[score_key] = score
                        evaluation[reason_key] = reason
                        
                except (ValueError, IndexError) as e:
                    print(f"⚠️ 解析{dim}时出错: {e}，使用默认值")
            else:
                print(f"⚠️ 未找到{dim}的评估结果，使用默认值")

        # 解析整体评价
        overall_pattern = re.compile(
            r"【整体评价】\s*(.*?)(?=\s*【|$)",  # 匹配到下一个维度或结束
            re.DOTALL
        )
        overall_match = overall_pattern.search(content)
        if overall_match:
            evaluation["整体评价"] = overall_match.group(1).strip()
        else:
            print("⚠️ 未找到整体评价，使用默认值")

        # 计算总分（取三个维度的平均值，四舍五入）
        if test_type == "daily":
            evaluation["总分"] = round(
                (evaluation["内容相关性"] +
                 evaluation["角色一致性"] +
                 evaluation["对话自然度"]) / 3
            )
        else:
            evaluation["总分"] = round(
                (evaluation["内容相关性"] +
                 evaluation["角色一致性"] +
                 evaluation["交互有效性"]) / 3
            )

        # 保存评估结果
        self._save_evaluation(evaluation, test_type)
        return evaluation

    def _save_evaluation(self, evaluation: dict, test_type: str = "daily"):
        """保存评估结果到JSON文件，只保留中文字段"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"evaluation_{evaluation.get('agent_id', 'unknown')}_{test_type}_{timestamp}.json"
        filepath = os.path.join(self.report_dir, filename)

        # 只保留中文字段的评估结果
        if test_type == "daily":
            chinese_evaluation = {
                "agent_id": evaluation.get("agent_id"),
                "agent_name": evaluation.get("agent_name"),
                "test_type": evaluation.get("test_type"),
                "总对话轮次": evaluation.get("总对话轮次", evaluation.get("total_turns")),
                "内容相关性": evaluation.get("内容相关性"),
                "内容相关性分数原因": evaluation.get("内容相关性分数原因"),
                "角色一致性": evaluation.get("角色一致性"),
                "角色一致性分数原因": evaluation.get("角色一致性分数原因"),
                "对话自然度": evaluation.get("对话自然度"),
                "对话自然度分数原因": evaluation.get("对话自然度分数原因"),
                "整体评价": evaluation.get("整体评价", evaluation.get("overall_evaluation")),
                "总分": evaluation.get("总分", evaluation.get("total_score")),
                "timestamp": evaluation.get("timestamp")
            }
        else:
            chinese_evaluation = {
                "agent_id": evaluation.get("agent_id"),
                "agent_name": evaluation.get("agent_name"),
                "test_type": evaluation.get("test_type"),
                "总对话轮次": evaluation.get("总对话轮次", evaluation.get("total_turns")),
                "内容相关性": evaluation.get("内容相关性"),
                "内容相关性分数原因": evaluation.get("内容相关性分数原因"),
                "角色一致性": evaluation.get("角色一致性"),
                "角色一致性分数原因": evaluation.get("角色一致性分数原因"),
                "交互有效性": evaluation.get("交互有效性"),
                "交互有效性分数原因": evaluation.get("交互有效性分数原因"),
                "整体评价": evaluation.get("整体评价", evaluation.get("overall_evaluation")),
                "总分": evaluation.get("总分", evaluation.get("total_score")),
                "timestamp": evaluation.get("timestamp")
            }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(chinese_evaluation, f, ensure_ascii=False, indent=2)
        print(f"💾 评估结果已保存至 {filepath}")

    def list_evaluation_files(self) -> list:
        """列出所有评估结果文件"""
        try:
            files = os.listdir(self.report_dir)
            evaluation_files = [f for f in files if f.startswith("evaluation_") and f.endswith(".json")]
            return evaluation_files
        except Exception as e:
            print(f"❌ 列出评估文件失败: {str(e)}")
            return []

    def load_evaluation(self, filepath: str) -> dict:
        """加载评估结果文件"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ 加载评估结果失败: {str(e)}")
            return None

    def update_evaluation(self, filepath: str, updated_evaluation: dict):
        """更新评估结果文件"""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(updated_evaluation, f, ensure_ascii=False, indent=2)
            print(f"✅ 评估结果已更新: {filepath}")
        except Exception as e:
            print(f"❌ 更新评估结果失败: {str(e)}")

    def interactive_modify_evaluation(self):
        """交互式修改评估结果"""
        evaluation_files = self.list_evaluation_files()
        if not evaluation_files:
            print("⚠️ 没有找到评估结果文件")
            return

        print("\n找到以下评估结果文件:")
        for i, filename in enumerate(evaluation_files, 1):
            print(f"{i}. {filename}")

        try:
            choice = int(input("\n请选择要修改的文件编号 (输入0退出): "))
            if choice == 0:
                return
            if 1 <= choice <= len(evaluation_files):
                filename = evaluation_files[choice - 1]
                filepath = os.path.join(self.report_dir, filename)
                
                # 加载评估结果
                evaluation = self.load_evaluation(filepath)
                if not evaluation:
                    return
                
                print(f"\n当前评估结果:")
                print(f"智能体: {evaluation.get('agent_name', '未知')}")
                print(f"内容相关性: {evaluation.get('内容相关性', 0)}/100")
                print(f"  理由: {evaluation.get('内容相关性分数原因', '')}")
                print(f"角色一致性: {evaluation.get('角色一致性', 0)}/100")
                print(f"  理由: {evaluation.get('角色一致性分数原因', '')}")
                print(f"对话自然度: {evaluation.get('对话自然度', 0)}/100")
                print(f"  理由: {evaluation.get('对话自然度分数原因', '')}")
                print(f"总分: {evaluation.get('总分', 0)}/100")
                print(f"整体评价: {evaluation.get('整体评价', '')}")
                
                # 询问是否修改
                modify = input("\n是否要修改评估结果? (y/n): ").lower()
                if modify != 'y':
                    return
                
                # 修改各项评分和理由
                print("\n请输入新的评分和理由 (直接回车保持原值):")
                
                # 修改内容相关性
                relevance_score = input(f"内容相关性 ({evaluation.get('内容相关性', 0)}): ")
                if relevance_score:
                    try:
                        evaluation['内容相关性'] = int(relevance_score)
                    except ValueError:
                        print("❌ 评分必须是数字，保持原值")
                
                relevance_reason = input(f"内容相关性理由 ({evaluation.get('内容相关性分数原因', '')}): ")
                if relevance_reason:
                    evaluation['内容相关性分数原因'] = relevance_reason
                
                # 修改角色一致性
                consistency_score = input(f"角色一致性 ({evaluation.get('角色一致性', 0)}): ")
                if consistency_score:
                    try:
                        evaluation['角色一致性'] = int(consistency_score)
                    except ValueError:
                        print("❌ 评分必须是数字，保持原值")
                
                consistency_reason = input(f"角色一致性理由 ({evaluation.get('角色一致性分数原因', '')}): ")
                if consistency_reason:
                    evaluation['角色一致性分数原因'] = consistency_reason
                
                # 修改对话自然度
                naturalness_score = input(f"对话自然度 ({evaluation.get('对话自然度', 0)}): ")
                if naturalness_score:
                    try:
                        evaluation['对话自然度'] = int(naturalness_score)
                    except ValueError:
                        print("❌ 评分必须是数字，保持原值")
                
                naturalness_reason = input(f"对话自然度理由 ({evaluation.get('对话自然度分数原因', '')}): ")
                if naturalness_reason:
                    evaluation['对话自然度分数原因'] = naturalness_reason
                
                # 修改整体评价
                overall_evaluation = input(f"整体评价 ({evaluation.get('整体评价', '')}): ")
                if overall_evaluation:
                    evaluation['整体评价'] = overall_evaluation
                
                # 重新计算总分
                evaluation['总分'] = round(
                    (evaluation['内容相关性'] + 
                     evaluation['角色一致性'] + 
                     evaluation['对话自然度']) / 3
                )
                
                # 保存修改后的评估结果
                self.update_evaluation(filepath, evaluation)
                print("✅ 评估结果修改完成")
            else:
                print("❌ 无效的选择")
        except ValueError:
            print("❌ 请输入有效的数字")
        except Exception as e:
            print(f"❌ 修改评估结果时出错: {str(e)}")

    def show_test_summary(self):
        """展示测试结果摘要"""
        if not self.test_log["tests"]:
            print("⚠️ 没有测试记录")
            return

        # 统计不同类型的测试数量
        daily_tests = [t for t in self.test_log["tests"] if t["test_type"] == "daily"]
        event_tests = [t for t in self.test_log["tests"] if t["test_type"] == "event"]

        print(f"📊 测试总览:")
        print(f"  - 开始时间: {self.test_log['start_time']}")
        print(f"  - 总测试数: {len(self.test_log['tests'])}")
        print(f"  - 日常对话测试: {len(daily_tests)} 次")
        print(f"  - 事件交互测试: {len(event_tests)} 次")

        # 展示每个测试的基本信息
        for i, test in enumerate(self.test_log["tests"], 1):
            print(f"\n测试 #{i}:")
            print(f"  类型: {'日常对话' if test['test_type'] == 'daily' else '事件交互'}")
            print(f"  智能体ID: {test['agent_id']}")
            print(f"  对话ID(session_id): {test['session_id'] or '无'}")
            print(f"  时间: {test['timestamp']}")
            print(f"  对话轮次: {len(test['conversation']) // 2} 轮")  # 每两轮为一次交互(用户+智能体)

    def batch_evaluate_interactions(self, test_logs_files=None):
        """
        批量评估交互对话质量
        参数:
            test_logs_files: 测试日志文件路径列表，如果为None则使用默认文件
        """
        # 确定要评估的日志文件
        if test_logs_files is None:
            # 默认评估所有日常交互日志文件
            test_logs_files = []
            try:
                # 获取目录下所有日常交互日志文件
                for file in os.listdir(self.report_dir):
                    if file.startswith("interaction_test_log") and file.endswith(".json"):
                        test_logs_files.append(os.path.join(self.report_dir, file))
            except Exception as e:
                print(f"⚠️ 读取日志文件列表失败: {e}")
                # 回退到默认文件
                test_logs_files = [os.path.join(self.report_dir, "interaction_test_log.json")]
        elif isinstance(test_logs_files, str):
            # 如果是单个文件路径，转换为列表
            test_logs_files = [test_logs_files]
        
        # 收集所有测试记录
        all_tests = []
        for log_file in test_logs_files:
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    test_logs = json.load(f)
                    all_tests.extend(test_logs.get("tests", []))
                    print(f"📁 已加载 {log_file}，包含 {len(test_logs.get('tests', []))} 条测试记录")
            except Exception as e:
                print(f"❌ 读取测试日志失败 {log_file}: {e}")
        
        if not all_tests:
            print("⚠️ 没有找到任何测试记录")
            return

        # 对每个测试进行评估
        evaluations = []
        for test in all_tests:
            if test.get("test_type") == "daily":
                print(f"🔄 正在评估 智能体ID:{test['agent_id']}")
                # 加载智能体信息
                try:
                    with self.db as db_conn:
                        agent_info = db_conn.get_agent_by_id(test["agent_id"])
                    if not agent_info:
                        print(f"⚠️ 无法加载智能体信息 (agent_id: {test['agent_id']})")
                        continue
                    
                    try:
                        full_json = json.loads(agent_info['full_json'])
                        agent_name = full_json.get('姓名', '未知姓名')
                        profession = full_json.get('职业', '未知职业')
                    except json.JSONDecodeError:
                        agent_name = '未知姓名'
                        profession = '未知职业'

                    agent_parsed_info = {
                        'agent_id': test["agent_id"],
                        'agent_name': agent_name,
                        'profession': profession,
                        'full_json': agent_info.get('full_json', '{}')
                    }
                except Exception as e:
                    print(f"⚠️ 加载智能体信息失败: {e}")
                    continue

                # 评估对话
                evaluation = self._evaluate_conversation(
                    test["conversation"], 
                    agent_parsed_info,
                    "daily"
                )
                if evaluation:
                    evaluations.append(evaluation)

        if not evaluations:
            print("⚠️ 没有评估结果生成")
            return

        # 保存批量评估结果
        self._save_batch_evaluation(evaluations)
        
        # 显示评估摘要
        self._display_evaluation_summary(evaluations)
        return evaluations

    def _save_batch_evaluation(self, evaluations: list):
        """保存批量评估结果到JSON文件"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"batch_daily_evaluation_{timestamp}.json"
        filepath = os.path.join(self.report_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(evaluations, f, ensure_ascii=False, indent=2)
        print(f"💾 批量评估结果已保存至 {filepath}")

    def _display_evaluation_summary(self, evaluations: list):
        """显示评估结果摘要"""
        if not evaluations:
            print("⚠️ 没有评估结果可显示")
            return

        print(f"\n{'='*80}")
        print("🎯 日常交互批量评估结果摘要")
        print(f"{'='*80}")
        
        # 按智能体分组
        agent_evaluations = {}
        for eval_result in evaluations:
            agent_id = eval_result.get("agent_id")
            if agent_id not in agent_evaluations:
                agent_evaluations[agent_id] = []
            agent_evaluations[agent_id].append(eval_result)
        
        # 显示每个智能体的评估结果
        for agent_id, agent_evals in agent_evaluations.items():
            agent_name = agent_evals[0].get("agent_name", "未知智能体")
            avg_total_score = sum(e.get("总分", 0) for e in agent_evals) / len(agent_evals)
            
            print(f"\n🤖 智能体: {agent_name} (ID: {agent_id})")
            print(f"   📊 平均总分: {avg_total_score:.1f}/100")
            print(f"   📈 评估测试数: {len(agent_evals)}")
            print("-" * 60)
            
            # 显示该智能体的每次测试评估
            for i, eval_result in enumerate(agent_evals, 1):
                total_score = eval_result.get("总分", 0)
                turns = eval_result.get("总对话轮次", 0)
                
                print(f"  📋 测试 #{i}")
                print(f"     ⭐ 总分: {total_score}/100")
                print(f"     💬 对话轮次: {turns}")
                
                # 显示各维度评分
                relevance = eval_result.get('内容相关性', 0)
                consistency = eval_result.get('角色一致性', 0)
                naturalness = eval_result.get('对话自然度', 0)
                
                print(f"     🎯 内容相关性: {relevance}/100")
                print(f"     🎭 角色一致性: {consistency}/100")
                print(f"     💬 对话自然度: {naturalness}/100")
                
                # 显示简要评价
                overall_eval = eval_result.get("整体评价", "")
                if overall_eval:
                    # 简化显示整体评价
                    lines = overall_eval.split("\n")
                    summary_line = lines[0] if lines else ""
                    if len(summary_line) > 60:
                        summary_line = summary_line[:60] + "..."
                    print(f"     📝 评价摘要: {summary_line}")
            print()

        # 总体统计
        total_evaluations = len(evaluations)
        avg_score = sum(e.get("总分", 0) for e in evaluations) / total_evaluations if total_evaluations > 0 else 0
        max_score = max(e.get("总分", 0) for e in evaluations) if evaluations else 0
        min_score = min(e.get("总分", 0) for e in evaluations) if evaluations else 0
        
        print(f"{'='*80}")
        print("📈 总体统计")
        print(f"   📦 总评估数: {total_evaluations}")
        print(f"   📊 平均分: {avg_score:.1f}/100")
        print(f"   🥇 最高分: {max_score}/100")
        print(f"   🥈 最低分: {min_score}/100")
        print(f"{'='*80}")

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

    def _generate_followup_response(self, conversation_log, agent_info, theme) -> str:
        """由用户模型基于对话历史生成后续回复"""
        # 格式化对话历史（仅保留角色和内容，简化输入）
        formatted_history = "\n".join([
            f"{item['role']}: {item['content']}"
            for item in conversation_log
        ])

        prompt = f"""
        请以用户身份继续与智能体对话，基于以下历史记录和主题生成自然回复：
        智能体信息：{agent_info['name']}（{agent_info['profession']}）
        对话主题：{theme}
        对话历史：
        {formatted_history}

        回复要求：
        1. 符合日常交流逻辑，与历史对话连贯
        2. 不使用长句，口语化表达
        3. 可以提问、分享观点或回应智能体的内容
        4. 避免重复之前说过的话
        """
        try:
            response = self.user_model_client.call_api(
                messages=[{"role": "user", "content": prompt}],  # 消息列表格式
                temperature=0.7,
                max_tokens=200
            )
            # 解析响应（根据API返回格式调整）
            if response and 'choices' in response and response['choices']:
                return response['choices'][0]['message']['content'].strip()
            else:
                return "继续说下去吧，我在听。"
        except Exception as e:
            print(f"⚠️ 生成用户后续回复失败: {str(e)}")
            return "继续说下去吧，我在听。"

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

def batch_evaluate_interactions():
    """批量评估交互记录"""
    tester = InteractionTester()
    tester.batch_evaluate_interactions()

def modify_evaluations():
    """修改评估结果的入口函数"""
    tester = InteractionTester()
    tester.interactive_modify_evaluation()

if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description='日常交互测试工具')
    parser.add_argument('--batch_evaluate', action='store_true', help='批量评估交互记录')
    parser.add_argument('--log_files', nargs='+', help='指定要评估的日志文件路径（多个文件用空格分隔）')
    parser.add_argument('action', nargs='?', default='run_tests', 
                       choices=['run_tests', 'batch_evaluate', 'modify'], 
                       help='要执行的操作')
    
    args = parser.parse_args()

    if args.action == "batch_evaluate" or args.batch_evaluate:
        # 执行批量评估
        tester = InteractionTester()
        tester.batch_evaluate_interactions(args.log_files)
    elif args.action == "modify":
        modify_evaluations()
    else:
        run_tests()
