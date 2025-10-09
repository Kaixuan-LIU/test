import os
import json
import random
import hashlib
import time
from typing import List, Dict
from Event_builder import EventTreeGenerator
from api_handler import ChatFireAPIClient


class EventDispatcher:
    def __init__(
        self,
        all_events: List[Dict],
        completed_events: List[str],
        agent_profile: Dict,
        history_messages: List[Dict],
        api_client: ChatFireAPIClient,
        agent_name: str = "智能体"
    ):
        self.all_events = all_events
        self.completed_events = completed_events
        self.agent_profile = agent_profile
        self.history_messages = history_messages
        self.api_client = api_client
        self.agent_name = agent_name

    def check_stage_completion(self) -> bool:
        """检查当前阶段是否所有事件都已完成"""
        if not self.all_events:
            return False

        current_stage = self._get_current_stage()
        if not current_stage:
            return False

        stage_events = current_stage.get("事件列表", [])
        completed_count = sum(1 for e in stage_events
                              if e.get("event_id") in self.completed_events)

        # 所有主线事件完成即认为阶段完成
        main_events = [e for e in stage_events if e.get("type") == "主线"]
        completed_main = sum(1 for e in main_events
                             if e.get("event_id") in self.completed_events)

        return completed_main == len(main_events)

    def get_next_stage_events(self):
        """获取下一阶段事件（调用生成器生成）"""
        # 获取前序事件
        previous_events = []
        for stage in self.all_events:
            previous_events.extend(stage.get("事件列表", []))

        # 调用生成器生成下一阶段事件
        generator = EventTreeGenerator(
            agent_name=self.agent_name,
            api_key=self.api_client.api_key,
            agent_id=self.agent_profile.get("agent_id"),
            user_id=self.agent_profile.get("user_id"),
            agent_builder=None
        )
        # 加载现有事件树
        generator.full_event_tree = self.all_events
        generator.current_stage_index = len(self.all_events) - 1
        if self.all_events:
            last_stage = self.all_events[-1]
            last_event = last_stage["事件列表"][-1] if last_stage["事件列表"] else {}
            generator.last_event_id = last_event.get("event_id", "E001")

        # 生成下一阶段事件
        new_events = generator.generate_next_stage_events(previous_events)
        if new_events:
            self.all_events = generator.full_event_tree
            return new_events
        return []

    def _get_current_stage(self):
        """获取当前阶段"""
        if not self.all_events:
            return None
        return self.all_events[-1] if self.all_events else None


    def analyze_state_from_history(self) -> Dict:
        """
        调用大模型分析对话历史，推断当前阶段、亲密度、知识储备。
        """
        prompt = f"""
你是一个用户行为与情绪状态分析专家，请根据以下对话片段，推测当前智能体与用户互动所处的生命周期阶段、亲密度等级（0-100）、以及用户已协助智能体掌握的知识关键词列表。

对话片段：
{json.dumps(self.history_messages[-10:], ensure_ascii=False)}

请提取以下内容（以 JSON 格式输出）：
{{
  "阶段": "智能体当前生命周期阶段",
  "亲密度": 整数值（当前角色对用户的亲密度估计）,
  "知识点": ["从对话中角色学到或提到的知识关键词"],
  "已完成事件": ["推测完成的事件 ID 列表"],
  "首次互动": true/false,
  "当前知识储备": ["心理调节", "社团组织"],
  "当前生命周期阶段": "当前生命周期阶段"
}}
"""
        try:
            # 调用API接口，传入prompt参数，设置temperature和max_tokens参数
            response = self.api_client.call_api(
                [{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=1000
            )
            # 从API返回的response中提取content
            content = response["choices"][0]["message"]["content"]
            # 在content中查找第一个和最后一个大括号的位置
            json_start = content.find("{")
            json_end = content.rfind("}")
            # 返回json.loads(content[json_start:json_end + 1])的结果
            result = json.loads(content[json_start:json_end + 1])

            # 验证必需字段是否存在
            if "亲密度" not in result:
                raise ValueError("❌ 模型返回缺少必要字段 '亲密度'")

            return result

        except Exception as e:
            # 打印错误信息并抛出异常（或根据需求重试）
            print(f"❌ 状态分析失败：{e}")
            raise  # 保留异常以便上层处理

    def select_next_event(self) -> Dict:
        """
        调用大模型选择合适的事件，或调用兜底事件生成器。
        """
        state = self.analyze_state_from_history()
        current_stage = state.get("当前生命周期阶段", "")
        current_affinity = state.get("当前亲密度", 0)  # 使用 get 方法并设置默认值为 0
        current_knowledge = state.get("当前知识储备", [])

        prompt = f"""
你是一个剧情导演，任务是根据当前剧情阶段与角色状态，从提供的事件链中选择下一个可触发的事件。

🧠 输入信息：
1. 智能体基本信息：{json.dumps(self.agent_profile, ensure_ascii=False)}
2. 当前生命周期阶段：{current_stage}
3. 当前亲密度：{current_affinity}
4. 当前知识储备：{json.dumps(current_knowledge, ensure_ascii=False)}
5. 已完成事件ID列表：{json.dumps(self.completed_events, ensure_ascii=False)}
6. 事件链：{json.dumps(self.all_events, ensure_ascii=False)}
7. 历史对话片段：{json.dumps(self.history_messages[-10:], ensure_ascii=False)}

📌 要求：
- 首先尝试在事件链中找到最符合当前状态的一个事件（主线优先）
- 如果没有合适的事件，请严格只输出字符串："fallback"
- 不要解释、不添加额外内容、不编造字段

输出格式：
事件对象 JSON 或字符串："fallback"
"""
        try:
            response = self.api_client.call_api(
                [{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=1800
            )
            reply = response['choices'][0]['message']['content'].strip()
            if "fallback" in reply.lower():
                return self.generate_fallback_event(current_stage, current_affinity)
            return json.loads(reply)
        except Exception as e:
            print(f"❌ 事件选择失败，自动兜底：{e}")
            return self.generate_fallback_event(current_stage, current_affinity)

    def generate_fallback_event(self, current_stage: str, current_affinity: int) -> Dict:
        """
        生成一个轻松日常事件作为兜底。
        """
        prompt = f"""
当前生命周期阶段：{current_stage}
智能体名称：{self.agent_name}
亲密度：{current_affinity}
智能体基础信息：{json.dumps(self.agent_profile, ensure_ascii=False, indent=2)}

请生成一个轻松自然、有具体人物、时间、地点的“日常”事件，用于主线事件之间的调剂。
要求：
- type 为“日常”
- dependencies 为 []
- trigger_conditions 为 []

返回以下格式：
{{
  "event_id": "TEMP_{random.randint(1000, 9999)}",
  "type": "日常",
  "name": "事件标题",
  "time": "具体时间",
  "location": "具体地点",
  "characters": ["用户", "{self.agent_name}"],
  "cause": "...",
  "process": "...",
  "result": "...",
  "impact": {{
    "心理状态变化": "...",
    "知识增长": "...",
    "亲密度变化": "+1"
  }},
  "importance": 2,
  "urgency": 1,
  "tags": ["日常", "陪伴"],
  "trigger_conditions": [],
  "dependencies": []
}}
"""
        try:
            response = self.api_client.call_api(
                [{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=800
            )
            content = response['choices'][0]['message'].get('content', '').strip()
            start, end = content.find("{"), content.rfind("}")
            if start != -1 and end != -1:
                return json.loads(content[start:end + 1])
        except Exception as e:
            print(f"❌ 临时事件生成失败：{e}")

        return {
            "event_id": f"TEMP_{random.randint(1000, 9999)}",
            "type": "日常",
            "name": "临时事件（生成失败）",
            "time": "某日",
            "location": "未知地点",
            "characters": ["用户", self.agent_name],
            "cause": "生成失败",
            "process": "生成失败",
            "result": "生成失败",
            "impact": {
                "心理状态变化": "无",
                "知识增长": "无",
                "亲密度变化": "+0"
            },
            "importance": 1,
            "urgency": 1,
            "tags": ["fallback"],
            "trigger_conditions": [],
            "dependencies": []
        }
