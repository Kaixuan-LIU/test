import os
import json
import re
import time
from typing import List, Dict
from app_config import config
from api_handler import ChatFireAPIClient
from database import MySQLDB


class EventTreeGenerator:
    def __init__(self, agent_name: str, api_key: str, agent_id: int , user_id: int, agent_builder: 'AgentBuilder'):
        # 保留原有初始化逻辑
        self.agent_name = agent_name
        self.api_client = ChatFireAPIClient(api_key=api_key)
        self.agent_id = agent_id
        self.user_id = user_id
        self.agent_builder = agent_builder
        self.db = MySQLDB(** config.DB_CONFIG)
        self.base_info = self._load_base_info_from_db()
        self.life_events = self._load_life_events_from_db()
        self.goals = self._load_goals_from_db()
        self.full_event_tree = []
        # 新增分阶段生成相关属性
        self.current_stage_index = 0  # 当前生成的阶段索引
        self.last_event_id = "E000"  # 最后一个事件ID，用于生成新ID
        self.stages = []  # 生命周期阶段列表
        self.is_final_stage = False

    def generate_initial_event(self) -> dict:
        """生成初始事件(E001)"""
        prompt = self.build_initial_event_prompt(self._get_initial_stage())
        try:
            response = self.api_client.call_api([{"role": "user", "content": prompt}])
            content = response['choices'][0]['message'].get('content', '')
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1:
                event_data = json.loads(content[start:end + 1])
                self.full_event_tree.append(event_data)
                self.last_event_id = "E001"
                self._save_event_tree()
                return event_data
        except Exception as e:
            print(f"❌ 生成初始事件失败：{e}")
            return {}

    def generate_next_stage_events(self):
        """生成下一阶段的事件"""
        # 获取生命周期阶段
        if not self.stages:
            self.stages = self.generate_lifecycle_stages()
            
        if not self.stages:
            print("❌ 无法获取生命周期阶段")
            return []
            
        # 确定当前阶段索引
        current_stage_index = len(self.full_event_tree)
        
        # 检查是否已完成所有阶段
        if current_stage_index >= len(self.stages):
            print("✅ 所有阶段事件已生成完毕")
            return []
            
        # 检查是否接近结局（第9-12阶段）
        if 8 <= current_stage_index <= 11:  # 0-based索引，对应第9-12阶段
            self.is_final_stage = True
            print("🏁 检测到接近结局阶段，将引导故事走向大结局")
            
        # 获取当前阶段
        current_stage = self.stages[current_stage_index]
        print(f"🔍 正在生成第 {current_stage_index + 1} 阶段事件：{current_stage.get('阶段', '未知阶段')}")
        
        # 获取前序事件用于参考
        previous_events = []
        for stage in self.full_event_tree:
            if '事件列表' in stage:
                previous_events.extend(stage['事件列表'])
        
        # 构建提示词 - 只为当前阶段生成事件
        prompt = self.build_stage_event_prompt(current_stage, previous_events)
        
        # 调用API生成事件
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.api_client.call_api([{"role": "user", "content": prompt}])
                content = response['choices'][0]['message']['content']
                
                # 使用更健壮的JSON提取方法
                events_data = self._extract_json(content)
                
                # 如果_extract_json失败，尝试直接解析
                if not events_data:
                    # 查找内容中的JSON对象
                    start_index = content.find('{')
                    end_index = content.rfind('}')
                    if start_index != -1 and end_index != -1 and end_index > start_index:
                        json_content = content[start_index:end_index + 1].strip()
                        try:
                            events_data = json.loads(json_content)
                        except json.JSONDecodeError:
                            print(f"⚠️ JSON解析失败，尝试修复...")
                            # 尝试修复常见的JSON格式问题
                            json_content = json_content.replace('\n', '').replace('\r', '')
                            json_content = re.sub(r',\s*}', '}', json_content)
                            json_content = re.sub(r',\s*]', ']', json_content)
                            # 移除可能的多余内容
                            brace_count = 0
                            valid_end = 0
                            for i, char in enumerate(json_content):
                                if char == '{':
                                    brace_count += 1
                                elif char == '}':
                                    brace_count -= 1
                                    if brace_count == 0:
                                        valid_end = i + 1
                                        break
                            if valid_end > 0:
                                json_content = json_content[:valid_end]
                            events_data = json.loads(json_content)
                
                # 验证事件数据结构
                is_valid = False
                if events_data and isinstance(events_data, dict):
                    # 检查是否包含事件列表
                    if '事件列表' in events_data:
                        event_list = events_data['事件列表']
                        if isinstance(event_list, list) and len(event_list) > 0:
                            # 验证每个事件的基本结构
                            valid_events = []
                            for event in event_list:
                                if isinstance(event, dict) and 'event_id' in event and 'name' in event:
                                    valid_events.append(event)
                            
                            if len(valid_events) > 0:
                                events_data['事件列表'] = valid_events
                                is_valid = True
                
                if is_valid:
                    stage_events = events_data
                    
                    # 分配连续事件ID（如果还没有的话）
                    if '事件列表' in stage_events:
                        # 检查是否需要分配事件ID
                        needs_id_assignment = any('event_id' not in event for event in stage_events['事件列表'])
                        if needs_id_assignment:
                            self._assign_event_ids(stage_events['事件列表'])
                        
                        # 为事件生成issue_id
                        for event in stage_events['事件列表']:
                            if "status" not in event:
                                event["status"] = "未完成"
                                
                            # 检查agent_builder是否存在
                            if self.agent_builder:
                                single_event_json = json.dumps(event, ensure_ascii=False)
                                issue_id = self.agent_builder._generate_global_event_id(
                                    user_id=self.user_id,
                                    agent_id=self.agent_id,
                                    event_json=single_event_json
                                )
                                if issue_id:
                                    event['issue_id'] = issue_id
                                    print(f"✅ 事件添加issue_id成功: {issue_id} - {event.get('name')}")
                            else:
                                print(f"⚠️ 未提供agent_builder，跳过issue_id生成: {event.get('name')}")
                    
                        # 添加到事件树并保存
                        self.full_event_tree.append(stage_events)
                        self._save_event_tree()
                        print(f"✅ 第 {current_stage_index + 1} 阶段事件生成完成")
                        return stage_events['事件列表']
                        
                print(f"⚠️ 尝试 {attempt + 1}/{max_retries}: 生成的阶段事件结构无效")
                # 添加调试信息
                print(f"🔍 响应内容预览: {content[:500]}...")
            except Exception as e:
                print(f"⚠️ 尝试 {attempt + 1}/{max_retries} 失败: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)
                
        print("❌ 所有重试失败，阶段事件生成失败")
        return []

    def _assign_event_ids(self, events: list):
        """为事件分配连续ID"""
        last_num = int(self.last_event_id[1:])  # 提取数字部分
        for i, event in enumerate(events):
            last_num += 1
            event["event_id"] = f"E{last_num:03d}"
            self.last_event_id = event["event_id"]

    def build_stage_event_prompt(self, stage: dict, previous_events: list) -> str:
        """构建阶段事件生成提示词，增加前序事件参考"""
        previous_events_str = json.dumps(previous_events[-10:], ensure_ascii=False) if previous_events else "[]"  # 只取最近10个事件
        final_stage_prompt = ""
        if self.is_final_stage:
            final_stage_prompt = "\n注意：这是接近结局的阶段，请设计引导用户走向大结局的事件，逐步收尾故事线。"

        return f"""
你是一位沉浸式互动剧情设计专家，用户将与智能体"{self.agent_name}"共同经历连贯真实的事件链。

基于以下信息为当前阶段生成事件：
角色信息：{self.base_info}
阶段信息：{json.dumps(stage, ensure_ascii=False)}
长期目标：{self.goals}
前序事件回顾（最近10个）：{previous_events_str}
{final_stage_prompt}

生成要求：
1. 只为当前阶段生成事件，不要涉及其他阶段
2. 包含3个主线事件、5个支线事件
3. 事件ID需从{self._get_next_event_id()}开始连续编号
4. 主线事件 importance ≥ 4，必须带有依赖（dependencies）
5. 支线事件 importance 为 3~4，无需依赖但应有明确触发条件
6. 所有事件必须包含以下字段：
   - event_id: 事件ID
   - type: 事件类型（主线/支线）
   - name: 事件标题
   - time: 具体时间
   - location: 具体地点
   - characters: 角色列表
   - cause: 事件起因
   - process: 事件经过
   - result: 事件结果
   - impact: 影响
   - importance: 重要性（1-5）
   - urgency: 紧急程度（1-5）
   - tags: 标签列表
   - trigger_conditions: 触发条件
   - dependencies: 依赖事件

严格按照以下JSON格式输出，不要包含任何额外文本：
{{
    "阶段": "{stage['阶段']}",
    "时间范围": "{stage['时间范围']}",
    "事件列表": [
        {{
            "event_id": "E001",
            "type": "主线",
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
            "importance": 5,
            "urgency": 4,
            "tags": ["关键词1", "关键词2"],
            "trigger_conditions": ["处于{stage['阶段']}", "亲密度>30"],
            "dependencies": []
        }}
    ]
}}
严格要求：
仅输出JSON对象，不包含任何解释、说明或多余文本
确保JSON格式完全正确（逗号分隔、引号闭合、无多余逗号）
键名和字符串值必须使用双引号（"），而非单引号（'）
数组和对象末尾不得有多余逗号
不要使用任何特殊字符或控制字符
        """

    def _get_next_event_id(self) -> str:
        """获取下一个事件ID"""
        num = int(self.last_event_id[1:]) + 1
        return f"E{num:03d}"

    def _get_initial_stage(self) -> dict:
        """获取初始阶段信息"""
        if not self.stages:
            self.stages = self.generate_lifecycle_stages()
        return self.stages[0] if self.stages else {"阶段": "初始阶段", "时间范围": "开始阶段"}

    def _save_event_tree(self):
        """保存事件树到数据库"""
        try:
            event_chain_data = {
                "version": "1.0",
                "event_tree": self.full_event_tree
            }
            chain_json = json.dumps(event_chain_data, ensure_ascii=False, indent=2)
            with self.db as db_conn:
                # 先尝试更新现有记录
                update_query = """
                               UPDATE agent_event_chains 
                               SET chain_json = %s, updated_at = CURRENT_TIMESTAMP 
                               WHERE agent_id = %s \
                               """
                rows_affected = db_conn._execute_update(update_query, (chain_json, self.agent_id))
                
                # 如果没有更新任何记录，则插入新记录
                if rows_affected == 0:
                    insert_query = """
                                   INSERT INTO agent_event_chains (user_id, agent_id, chain_json) 
                                   VALUES (%s, %s, %s) \
                                   """
                    db_conn._execute_update(insert_query, (self.user_id, self.agent_id, chain_json))
                
                print(f"✅ 事件链已保存到数据库")
        except Exception as e:
            print(f"❌ 保存事件树失败：{e}")
            import traceback
            traceback.print_exc()

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

            # 添加调试信息
            print(f"🔍 接收到的原始响应内容：")
            print(content)
            
            # 提取 JSON 内容
            start_index = content.find("[")
            end_index = content.rfind("]")
            if start_index != -1 and end_index != -1 and end_index > start_index:
                json_content = content[start_index:end_index + 1].strip()
                
                # 添加调试信息
                print(f"🔍 提取的JSON内容：")
                print(json_content)
                
                # 尝试解析JSON
                try:
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
                except json.JSONDecodeError as e:
                    print(f"❌ JSON解析失败: {e}")
                    # 尝试修复常见的JSON问题
                    try:
                        # 修复未转义的引号
                        json_content = json_content.replace('\\"', '"').replace('"', '\\"')
                        # 但保留对象内部的引号
                        json_content = re.sub(r'\\"([^"]*)\\"', r'"\1"', json_content)
                        stages = json.loads(json_content)
                        return stages
                    except json.JSONDecodeError:
                        print(f"❌ JSON修复尝试失败")
                        return []
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
[
  {{
    "阶段编号": "1",
    "阶段": "小学四年级",
    "时间范围": "2015年-2018年（18岁-21岁）",
    "阶段目标": "...",
    "是否为起点阶段": "true"
  }}
]
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

    def build_initial_event_prompt(self, stage):
        return f"""
你是一位沉浸式互动剧情设计专家，现在需要为用户与智能体"{self.agent_name}"设计一个引人入胜的初次相遇事件。

这个初始事件应该：
1. 具有强烈的故事感和代入感
2. 展现智能体的核心特征和个性
3. 为后续的互动奠定基础
4. 具有足够的冲突或趣味性来吸引用户继续互动

角色信息：
{self.base_info}

阶段信息：
{stage}

长期目标与背景：
{self.goals}

请严格按照以下JSON格式输出初始事件，不要包含任何额外文本：
{{
    "阶段": "{stage['阶段']}",
    "时间范围": "{stage['时间范围']}",
    "事件列表": [
        {{
            "event_id": "E001",
            "type": "主线",
            "name": "初次相遇",
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
            "importance": 5,
            "urgency": 4,
            "tags": ["初次相遇", "关键事件"],
            "trigger_conditions": ["初次互动"],
            "dependencies": []
        }}
    ]
}}

请特别注意：
- 这是用户与智能体的初次相遇，需要精心设计
- event_id必须为"E001"
- 类型必须是"主线"
- importance应为最高级别5
- 需要详细描述相遇的情景、原因和过程
- 要体现智能体的个性特征和当前阶段的背景

请以 JSON 形式输出初始事件。
"""

    def _extract_json(self, content: str) -> dict:
        """更健壮的JSON提取方法"""
        try:
            # 尝试直接解析整个内容
            if content.strip().startswith('{') or content.strip().startswith('['):
                result = json.loads(content)
                print("✅ 直接解析成功")
                return result

                # 尝试提取JSON对象或数组
                start_index = -1
                end_index = -1

                # 查找对象开始位置
                obj_start = content.find('{')
                arr_start = content.find('[')

                if obj_start != -1 and (arr_start == -1 or obj_start < arr_start):
                    start_index = obj_start
                    # 查找对应的结束大括号
                    brace_count = 0
                    for i in range(start_index, len(content)):
                        if content[i] == '{':
                            brace_count += 1
                        elif content[i] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end_index = i
                                break
                elif arr_start != -1:
                    start_index = arr_start
                    # 查找对应的结束方括号
                    bracket_count = 0
                    for i in range(start_index, len(content)):
                        if content[i] == '[':
                            bracket_count += 1
                        elif content[i] == ']':
                            bracket_count -= 1
                            if bracket_count == 0:
                                end_index = i
                                break

                if start_index != -1 and end_index != -1 and end_index > start_index:
                    json_str = content[start_index:end_index + 1]
                    safe_print(f"🔍 提取JSON片段，长度: {len(json_str)}")
                    result = json.loads(json_str)
                    safe_print("✅ 提取解析成功")
                    return result

            # 尝试处理代码块
            if '```json' in content:
                json_str = content.split('```json')[1].split('```')[0].strip()
                return json.loads(json_str)
                safe_print("✅ 代码块解析成功")
                return result
            elif '```' in content:
                parts = content.split('```')
                if len(parts) >= 2:
                    json_str = parts[1].strip()
                    result = json.loads(json_str)
                    print("✅ 代码块解析成功")
                    return result


        except json.JSONDecodeError as e:
            print(f"⚠️ JSON解析失败: {e}")
            error_pos = e.pos if hasattr(e, 'pos') else 0
            start = max(0, error_pos - 50)
            end = min(len(content), error_pos + 50)
            print(f"🔍 错误位置附近的内容: {content[start:end]}")

            # 最终尝试修复常见错误
            try:
                print("🔄 尝试修复JSON格式...")
                # 修复常见的格式错误
                fixed_content = content.replace('\n', '').replace('\r', '')
                # 移除括号后的多余空格
                fixed_content = re.sub(r'(?<=[{\[,])\s+', '', fixed_content)
                # 移除括号前的多余空格
                fixed_content = re.sub(r'\s+(?=[}\]])', '', fixed_content)
                # 修复相邻字符串缺少逗号的情况
                fixed_content = re.sub(r'(?<=\w)"(?=\w)', r'","', fixed_content)
                # 修复多余的逗号
                fixed_content = re.sub(r',\s*]', ']', fixed_content)  # 修复多余的逗号
                fixed_content = re.sub(r',\s*}', '}', fixed_content)
                fixed_content = re.sub(r'[\u0000-\u001F]', '', fixed_content)  # 移除控制字符

                # 再次尝试解析
                if fixed_content.strip().startswith('{') or fixed_content.strip().startswith('['):
                    result = json.loads(fixed_content)
                    print("✅ 修复后解析成功")
                    return result

            except Exception as e:
                print(f"⚠️ 修复后解析仍失败: {e}")

            print("❌ 所有JSON解析方法都失败")
            return {}

    def generate_initial_event_only(self):
        """
        只生成初始事件，用于快速初始化
        """
        stages = self.generate_lifecycle_stages()
        
        # 只处理第一个阶段来生成初始事件
        if stages:
            first_stage = stages[0]
            print(f"🔍 正在生成初始事件，阶段：{first_stage.get('阶段', '未知阶段')} ...")
            
            # 使用专门的初始事件提示词
            prompt = self.build_initial_event_prompt(first_stage)
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = self.api_client.call_api([{"role": "user", "content": prompt}])
                    content = response['choices'][0]['message']['content']
                    events = self._extract_json(content)

                    if events and isinstance(events, dict) and '事件列表' in events:
                        stage_event_list = events['事件列表']
                        for idx, event in enumerate(stage_event_list):
                            # 设置默认状态
                            if "status" not in event:
                                event["status"] = "未完成"

                            # 生成全局唯一的issue_id
                            single_event_json = json.dumps(event, ensure_ascii=False)
                            if self.agent_builder:  # 确保agent_builder存在
                                issue_id = self.agent_builder._generate_global_event_id(
                                    user_id=self.user_id,
                                    agent_id=self.agent_id,
                                    event_json=single_event_json
                                )
                                if issue_id:
                                    stage_event_list[idx]['issue_id'] = issue_id
                                    print(f"✅ 初始事件添加issue_id成功: {issue_id} - {event.get('name')}")
                                else:
                                    print(f"⚠️ 初始事件无issue_id: {event.get('name')}")

                            # 确保初始事件的event_id为E001
                            stage_event_list[idx]['event_id'] = "E001"
                            print(f"✅ 设置初始事件event_id为E001：{event.get('name')}")

                    # 验证数据结构
                    if events and isinstance(events, dict) and '事件列表' in events and len(events['事件列表']) > 0:
                        # 只保留初始事件
                        events['事件列表'] = [e for e in events['事件列表'] if e.get('event_id') == 'E001']
                        
                        # 保存初始事件到数据库
                        try:
                            event_chain_data = {
                                "version": "1.0",
                                "event_tree": [events]  # 只包含初始事件
                            }
                            chain_json = json.dumps(event_chain_data, ensure_ascii=False, indent=2)
                            with self.db as db_conn:
                                # 先尝试更新现有记录
                                update_query = """
                                               UPDATE agent_event_chains 
                                               SET chain_json = %s, updated_at = CURRENT_TIMESTAMP 
                                               WHERE agent_id = %s \
                                               """
                                rows_affected = db_conn._execute_update(update_query, (chain_json, self.agent_id))
                                
                                # 如果没有更新任何记录，则插入新记录
                                if rows_affected == 0:
                                    insert_query = """
                                                   INSERT INTO agent_event_chains (user_id, agent_id, chain_json) 
                                                   VALUES (%s, %s, %s) \
                                                   """
                                    db_conn._execute_update(insert_query, (self.user_id, self.agent_id, chain_json))
                                
                                print(f"✅ 初始事件已存入数据库")
                        except Exception as e:
                            print(f"❌ 初始事件数据库操作异常：{e}")
                            import traceback
                            traceback.print_exc()
                            
                        return events
                        
                    print(f"⚠️ 尝试 {attempt + 1}/{max_retries}: 生成的初始事件结构无效")
                except Exception as e:
                    print(f"⚠️ 尝试 {attempt + 1}/{max_retries} 失败: {e}")
                    import traceback
                    traceback.print_exc()
                    time.sleep(1)
                    
            print("❌ 所有重试失败，初始事件生成失败")
            
        return {}

    def generate_events_for_stage(self, stage, start_event_id=1):
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
                        # 检查agent_builder是否存在
                        if self.agent_builder:
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
                        else:
                            print(f"⚠️ 未提供agent_builder，跳过issue_id生成: {event.get('name')}")

                        # 设置连续的event_id（从指定编号开始）
                        event_id_num = start_event_id + idx
                        event_id = f"E{event_id_num:03d}"
                        stage_event_list[idx]['event_id'] = event_id
                        print(f"✅ 设置连续event_id：{event_id} - {event.get('name')}")

                # 验证数据结构（确保含event_id和有效事件列表）
                if events and isinstance(events, dict) and '事件列表' in events and len(events['事件列表']) > 0:
                    # 过滤掉没有event_id的无效事件
                    events['事件列表'] = [e for e in events['事件列表'] if e.get('event_id')]
                    return events
                print(f"⚠️ 尝试 {attempt + 1}/{max_retries}: 生成的事件链结构无效（无事件或无有效event_id）")
            except Exception as e:
                print(f"⚠️ 尝试 {attempt + 1}/{max_retries} 失败: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)
        print("❌ 所有重试失败，返回空事件结构")
        return {}


    def build_full_event_tree(self):
        stages = self.generate_lifecycle_stages()

        full_tree = []

        # 检查数据库中是否已存在初始事件，以确定正确的起始编号
        event_counter = 1  # 默认从E001开始编号
        try:
            with self.db as db_conn:
                # 查询现有的事件链
                query = """
                        SELECT chain_json
                        FROM agent_event_chains
                        WHERE agent_id = %s
                        ORDER BY updated_at DESC LIMIT 1 \
                        """
                result = db_conn._execute_query(query, (self.agent_id,))

                if result:
                    chain_data = json.loads(result[0]['chain_json'])
                    event_tree = chain_data.get('event_tree', [])

                    # 计算现有事件数量，确定下一个事件ID
                    total_events = sum(len(stage.get('事件列表', [])) for stage in event_tree)
                    if total_events > 0:
                        event_counter = total_events + 1
                        print(f"🔍 检测到已有 {total_events} 个事件，下一个事件ID将从 E{event_counter:03d} 开始")
        except Exception as e:
            print(f"⚠️ 检查现有事件时出错: {e}")

        for stage_idx, stage in enumerate(stages):
            print(f"🔍 正在生成事件阶段：{stage.get('阶段', '未知阶段')} ...")

            # 从正确的编号开始生成事件
            stage_events = self.generate_events_for_stage(stage, event_counter)

            # 更新事件计数器
            if '事件列表' in stage_events:
                event_counter += len(stage_events['事件列表'])

            full_tree.append(stage_events)

        print(f"✅ 事件链构建完成，共处理 {len(full_tree)} 个阶段")
        self.full_event_tree = full_tree
        print("🔍 开始执行数据库存储操作...")
        return full_tree

    def check_background_generation_status(self):
        """
        检查后台事件链生成状态（已废弃）
        返回:
        - "completed": 已完成
        - "in_progress": 正在进行中
        - "not_started": 尚未开始
        - "failed": 失败
        """
        # 该方法已废弃，不再使用
        return "completed"  # 默认返回已完成状态

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

    def generate_and_save(self) -> list:
        """改为仅生成初始事件，后续阶段在交互中生成"""
        # 首先检查数据库中是否已有事件链
        try:
            with self.db as db_conn:
                query = """
                        SELECT chain_json
                        FROM agent_event_chains
                        WHERE agent_id = %s
                        ORDER BY updated_at DESC LIMIT 1 \
                        """
                result = db_conn._execute_query(query, (self.agent_id,))
                
                if result:
                    chain_data = json.loads(result[0]['chain_json'])
                    self.full_event_tree = chain_data.get('event_tree', [])
                    # 更新last_event_id为最后一个事件的ID
                    if self.full_event_tree:
                        last_stage = self.full_event_tree[-1]
                        if '事件列表' in last_stage and last_stage['事件列表']:
                            self.last_event_id = last_stage['事件列表'][-1]['event_id']
                    print(f"✅ 从数据库加载现有事件链，最后事件ID: {self.last_event_id}")
                    return self.full_event_tree
        except Exception as e:
            print(f"⚠️ 加载现有事件链时出错: {e}")

        # 如果数据库中没有事件链，则生成初始事件
        if not self.full_event_tree:
            initial_event = self.generate_initial_event_only()
            if initial_event:
                self.full_event_tree = [initial_event]
                if '事件列表' in initial_event and initial_event['事件列表']:
                    self.last_event_id = initial_event['事件列表'][0]['event_id']
        
        # 保存事件链到数据库
        self._save_event_tree()
        return self.full_event_tree



if __name__ == "__main__":
    generator = EventTreeGenerator(
        agent_name="萧炎",
        api_key="sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV",
        user_id="1",
        agent_id="37"
    )
    # generator.generate_lifecycle_stages()
    generator.generate_and_save()
