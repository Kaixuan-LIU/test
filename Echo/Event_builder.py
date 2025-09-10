import os
import json
import re
import time
from typing import List, Dict
from api_handler import ChatFireAPIClient
from database import MySQLDB


class EventTreeGenerator:
    def __init__(self, agent_name: str, api_key: str, agent_id: int , user_id: int,agent_builder: 'AgentBuilder'):
        self.agent_name = agent_name
        self.api_client = ChatFireAPIClient(api_key=api_key)
        self.agent_id = agent_id
        self.user_id = user_id
        self.agent_builder = agent_builder
        # 智能体ID
        self.db = MySQLDB(
            host="101.200.229.113",
            user="gongwei",
            password="Echo@123456",
            database="echo",
            port=3306,
            charset="utf8mb4"
        )
        self.base_info = self._load_base_info_from_db()
        self.life_events = self._load_life_events_from_db()
        self.goals = self._load_goals_from_db()
        self.full_event_tree = []

    def _load_base_info_from_db(self) -> dict:
        """调用get_agent方法读取智能体基础信息"""
        try:
            with self.db as db:
                # 调用MySQLDB中已定义的get_agent方法
                agent_data = db.get_agent(self.agent_id)
                if agent_data and len(agent_data) > 0:
                    full_json = agent_data[0].get("full_json", "{}")
                    base_info = json.loads(full_json)
                    base_info["agent_id"] = agent_data[0]["agent_id"]
                    base_info["user_id"] = agent_data[0]["user_id"]
                    return base_info
                else:
                    print(f"❌ 未查询到agent_id={self.agent_id}的基础信息")
                    return {}
        except json.JSONDecodeError as e:
            print(f"❌ 解析智能体基础信息JSON失败：{e}")
            return {}
        except Exception as e:
            print(f"❌ 加载智能体基础信息异常：{e}")
            return {}

    def _load_life_events_from_db(self) -> dict:
        """调用get_agent_life_events方法读取生平事件"""
        try:
            with self.db as db:
                # 调用数据库方法获取事件列表（List[Dict]）
                events_data = db.get_agent_life_events(self.agent_id)

            # 直接返回包含事件数据的字典（键为固定字符串，值为事件列表）
            return {"events": events_data}
        except Exception as e:
            print(f"❌ 加载生平事件异常：{e}")
            return {"events": []}

    def _load_goals_from_db(self) -> dict:
        """调用get_agent_goals方法读取目标信息"""
        try:
            with self.db as db:
                # 调用数据库方法获取目标列表（List[Dict]）
                goals_data = db.get_agent_goals(self.agent_id)

            # 直接返回包含目标数据的字典（键为固定字符串，值为目标列表）
            return {"goals": goals_data}
        except Exception as e:
            print(f"❌ 加载目标信息异常：{e}")
            return {"goals": []}
    def generate_lifecycle_stages(self):
        prompt = self.build_stage_prompt()

        try:
            response = self.api_client.call_api([{"role": "user", "content": prompt}])
            content = response['choices'][0]['message'].get('content', '')

            # 提取 JSON 内容
            start_index = content.find("[")
            end_index = content.rfind("]")
            if start_index != -1 and end_index != -1 and end_index > start_index:
                json_content = content[start_index:end_index + 1].strip()
                stages = json.loads(json_content)

                # 确保结构正确
                if not isinstance(stages, list):
                    print("❌ 生成的生命周期阶段数据结构不正确，期望为列表")
                    return []

                for stage in stages:
                    if not isinstance(stage, dict) or "阶段" not in stage or "时间范围" not in stage:
                        print("❌ 生命周期阶段数据结构不完整")
                        return []

                return stages
            else:
                print("❌ 未找到有效的 JSON 数组结构")
                return []
        except Exception as e:
            print(f"❌ 生成生命周期阶段失败：{e}")
            return []

    def build_stage_prompt(self):
        return f"""
你是一个流程规划设计专家，请基于以下角色信息，为其完整生命周期（现在到60岁之间）的人生划分多个连续阶段，每个阶段包含：阶段名、年龄范围、阶段目标与挑战。

角色信息：
{self.base_info}
{self.life_events}
{self.goals}

请以json格式输出，输出格式如下：
{{{{
  {{
    "阶段编号": "1":,
    "阶段": "小学四年级",
    "时间范围": "2015年-2018年（18岁-21岁）",
    "阶段目标": "...",
    "是否为起点阶段": "true"
  }},
  ...}}}}
"""

    def build_prompt(self, stage):
        return f"""
你是一位沉浸式互动剧情设计专家，用户将与智能体“{self.agent_name}”共同经历一段连贯真实、充满冲突与成长的连续事件链体验。

你的目标是：为每个人生阶段生成具备“情节冲突 + 用户决策影响 + 多轮互动”的3个【主线事件】与5个【支线事件】，以及角色在非剧情高峰期的8个【日常事件】，以支撑剧情节奏。

角色信息：
{self.base_info}

阶段信息：
{stage}

长期目标与背景：
{self.goals}

1. 事件中应包含一个初始事件，引入智能体与用户的初次相识。
2. 主线应构建关键冲突，如目标受阻、价值冲突、人际误解等，设计明确的用户影响路径。
3. 支线应具备探索性，例如“是否追查真相”“是否帮助朋友”“是否道歉”，体现个性发展。
4. 日常事件为低张力休闲互动，强调关系积累（如散步、游戏、学习等），可复用不同模板变体。
5. 所有事件必须完整描述 cause、process、result，并体现 impact（心理变化、知识增长、亲密度波动）。

---

🎭【事件结构示例】
请严格按照以下JSON格式输出，不要包含任何额外文本：
{{
    "阶段": "{stage['阶段']}",
    "时间范围": "{stage['时间范围']}",
    "事件列表": [
        {{
            "event_id": "E001",
            "type": "主线/支线/日常",
            "name": "事件标题",
            "time": "具体时间",
            "location": "具体地点",
            "characters": ["{self.agent_name}", "用户", "配角"],
            "cause": "事件起因...",
            "process": "事件经过（有挑战、有互动）...",
            "result": "事件结果...",
            "impact": {{
                "心理状态变化": "...",
                "知识增长": "...",
                "亲密度变化": "+3"
            }},
            "importance": 1~5,
            "urgency": 1~5,
            "tags": ["关键词1", "关键词2"],
            "trigger_conditions": ["处于{stage['阶段']}", "亲密度>30", "关键词：xx"],
            "dependencies": ["E001"]
        }}
        // 其他事件...
    ]
}}

请注意：
- 必须为每个阶段都生成事件
- 事件的event_id需从E001开始全局连续递增，跨阶段不重新从E001开始，所有事件（无论属于哪个阶段）的编号必须唯一且依次递增（例如上一阶段最后一个事件为E015，下一阶段第一个事件为E016，以此类推）。
- 主线事件 importance ≥ 4，必须带有依赖（dependencies）。
- 支线事件 importance 为 3~4，无需依赖但应有明确触发条件。
- 日常事件 importance ≤ 2，trigger_conditions 可留空。
- 日常事件可以重复发生。
- 初识事件应合理设置在角色某一人生阶段中，主线/支线/日常事件与初始之间应保持逻辑关系。
- 每个阶段中事件数量应适当控制，数量可以不一致，但应保持连续性，尽量要覆盖完整的生命周期。
- 所有事件应具有可玩性（用户决策影响角色表现）、连续性（前后衔接）、真实感（基于性格设定）。

请以 JSON 形式输出所有事件列表。
"""

    def _extract_json(self, content: str) -> dict:
        """更健壮的JSON提取方法"""
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

            # 尝试处理代码块
            if '```json' in content:
                json_str = content.split('```json')[1].split('```')[0].strip()
                return json.loads(json_str)
            elif '```' in content:
                json_str = content.split('```')[1].split('```')[0].strip()
                return json.loads(json_str)

        except json.JSONDecodeError as e:
            print(f"JSON解析失败: {e}")

        # 最终尝试修复常见错误
        try:
            # 修复常见的格式错误
            fixed_content = re.sub(r',\s*]', ']', content)  # 修复多余的逗号
            fixed_content = re.sub(r',\s*}', '}', fixed_content)
            fixed_content = re.sub(r'[\u0000-\u001F]', '', fixed_content)  # 移除控制字符
            return json.loads(fixed_content)
        except:
            return {}

        return {}

    def generate_events_for_stage(self, stage):
        prompt = self.build_prompt(stage)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.api_client.call_api([{"role": "user", "content": prompt}])
                content = response['choices'][0]['message']['content']
                events = self._extract_json(content)

                if events and isinstance(events, dict) and '事件列表' in events:
                    stage_event_list = events['事件列表']  # 阶段下的所有事件（主线/支线/日常）
                    for idx, event in enumerate(stage_event_list):
                        # 设置默认状态
                        if "status" not in event:
                            event["status"] = "未完成"

                        # 生成全局唯一的issue_id（使用原event_id生成逻辑）
                        single_event_json = json.dumps(event, ensure_ascii=False)
                        issue_id = self.agent_builder._generate_global_event_id(
                            user_id=self.user_id,
                            agent_id=self.agent_id,
                            event_json=single_event_json
                        )
                        if issue_id:
                            stage_event_list[idx]['issue_id'] = issue_id
                            print(f"✅ 事件添加issue_id成功: {issue_id} - {event.get('name')}")
                        else:
                            print(f"⚠️ 事件无issue_id: {event.get('name')}")

                        # 验证并保留提示词生成的event_id（E001格式）
                        event_id = event.get("event_id")
                        if event_id:
                            # 保留原始event_id，不进行覆盖
                            stage_event_list[idx]['event_id'] = event_id
                            print(f"✅ 保留提示词生成的event_id：{event_id} - {event.get('name')}")
                        else:
                            print(f"⚠️ 事件缺少提示词生成的event_id（E001格式）: {event.get('name')}")

                # 验证数据结构（确保含event_id和有效事件列表）
                if events and isinstance(events, dict) and '事件列表' in events and len(events['事件列表']) > 0:
                    # 过滤掉没有event_id的无效事件
                    events['事件列表'] = [e for e in events['事件列表'] if e.get('event_id')]
                    return events
                print(f"⚠️ 尝试 {attempt + 1}/{max_retries}: 生成的事件链结构无效（无事件或无有效event_id）")
            except Exception as e:
                print(f"⚠️ 尝试 {attempt + 1}/{max_retries} 失败: {e}")
                time.sleep(1)
        print("❌ 所有重试失败，返回空事件结构")
        return {}

    def build_full_event_tree(self):
        stages = self.generate_lifecycle_stages()

        full_tree = []

        for stage in stages:
            print(f"🔍 正在生成事件阶段：{stage.get('阶段', '未知阶段')} ...")
            stage_events = self.generate_events_for_stage(stage)
            full_tree.append(stage_events)

        print(f"✅ 事件链构建完成，共处理 {len(full_tree)} 个阶段")
        self.full_event_tree = full_tree
        print("🔍 开始执行数据库存储操作...")
        return full_tree

    def save_event_tree(self, filename: str = "full_event_tree.json"):
        try:
            event_chain_data = {
                "version": "1.0",
                "event_tree": self.full_event_tree  # 已含event_id的事件链
            }
            chain_json = json.dumps(event_chain_data, ensure_ascii=False, indent=2)
            with self.db as db_conn:
                chain_id = db_conn.insert_agent_event_chain(
                    user_id=self.user_id,
                    agent_id=self.agent_id,
                    chain_json=chain_json
                )
                if chain_id:
                    print(f"✅ 含全局ID的事件链已存入数据库（chain_id: {chain_id}）")
                else:
                    print(f"❌ 事件链存入数据库失败")
        except Exception as e:
            print(f"❌ 事件链数据库操作异常：{e}")

    def generate_and_save(self):
        full_tree = self.build_full_event_tree()
        self.save_event_tree()
        return full_tree

if __name__ == "__main__":
    generator = EventTreeGenerator(
        agent_name="萧炎",
        api_key="sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV",
        user_id="1",
        agent_id="37"
    )
    # generator.generate_lifecycle_stages()
    generator.generate_and_save()
