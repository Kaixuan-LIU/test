import os
os.environ["APP_ENV"] = "testing"  # 设置为测试环境
import json
import random
import re
import argparse
from datetime import datetime
from typing import List, Dict
from app_config import config
from database import TEST_DB_CONFIG, MySQLDB, DB_CONFIG
from api_handler import ChatFireAPIClient
from event_loop_tool import run_event_loop


class EventInteractionTester:
    def __init__(self, api_key: str = None, init_test_db: bool = False, use_test_db: bool = True):
        """
        初始化事件交互测试工具
        参数:
            init_test_db: 是否初始化测试数据库（默认不初始化，避免删除数据）
            use_test_db: 是否使用测试数据库（默认True），设为False则使用生产数据库
        """
        self.api_key = api_key or config.API_KEY
        self.client = ChatFireAPIClient(api_key=self.api_key)
        # 根据use_test_db参数决定使用测试数据库还是生产数据库
        db_config = TEST_DB_CONFIG if use_test_db else DB_CONFIG
        print(f"🔧 数据库配置: {db_config}")
        self.db = MySQLDB(**db_config)
        self.test_log = {
            "start_time": datetime.now().isoformat(),
            "tests": []
        }
        self.report_dir = "test_reports"
        if not os.path.exists(self.report_dir):
            os.makedirs(self.report_dir)
            print(f"✅ 创建测试报告文件夹: {self.report_dir}")

    def _log_test(self, test_type: str, agent_id: int, event_id: str = None,
                  session_id: str = None, conversation: list = None):
        """记录测试日志"""
        test_entry = {
            "timestamp": datetime.now().isoformat(),
            "test_type": test_type,
            "agent_id": agent_id,
            "event_id": event_id,
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
            filename = f"event_interaction_test_log_{timestamp}.json"
        
        filepath = os.path.join(self.report_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.test_log, f, ensure_ascii=False, indent=2)
        print(f"💾 测试日志已保存至 {filepath}")

    def _safe_json_loads(self, json_str: str, field_name: str = "unknown") -> dict:
        """安全的JSON解析函数"""
        try:
            # 尝试直接解析
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"⚠️ {field_name} JSON解析失败: {e}")
            # 尝试修复常见的JSON问题
            try:
                # 移除可能的BOM标记
                json_str = json_str.lstrip('\ufeff')
                # 尝试修复尾部问题
                json_str = json_str.strip()
                # 查找第一个{和最后一个}
                start = json_str.find('{')
                end = json_str.rfind('}')
                if start != -1 and end != -1 and end > start:
                    json_str = json_str[start:end+1]
                    return json.loads(json_str)
            except Exception as fix_e:
                print(f"❌ {field_name} JSON修复失败: {fix_e}")
        return {}

    def _load_agent_info(self, agent_id: int) -> dict:
        """从数据库加载智能体信息"""
        try:
            print(f"🔍 正在加载智能体信息 (agent_id: {agent_id})")
            with self.db as db:
                agent_data = db.get_agent_by_id(agent_id)  # 这里返回的是单条记录的字典

                if agent_data:  # 直接判断字典是否存在（非空）
                    print(f"📦 原始数据: {agent_data}")
                    # 检查必要的字段是否存在
                    required_fields = ['full_json', 'agent_id', 'agent_name']
                    for field in required_fields:
                        if field not in agent_data:  # 直接从字典中检查字段
                            raise KeyError(f"缺少必要字段: {field}")

                    # 安全解析full_json
                    full_json_str = agent_data['full_json']
                    print(f"📄 full_json长度: {len(full_json_str)} 字符")

                    agent_info = self._safe_json_loads(full_json_str, "full_json")
                    if not agent_info:
                        print("❌ full_json 解析失败，使用空字典")
                        agent_info = {}

                    # 直接从字典中获取字段
                    agent_info['agent_id'] = agent_data['agent_id']
                    agent_info['agent_name'] = agent_data['agent_name']
                    print(f"✅ 成功加载智能体信息: {agent_info.get('agent_name', '未知')}")
                    return agent_info
                else:
                    print(f"❌ 数据库中未找到智能体 (agent_id: {agent_id})")
        except KeyError as e:
            print(f"❌ 缺少必要字段: {e}")
        except Exception as e:
            print(f"❌ 加载智能体信息失败: {e}")
            import traceback
            traceback.print_exc()
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

    def _display_event_info(self, event: dict):
        """显示事件的完整背景信息"""
        print(f"\n{'='*50}")
        print("事件背景信息")
        print(f"{'='*50}")
        print(f"事件标题: {event.get('name', '未知')}")
        print(f"事件类型: {event.get('type', '一般事件')}")
        print(f"发生时间: {event.get('time', '未知时间')}")
        print(f"发生地点: {event.get('location', '未知地点')}")
        print(f"参与角色: {', '.join(event.get('characters', ['未知']))}")
        print(f"事件起因: {event.get('cause', '未知')}")
        print(f"重要程度: {event.get('importance', 0)}/5")
        print(f"紧急程度: {event.get('urgency', 0)}/5")
        print(f"{'='*50}\n")

    def test_single_event_interaction(self, agent_id: int, event_id: str, num_turns: int = 3):
        """
        测试单个事件交互
        参数:
            agent_id: 智能体ID
            event_id: 事件ID
            num_turns: 对话轮次
        """
        print(f"\n{'=' * 50}")
        print(f"开始测试事件交互 (agent_id: {agent_id}, event_id: {event_id})")
        print(f"{'=' * 50}")

        # 加载智能体信息
        print(f"📥 尝试加载智能体信息...")
        agent_info = self._load_agent_info(agent_id)
        if not agent_info:
            print(f"❌ 无法加载智能体信息 (agent_id: {agent_id})")
            return
        
        print(f"📄 智能体信息加载成功: {agent_info.get('agent_name', '未知')}")

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

        # 显示事件背景信息
        self._display_event_info(target_event)

        # 执行事件交互测试
        conversation_log = []
        session_id = None

        # 生成第一轮用户输入
        user_input = self._generate_initial_user_input(agent_info, target_event)

        for i in range(num_turns):
            print(f"第 {i+1} 轮对话:")
            print(f"用户输入: {user_input}")

            # 记录用户输入
            conversation_log.append({
                "role": "user",
                "content": user_input,
                "turn": i,
                "timestamp": datetime.now().isoformat()
            })

            # 执行事件交互
            response = run_event_loop(
                user_id=0,  # 测试用户ID
                agent_id=agent_id,
                event_id=event_id,
                user_input=user_input,
                session_id=session_id
            )

            # 更新session_id
            if response and "session_id" in response:
                session_id = response["session_id"]

            # 记录智能体回复
            if response and "content" in response:
                conversation_log.append({
                    "role": "assistant",
                    "content": response["content"],
                    "turn": i,
                    "timestamp": datetime.now().isoformat()
                })
                print(f"智能体回复: {response['content']}")
            
            # 生成下一轮用户输入
            if i < num_turns - 1:  # 不是最后一轮
                user_input = self._generate_followup_user_input(conversation_log, agent_info, target_event)
            print()

        # 记录本次测试
        self._log_test("event", agent_id, event_id, session_id, conversation_log)

        # 不再进行评估，只保存对话记录
        print(f"\n{'=' * 50}")
        print("事件交互测试完成")
        print(f"{'=' * 50}")

    def _generate_initial_user_input(self, agent_info: dict, event: dict) -> str:
        """生成初始用户输入"""
        event_name = event.get("name", "当前事件")
        event_type = event.get("type", "一般事件")
        event_description = event.get("description", "")
        
        prompt = f"""
        你是一个正在与AI角色进行对话的用户。根据以下信息生成一句自然的开场白：

        AI角色信息：
        姓名：{agent_info.get('agent_name', '未知')}
        职业：{agent_info.get('职业', '未知职业')}
        性格：{agent_info.get('性格', '未知性格')}

        事件背景：
        事件名称：{event_name}
        事件类型：{event_type}
        事件描述：{event_description}

        要求：
        1. 开场白要自然、符合日常对话习惯
        2. 要与事件背景相关
        3. 根据AI角色的职业和性格特点来设计对话内容
        4. 长度适中，1-2句话即可
        5. 不要使用任何格式符号或特殊字符

        请直接输出开场白内容，不要添加其他说明。
        """

        try:
            response = self.client.call_api(
                [{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=100
            )
            if response and 'choices' in response:
                return response['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"⚠️ 生成初始用户输入失败: {e}")

        # 备用方案
        if event_type == "主线事件":
            return f"关于{event_name}，我想听听你的看法"
        elif event_type == "支线事件":
            return f"我发现{event_name}有些问题"
        else:
            return "今天过得怎么样？"

    def _generate_followup_user_input(self, conversation_log: list, agent_info: dict, event: dict) -> str:
        """基于对话历史生成后续用户输入"""
        if not conversation_log:
            return "继续说说吧"

        # 构建对话历史
        history = "\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in conversation_log[-4:]  # 只取最近4条消息
        ])

        event_name = event.get("name", "当前事件")
        event_type = event.get("type", "一般事件")

        prompt = f"""
        你是一个正在与AI角色进行对话的用户。根据以下信息生成一句自然的回复：

        AI角色信息：
        姓名：{agent_info.get('agent_name', '未知')}
        职业：{agent_info.get('职业', '未知职业')}

        事件背景：
        事件名称：{event_name}
        事件类型：{event_type}

        对话历史：
        {history}

        要求：
        1. 回复要自然、符合日常对话习惯
        2. 要与事件背景和对话历史相关
        3. 可以是对AI回复的回应、追问或引导话题
        4. 长度适中，1-2句话即可
        5. 不要使用任何格式符号或特殊字符

        请直接输出回复内容，不要添加其他说明。
        """

        try:
            response = self.client.call_api(
                [{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=100
            )
            if response and 'choices' in response:
                return response['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"⚠️ 生成后续用户输入失败: {e}")

        # 备用方案
        fallback_inputs = [
            "能详细说说吗？",
            "这听起来很有意思",
            "然后呢？",
            "我明白了，谢谢",
            "还有其他需要考虑的吗？"
        ]
        return random.choice(fallback_inputs)

    def batch_evaluate_interactions(self, test_logs_files=None):
        """
        批量评估交互对话质量
        参数:
            test_logs_files: 测试日志文件路径列表，如果为None则使用默认文件
        """
        # 确定要评估的日志文件
        if test_logs_files is None:
            # 默认评估所有事件交互日志文件
            test_logs_files = []
            try:
                # 获取目录下所有事件交互日志文件
                for file in os.listdir(self.report_dir):
                    if file.startswith("event_interaction_test_log") and file.endswith(".json"):
                        test_logs_files.append(os.path.join(self.report_dir, file))
            except Exception as e:
                print(f"⚠️ 读取日志文件列表失败: {e}")
                # 回退到默认文件
                test_logs_files = [os.path.join(self.report_dir, "event_interaction_test_log.json")]
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
            if test.get("test_type") == "event":
                print(f"🔄 正在评估 智能体ID:{test['agent_id']} 事件ID:{test['event_id']}")
                # 加载智能体信息
                agent_info = self._load_agent_info(test["agent_id"])
                if not agent_info:
                    print(f"⚠️ 无法加载智能体信息 (agent_id: {test['agent_id']})")
                    continue

                # 加载事件链
                event_chain = self._load_event_chain(test["agent_id"])
                if not event_chain:
                    print(f"⚠️ 无法加载事件链 (agent_id: {test['agent_id']})")
                    continue

                # 查找目标事件
                target_event = self._find_event(event_chain, test["event_id"])
                if not target_event:
                    print(f"⚠️ 未找到事件ID: {test['event_id']}")
                    continue

                # 评估对话
                evaluation = self._evaluate_conversation(
                    test["conversation"], 
                    agent_info, 
                    target_event
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

    def _evaluate_conversation(self, conversation_log: list, agent_info: dict, event: dict):
        """
        评估事件交互对话质量
        """
        if not conversation_log:
            return {"error": "无对话内容可评估"}

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
        {json.dumps(agent_info, ensure_ascii=False, indent=2)}

        【事件背景】
        {json.dumps(event, ensure_ascii=False, indent=2)}

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

        # 初始化评估结果字典
        evaluation = {
            "agent_id": agent_info.get("agent_id"),
            "agent_name": agent_info.get("agent_name", "未知"),
            "event_id": event.get("event_id", "未知"),
            "event_name": event.get("name", "未知事件"),
            "test_type": "event",
            "总对话轮次": len(conversation_log) // 2,
            "内容相关性": 0,
            "内容相关性分数原因": "未提取到相关信息",
            "角色一致性": 0,
            "角色一致性分数原因": "未提取到相关信息",
            "交互有效性": 0,
            "交互有效性分数原因": "未提取到相关信息",
            "整体评价": "未提取到整体评价",
            "timestamp": datetime.now().isoformat()
        }

        dim_mapping = {
            "内容相关性": ("内容相关性", "内容相关性分数原因"),
            "角色一致性": ("角色一致性", "角色一致性分数原因"),
            "交互有效性": ("交互有效性", "交互有效性分数原因")
        }

        # 解析每个维度的评分、理由
        for dim, (score_key, reason_key) in dim_mapping.items():
            dim_pattern = re.compile(
                rf"【{dim}】\s*"
                r"评分：(\d+)\s*"
                r"理由：(.*?)(?=\s*【|$)",
                re.DOTALL
            )
            match = dim_pattern.search(content)
            if match:
                try:
                    score = int(match.group(1))
                    score = max(0, min(100, score))
                    reason = match.group(2).strip()
                    evaluation[score_key] = score
                    evaluation[reason_key] = reason
                except (ValueError, IndexError) as e:
                    print(f"⚠️ 解析{dim}时出错: {e}，使用默认值")
            else:
                print(f"⚠️ 未找到{dim}的评估结果，使用默认值")

        # 解析整体评价
        overall_pattern = re.compile(
            r"【整体评价】\s*(.*?)(?=\s*【|$)",
            re.DOTALL
        )
        overall_match = overall_pattern.search(content)
        if overall_match:
            evaluation["整体评价"] = overall_match.group(1).strip()
        else:
            print("⚠️ 未找到整体评价，使用默认值")

        # 计算总分
        evaluation["总分"] = round(
            (evaluation["内容相关性"] +
             evaluation["角色一致性"] +
             evaluation["交互有效性"]) / 3
        )

        # 保存评估结果
        self._save_evaluation(evaluation)
        return evaluation

    def _save_batch_evaluation(self, evaluations: list):
        """保存批量评估结果到JSON文件"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"batch_event_evaluation_{timestamp}.json"
        filepath = os.path.join(self.report_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(evaluations, f, ensure_ascii=False, indent=2)
        print(f"💾 批量评估结果已保存至 {filepath}")

    def _save_evaluation(self, evaluation: dict):
        """保存评估结果到JSON文件"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"event_evaluation_{evaluation.get('agent_id', 'unknown')}_{evaluation.get('event_id', 'unknown')}_{timestamp}.json"
        filepath = os.path.join(self.report_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(evaluation, f, ensure_ascii=False, indent=2)
        print(f"💾 评估结果已保存至 {filepath}")

    def _display_evaluation_summary(self, evaluations: list):
        """显示评估结果摘要"""
        if not evaluations:
            print("⚠️ 没有评估结果可显示")
            return

        print(f"\n{'='*80}")
        print("🎯 事件交互批量评估结果摘要")
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
            print(f"   📈 评估事件数: {len(agent_evals)}")
            print("-" * 60)
            
            # 显示该智能体的每个事件评估
            for eval_result in agent_evals:
                event_name = eval_result.get("event_name", "未知事件")
                event_id = eval_result.get("event_id", "未知ID")
                total_score = eval_result.get("总分", 0)
                turns = eval_result.get("总对话轮次", 0)
                
                print(f"  📋 事件: {event_name} ({event_id})")
                print(f"     ⭐ 总分: {total_score}/100")
                print(f"     💬 对话轮次: {turns}")
                
                # 显示各维度评分
                relevance = eval_result.get('内容相关性', 0)
                consistency = eval_result.get('角色一致性', 0)
                effectiveness = eval_result.get('交互有效性', 0)
                
                print(f"     🎯 内容相关性: {relevance}/100")
                print(f"     🎭 角色一致性: {consistency}/100")
                print(f"     🔗 交互有效性: {effectiveness}/100")
                
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

    def list_agent_events(self, agent_id: int):
        """列出指定智能体的所有事件"""
        print(f"\n智能体 {agent_id} 的事件列表:")

        # 加载事件链
        event_chain = self._load_event_chain(agent_id)
        if not event_chain:
            print(f"❌ 无法加载事件链 (agent_id: {agent_id})")
            return

        # 遍历所有阶段和事件
        event_count = 0
        for stage in event_chain:
            if isinstance(stage, dict) and "事件列表" in stage:
                print(f"\n阶段: {stage.get('阶段', '未知阶段')}")
                for event in stage["事件列表"]:
                    if isinstance(event, dict):
                        event_count += 1
                        print(f"  {event_count}. {event.get('event_id', '未知ID')}: {event.get('name', '未知事件')} ({event.get('type', '一般事件')})")

    def test_agent_all_events(self, agent_id: int, num_turns: int = 3):
        """测试智能体的所有事件"""
        print(f"\n测试智能体 {agent_id} 的所有事件:")

        # 加载事件链
        event_chain = self._load_event_chain(agent_id)
        if not event_chain:
            print(f"❌ 无法加载事件链 (agent_id: {agent_id})")
            return

        # 遍历所有阶段和事件进行测试
        for stage in event_chain:
            if isinstance(stage, dict) and "事件列表" in stage:
                for event in stage["事件列表"]:
                    if isinstance(event, dict):
                        event_id = event.get("event_id")
                        if event_id:
                            self.test_single_event_interaction(agent_id, event_id, num_turns)

    def show_test_summary(self):
        """展示测试结果摘要"""
        if not self.test_log["tests"]:
            print("⚠️ 没有测试记录")
            return

        # 统计测试数量
        event_tests = [t for t in self.test_log["tests"] if t["test_type"] == "event"]

        print(f"📊 事件交互测试总览:")
        print(f"  - 开始时间: {self.test_log['start_time']}")
        print(f"  - 事件交互测试: {len(event_tests)} 次")

        # 展示每个测试的基本信息
        for i, test in enumerate(self.test_log["tests"], 1):
            print(f"\n测试 #{i}:")
            print(f"  类型: 事件交互")
            print(f"  智能体ID: {test['agent_id']}")
            print(f"  事件ID: {test['event_id']}")
            print(f"  对话ID(session_id): {test['session_id'] or '无'}")
            print(f"  时间: {test['timestamp']}")
            print(f"  对话轮次: {len(test['conversation']) // 2} 轮")


def run_event_tests(agent_id=None, event_id=None, use_test_db=False):
    """运行事件交互测试"""
    tester = EventInteractionTester(use_test_db=use_test_db)

    if agent_id and event_id:
        # 如果提供了agent_id和event_id，则测试指定的事件
        print(f"\n>>> 测试智能体 {agent_id} 的事件交互")
        tester.test_single_event_interaction(agent_id=agent_id, event_id=event_id)
    elif agent_id:
        # 如果只提供了agent_id，则测试该智能体的所有事件
        print(f"\n>>> 测试智能体 {agent_id} 的所有事件")
        tester.test_agent_all_events(agent_id=agent_id)
    else:
        # 运行默认测试
        print("\n>>> 测试医生智能体的事件交互")
        tester.test_single_event_interaction(agent_id=1, event_id="E001")

        print("\n>>> 测试律师智能体的事件交互")
        tester.test_single_event_interaction(agent_id=3, event_id="E101")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='事件交互测试工具')
    parser.add_argument('--agent_id', type=int, help='智能体ID')
    parser.add_argument('--event_id', type=str, help='事件ID')
    parser.add_argument('--list_events', type=int, help='列出指定智能体的所有事件')
    parser.add_argument('--use_test_db', action='store_true', help='使用测试数据库', default=True)
    parser.add_argument('--batch_evaluate', action='store_true', help='批量评估交互记录')
    parser.add_argument('--log_files', nargs='+', help='指定要评估的日志文件路径（多个文件用空格分隔）')
    
    args = parser.parse_args()
    print(f"🔧 命令行参数: {args}")

    if args.list_events:
        tester = EventInteractionTester(use_test_db=args.use_test_db)
        tester.list_agent_events(args.list_events)
    elif args.batch_evaluate:
        # 执行批量评估
        tester = EventInteractionTester(use_test_db=args.use_test_db)
        tester.batch_evaluate_interactions(args.log_files)
    elif args.agent_id and args.event_id:
        # 如果提供了agent_id和event_id，则测试指定的事件
        print(f"🚀 运行指定测试: agent_id={args.agent_id}, event_id={args.event_id}")
        run_event_tests(args.agent_id, args.event_id, args.use_test_db)
    elif args.agent_id:
        # 如果只提供了agent_id，则测试该智能体的所有事件
        print(f"🚀 运行智能体所有事件测试: agent_id={args.agent_id}")
        run_event_tests(args.agent_id, None, args.use_test_db)
    else:
        # 运行默认测试
        print("🚀 运行默认测试")
        run_event_tests(use_test_db=args.use_test_db)