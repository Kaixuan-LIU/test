import json
import uuid
import random
import os
from typing import Dict, Any, List, Tuple
from pathlib import Path
from app_config import config
from Event_builder import EventTreeGenerator
from api_handler import ChatFireAPIClient
from database import MySQLDB



class AgentTemplateManager:
    def __init__(self, api_key: str, data_path: str = "agents", user_id: int = 1):
        self.client = ChatFireAPIClient(api_key=api_key)
        self.data_path = data_path
        self.user_id = user_id
        # 使用远程数据库配置
        self.db = MySQLDB(
            **config.DB_CONFIG
        )

        # 从数据库加载MBTI知识库
        self.mbti_knowledge = self._load_mbti_from_db()
        self.tag_pool = self._load_tag_templates()
    def _load_mbti_from_db(self) -> dict:
        """从数据库加载MBTI类型和认知功能数据"""
        mbti_data = {
            "MBTI_TYPES": {},
            "COGNITIVE_FUNCTIONS": {}
        }
        try:
            with self.db as db:
                # 查询 templates 表中 template_type 为 'mbti' 的活跃模板
                query = """
                    SELECT content_json 
                    FROM templates 
                    WHERE template_type = 'mbti' AND is_active = TRUE
                """
                results = db._execute_query(query)

                if not results:
                    print("⚠️ 数据库中未找到MBTI数据")
                    return mbti_data

                # 解析查询结果（实际只有一条记录，包含所有数据）
                for item in results:
                    # 直接解析整条JSON数据
                    content = json.loads(item["content_json"])

                    # 提取所有MBTI类型（如ENFJ、ENFP等）
                    mbti_data["MBTI_TYPES"] = content.get("MBTI_TYPES", {})
                    # 提取所有认知功能（如Fe、Fi等）
                    mbti_data["COGNITIVE_FUNCTIONS"] = content.get("COGNITIVE_FUNCTIONS", {})

                # 打印加载结果
                print(
                    f"✅ 成功从数据库加载 MBTI 知识库（共 {len(mbti_data['MBTI_TYPES'])} 种类型，{len(mbti_data['COGNITIVE_FUNCTIONS'])} 种认知功能）")
                return mbti_data
        except Exception as e:
            print(f"❌ 加载MBTI数据失败：{e}")
            return {"MBTI_TYPES": {}, "COGNITIVE_FUNCTIONS": {}}

    def _load_tag_templates(self):
        """从数据库 template_type = 'attribute' 中加载tag池数据"""
        try:
            with self.db as db:
                # 查询活跃的attribute类型模板
                query = """
                    SELECT content_json 
                    FROM templates 
                    WHERE template_type = 'attribute' AND is_active = TRUE
                """
                results = db._execute_query(query)

                if not results:
                    print("⚠️ 数据库中未找到attribute类型的tag模板数据")
                    return {}

                # 解析查询结果（假设只有一条活跃的attribute模板记录）
                tag_pool = {}
                for item in results:
                    # 合并所有attribute模板的内容（如果有多个版本）
                    content = json.loads(item["content_json"])
                    tag_pool.update(content)

                print(f"✅ 成功从数据库加载tag模板（共 {len(tag_pool)} 个标签定义）")
                return tag_pool
        except json.JSONDecodeError:
            print("错误：数据库中的attribute模板JSON格式不正确")
        except Exception as e:
            print(f"❌ 加载tag模板时发生错误: {str(e)}")
            return {}

class AgentBuilder:
    def __init__(self, api_key: str, data_path: str = "agents", user_id: int = 1):
        self.api_key = api_key
        self.client = ChatFireAPIClient(api_key=api_key)
        self.template_manager = AgentTemplateManager(api_key=api_key, data_path=data_path)
        self.data_path = data_path
        self.user_id = user_id
        # 使用远程数据库配置
        self.db = MySQLDB(
            ** config.DB_CONFIG
        )
        self.mbti_knowledge = self._load_mbti_from_db()
        self.tag_pool = self._load_tag_templates()

    def _load_mbti_from_db(self) -> dict:
        """从数据库加载MBTI类型和认知功能数据"""
        mbti_data = {
            "MBTI_TYPES": {},
            "COGNITIVE_FUNCTIONS": {}
        }
        try:
            with self.db as db:
                # 查询 templates 表中 template_type 为 'mbti' 的活跃模板
                query = """
                        SELECT content_json
                        FROM templates
                        WHERE template_type = 'mbti' \
                          AND is_active = TRUE \
                        """
                results = db._execute_query(query)

                if not results:
                    print("⚠️ 数据库中未找到MBTI数据")
                    return mbti_data

                # 解析查询结果（实际只有一条记录，包含所有数据）
                for item in results:
                    # 直接解析整条JSON数据
                    content = json.loads(item["content_json"])

                    # 提取所有MBTI类型（如ENFJ、ENFP等）
                    mbti_data["MBTI_TYPES"] = content.get("MBTI_TYPES", {})
                    # 提取所有认知功能（如Fe、Fi等）
                    mbti_data["COGNITIVE_FUNCTIONS"] = content.get("COGNITIVE_FUNCTIONS", {})

                # 打印加载结果
                print(
                    f"✅ 成功从数据库加载 MBTI 知识库（共 {len(mbti_data['MBTI_TYPES'])} 种类型，{len(mbti_data['COGNITIVE_FUNCTIONS'])} 种认知功能）")
                return mbti_data
        except Exception as e:
            print(f"❌ 加载MBTI数据失败：{e}")
            return {"MBTI_TYPES": {}, "COGNITIVE_FUNCTIONS": {}}

    def _load_tag_templates(self):
        """从数据库 template_type = 'attribute' 中加载tag池数据"""
        try:
            with self.db as db:
                # 查询活跃的attribute类型模板
                query = """
                        SELECT content_json
                        FROM templates
                        WHERE template_type = 'attribute' \
                          AND is_active = TRUE \
                        """
                results = db._execute_query(query)

                if not results:
                    print("⚠️ 数据库中未找到attribute类型的tag模板数据")
                    return {}

                # 解析查询结果（假设只有一条活跃的attribute模板记录）
                tag_pool = {}
                for item in results:
                    # 合并所有attribute模板的内容（如果有多个版本）
                    content = json.loads(item["content_json"])
                    tag_pool.update(content)

                print(f"✅ 成功从数据库加载tag模板（共 {len(tag_pool)} 个标签定义）")
                return tag_pool
        except json.JSONDecodeError:
            print("错误：数据库中的attribute模板JSON格式不正确")
        except Exception as e:
            print(f"❌ 加载tag模板时发生错误: {str(e)}")
            return {}


    def _format_template(self, template: Dict[str, Any]) -> str:
        formatted = ""
        for key, value in template.items():
            if key in ["爱好", "知识体系"] and isinstance(value, list):
                formatted += f"{key}：\n"
                for item in value:
                    formatted += f"  - {item}\n"
            elif key == "个人技能" and isinstance(value, dict):
                formatted += f"{key}：\n"
                for skill_key, skill_value in value.items():
                    formatted += f"  {skill_key}：{skill_value}\n"
            elif key == "国家地区":
                    formatted += f"{key}：{value}\n"
            elif key == "与玩家关系":
                formatted += f"{key}：{value}\n"
            elif key == "声音":
                formatted += f"{key}：{value}\n"
            else:
                formatted += f"{key}：{value}\n"
        return formatted

    def _format_prompt_for_completion(self, user_input: str) -> str:
        with self.db as db:
            template_data = db.get_template_by_type_key(
                template_type="agent_info",
                template_key="agent_generation_template",
                version='1.0'
            )
            if not template_data:
                raise ValueError("未找到agent_generation_template模板")
            empty_template = json.loads(template_data['content_json'])

        empty_template_str = self._format_template(empty_template)

        prompt = f"""
请根据用户输入的初始信息，按照以下内容进行补全，为想要生成的智能体的基本信息：
{empty_template_str}
用户输入的初始信息：
{user_input}



注意：
1.输出内容必须与模板和参考示例格式一致，内容与参考示例无关。
2.输出内容以纯文本格式给出，不要输出冗余信息。
3.生成的智能体基本信息需要以用户输入信息为基础，并根据用户输入信息进行补充，符合设定世界观的逻辑。
"""
        return prompt

    def complete_user_input(self, user_input: str) -> str:
        prompt = self._format_prompt_for_completion(user_input)
        messages = [{"role": "user", "content": prompt}]

        print(f"发送给大模型的提示词:\n{prompt}")
        response = self.client.call_api(
            messages=messages,
            temperature=0.8,
            top_p=0.9,
            max_tokens=3000
        )

        if not response or 'choices' not in response:
            raise Exception("大模型响应失败，无法补全用户输入")

        content = response['choices'][0]['message']['content']
        print(f"🔍🔍 大模型基础信息响应：\n{content}")
        return content.strip()

    def _format_prompt_for_agent_creation(self, completed_info_text: str) -> str:
        mbti_type = "UNKNOWN"
        for line in completed_info_text.splitlines():
            if line.startswith("MBTI类型："):
                try:
                    mbti_type = line.split("：", 1)[1].strip()  # 更安全地提取
                    if mbti_type:  # 确保不为空
                        break
                except IndexError:
                    continue

        mbti_data = self.mbti_knowledge.get("MBTI_TYPES", {}).get(mbti_type, {})
        function_stack = mbti_data.get("function_stack", [])

        cognitive_functions = self.mbti_knowledge.get("COGNITIVE_FUNCTIONS", {})
        function_descriptions = []

        for idx, func in enumerate(function_stack):
            func_detail = cognitive_functions.get(func, {})
            name = func_detail.get("meta", {}).get("name", func)
            position_key = f"position_{idx + 1}"
            pos_data = func_detail.get("positions", {}).get(position_key, {})

            strengths = pos_data.get("strengths", [])
            weaknesses = pos_data.get("weaknesses", [])

            function_descriptions.append(
                f"{idx + 1}. {name}（{func}）\n优点：{', '.join(strengths)}\n缺点：{', '.join(weaknesses)}")

        mbti_knowledge_text = "\n".join(function_descriptions) or "无"

        # 获取属性池模板
        tag_pool = self.template_manager._load_tag_templates()

        prompt = f"""

请根据智能体基础信息和MBTI类型，结合以下要求生成属性池：
1. 状态标签需包含【生理/心理/社交/特殊】四个维度
2. 每个标签必须包含触发条件和影响描述
3. 特征标签需关联行动风格和社交倾向
4. 经历标签需按教育/职业/人生里程碑/创伤/成就分类
5. 关系标签需区分情感/工作关系

基础信息：
{completed_info_text}

MBTI功能堆栈与性格描述：
{mbti_knowledge_text}

Tag池模板：
{json.dumps(tag_pool, indent=2, ensure_ascii=False)}

输出格式：
【性格状态】
[此处输出性格描述]

【Tag池】
状态标签：
  生理状态：
    - 标签名 (触发条件: [条件], 影响: [影响], 存在依据: [说明])
    ...
  心理状态：
    - 标签名 (触发条件: [条件], 影响: [影响], 存在依据: [说明])
    ...
  社交状态：
    - 标签名 (触发条件: [条件], 影响: [影响], 存在依据: [说明])
    ...
  特殊状态：
    - 标签名 (触发条件: [条件], 影响: [影响], 存在依据: [说明])
    ...
特征标签：
  - 标签名 (行为表现: [行为], 影响: [影响], 存在依据: [说明])
  ...
经历标签：
  教育经历：
    - 标签名 (触发条件: [条件], 影响: [影响], 存在依据: [说明])
    ...
  职业发展：
    - 标签名 (触发条件: [条件], 影响: [影响], 存在依据: [说明])
    ...
  ...
关系标签：
  - 标签名 (类别: [类别], 触发条件: [条件], 影响: [影响], 存在依据: [说明])
  ...

注意：
1. 只列出角色实际存在的标签，不存在的标签不要列出
2. 存在依据要结合角色的背景信息
3. 状态标签和经历标签需满足触发条件才存在
"""
        return prompt

    def generate_agent_properties(self, completed_info_text: str) -> str:
        prompt = self._format_prompt_for_agent_creation(completed_info_text)
        messages = [{"role": "user", "content": prompt}]

        response = self.client.call_api(
            messages=messages,
            temperature=0.6,
            top_p=0.8,
            max_tokens=3000
        )

        if not response or 'choices' not in response:
            raise Exception("大模型响应失败，无法生成智能体属性")

        content = response['choices'][0]['message']['content']
        print(f"🔍🔍 大模型状态信息响应：\n{content}")
        return content.strip()

    def _generate_base_attributes(self, mbti_type: str) -> dict:
        """基于MBTI生成基础属性"""
        cognitive_map = {
            "ISTJ": {"注意力": 8, "记忆力": 9, "逻辑力": 7},
            "ENFP": {"创造力": 9, "社交力": 8, "直觉力": 8},
            "INFJ": {"直觉力": 9, "情绪稳定性": 8, "逻辑力": 7},
            "INTP": {"逻辑力": 9, "注意力": 8, "记忆力": 7},
            "ESFJ": {"社交力": 9, "情绪稳定性": 8, "记忆力": 7},
            "ENTP": {"逻辑力": 9, "创造力": 8, "社交力": 7},
            "ISFP": {"注意力": 8, "记忆力": 7, "创造力": 8},
            "ENFJ": {"社交力": 9, "情绪稳定性": 8, "创造力": 7},
            "INTJ": {"逻辑力": 9, "注意力": 8, "情绪稳定性": 7},
            "ISFJ": {"社交力": 8, "记忆力": 9, "情绪稳定性": 7},
            "ESTJ": {"注意力": 9, "记忆力": 8, "逻辑力": 7},
            "ESFP": {"注意力": 8, "记忆力": 7, "创造力": 8},
            "ENTJ": {"逻辑力": 9, "注意力": 8, "社交力": 7},
            "ISTP": {"注意力": 9, "记忆力": 8, "创造力": 7}
        }
        return cognitive_map.get(mbti_type[:4], {
            "注意力": random.randint(5, 9),
            "记忆力": random.randint(5, 9),
            "逻辑力": random.randint(5, 9),
            "创造力": random.randint(5, 9),
            "社交力": random.randint(5, 9),
            "情绪稳定性": random.randint(5, 9)
        })

    def format_agent_full_info(self, completed_info_text: str, agent_state_text: str, agent_name: str) -> str:
        prompt = f"""
以下是一个智能体的基础信息与状态信息，请按照指定格式整理：

要求输出的字段包括：
- 世界观
- 姓名
- 年龄
- 生日
- 教育背景
- 家庭背景
- 职业
- 国家地区
- 理想
- 爱好
- 声音
- 个人技能
- 知识体系
- 与玩家关系
- MBTI类型
- 心理状态
- Tag池（包含存在的状态标签、特征标签、经历标签、关系标签）

输出格式要求为JSON对象，键值对如下：
{{
    "世界观": "字符串",
    "姓名": "字符串",
    ...,
    "Tag池": {{
        "状态标签": {{
            "生理状态": [
                {{"标签": "标签名", "触发条件": "条件", "影响": "影响", "存在依据": "说明"}},
                ...
            ],
            "心理状态": [...],
            "社交状态": [...],
            "特殊状态": [...]
        }},
        "特征标签": [
            {{"标签": "标签名", "行为表现": "行为", "影响": "影响", "存在依据": "说明"}},
            ...
        ],
        "经历标签": {{
            "教育经历": [
                {{"标签": "标签名", "触发条件": "条件", "影响": "影响", "存在依据": "说明"}},
                ...
            ],
            "职业发展": [...],
            ...
        }},
        "关系标签": [
            {{"标签": "标签名", "类别": "类别", "触发条件": "条件", "影响": "影响", "存在依据": "说明"}},
            ...
        ]
    }}
}}


原始信息如下：
【基础信息】
{completed_info_text}

【状态信息】
{agent_state_text}
"""
        messages = [{"role": "user", "content": prompt}]
        response = self.client.call_api(
            messages=messages,
            temperature=0.5,
            top_p=0.9,
            max_tokens=2500
        )

        if not response or 'choices' not in response:
            raise Exception("大模型响应失败，无法统一格式化智能体信息")

        content = response['choices'][0]['message'].get('content', '')
        content = content.strip().replace('\ufeff', '')

        print("💡💡💡💡 接收到的原始响应内容：")
        print(content)
        start_index = content.find("{")
        end_index = content.rfind("}")

        if start_index != -1 and end_index != -1 and end_index > start_index:
            json_content = content[start_index:end_index + 1].strip()
        else:
            print("❌❌❌❌ 未找到有效的JSON对象结构")
            json_content = "{}"

        try:
            agent_data = json.loads(json_content)
            mbti_type = "INFP"  # 默认值
            for line in completed_info_text.splitlines():
                if line.startswith("MBTI类型："):
                    mbti_type = line.split("：", 1)[1].strip()
                    break
            agent_data["基础属性"] = self._generate_base_attributes(mbti_type)
            final_data = {"version": "智能体信息模板1.0"}
            final_data.update(agent_data)  # 包含所有字段
            json_with_version = json.dumps(final_data, ensure_ascii=False, indent=2)

            # 保存到数据库
            with self.db as db:
                user_id = self.user_id
                agent_id = db.insert_agent(user_id, agent_name, json_with_version)
            if agent_id:
                print(f"✅ 智能体信息已成功存入数据库，ID: {agent_id}")
            else:
                print("❌❌ 智能体信息存入数据库失败，未返回有效 ID")
            return agent_data, agent_id  # 返回包含基础属性的数据
        except json.JSONDecodeError as e:
            print(f"❌❌❌❌ 智能体信息JSON解析失败：{e}")
            return {"raw_data": json_content}, agent_id


    def generate_life_events(self, full_formatted_text: str, agent_name: str, agent_id: int) -> str:
        prompt = f"""
请基于角色信息，生成该角色迄今为止的人生中的重要事件并进行记录。
示例：年份（岁数）：事件描述
1. 2006年（3岁）：首次接触电子积木玩具，展现出对逻辑排列的强烈兴趣，能独立完成远超年龄难度的拼搭。
2. 2010年（7岁）：小学二年级参加奥数兴趣班，首次发现通过数学公式解决复杂问题的乐趣。
3. 2014年（11岁）：家庭购置第一台电脑，自学Scratch编程并制作简单动画游戏，编程热情被点燃。
4. 2017年（14岁，初三）：
- 以全市前50名成绩考入重点高中理科实验班。
- 阅读《三体》，价值观受到冲击，开始思考技术与人性关系。
5. 2018年（15岁，高一）：参加信息学奥赛（NOIP），获省级二等奖，确认计算机为未来方向。
6. 2019年（16岁，高二）：
- 挫折事件：因沉迷开发一个策略游戏原型导致物理成绩滑坡，被班主任约谈。
- 转折点：父亲引导其制定时间管理表，首次学会平衡兴趣与学业。
7. 2020年（17岁，高三）：
- 获全国青少年信息学联赛（NOI）省级一等奖。
- 放弃清北竞赛保送资格，坚持参加高考，目标明确选择A大学计算机系。
8. 2021年（18岁，大一）：
- 价值观事件：选修《科技伦理学》课程，撰写论文《AI决策中的公平性陷阱》，奠定对技术伦理的关注。
- 技能突破：用Python复现经典机器学习算法（如KNN、决策树），GitHub获超100星。
9. 2022年（19岁，大二）：
- 加入教授实验室参与NLP方向课题，首次接触真实科研流程。
- 经济独立尝试：接洽外包项目开发小型企业管理系统，赚取第一笔技术收入（2万元）。
10. 2023年（20岁，大三上）：
- 职业启蒙：在某科技公司暑期实习期间参与AI客服系统优化，发现工业界与学术界的巨大差异。
- 理想深化：实习主管因其提出的"老年人语音交互易用性改进方案"予以嘉奖，明确AI需服务弱势群体的信念。
11. 2023年末（20岁，大三下）：
- 挑战事件：主导的课程项目（基于深度学习的垃圾分类系统）因数据集偏差导致演示失败，连续48小时重构代码终获成功。
- 人际成长：首次作为队长带队参与黑客马拉松，协调5人团队开发"AR校园导航"应用获三等奖。
12. 2024年（21岁）：
- 以第一作者身份完成论文《基于迁移学习的低资源方言识别模型》，投稿至国际学术会议。
- 重大失去：祖父因病去世，其临终前无法操作智能医疗设备的问题，促使XXX将研究方向聚焦"适老化AI交互"。
13. 2024年中（当前）：
- 十字路口：收到美国TOP30大学AI硕博全奖offer vs. 国内头部AI企业研究岗offer，陷入深造与实战的选择困境。

以下是角色信息：
{full_formatted_text}

请以 JSON 数组形式输出所有事件。
"""
        messages = [{"role": "user", "content": prompt}]
        response = self.client.call_api(
            messages=messages,
            temperature=0.6,
            top_p=0.95,
            max_tokens=10000
        )

        if not response or 'choices' not in response:
            raise Exception("大模型响应失败，无法生成生平事件")

        content = response['choices'][0]['message'].get('content', '')
        content = content.strip().replace('\ufeff', '')

        print("💡💡 接收到的原始响应内容：")
        print(content)
        start_index = content.find("[")
        end_index = content.rfind("]")

        if start_index != -1 and end_index != -1 and end_index > start_index:
            json_content = content[start_index:end_index + 1].strip()
        else:
            print("❌❌ 未找到有效的 JSON 数组结构（[...]）")
            json_content = ""

        if json_content:
            try:
                # 解析JSON并添加版本号
                events_data = json.loads(json_content)
                events_with_version = {
                    "version": "1.0",
                    "events": events_data
                }
                event_json = json.dumps(events_with_version, ensure_ascii=False, indent=2)

                # 存入数据库
                with self.db as db:
                    success = db.insert_agent_life_event(
                        user_id=self.user_id,
                        agent_id=agent_id,
                        event_json=event_json
                    )
                    if success:
                        print(f"✅ 智能体生平事件已成功存入数据库（agent_id: {agent_id}）")
                    else:
                        print(f"❌ 智能体生平事件存入数据库失败（agent_id: {agent_id}）")
            except json.JSONDecodeError as e:
                print(f"❌ JSON解析错误，无法处理生平事件数据：{e}")
            except Exception as e:
                print(f"❌ 处理生平事件时发生异常：{e}")

        return json_content

    def _generate_global_event_id(self, user_id: int, agent_id: int, event_json: str) -> str:
        """
        :param user_id: 所属用户ID（必须在users表存在，满足外键约束）
        :param agent_id: 关联智能体ID（必须在agents表存在）
        :param event_json: 事件内容（JSON字符串，满足event_json字段类型）
        :return: 6位event_id，失败返回空
        """
        try:
            with self.db as db_conn:
                # 关键：插入SQL包含user_id字段，与表结构完全对齐
                insert_sql = """
                             INSERT INTO global_event_counter (user_id, agent_id, event_json)
                             VALUES (%s, %s, %s) \
                             """
                # 传入3个参数：user_id（来自self.user_id）、agent_id、event_json
                db_conn._execute_update(insert_sql, (user_id, agent_id, event_json))

                # 获取自增ID并格式化为6位
                get_id_sql = "SELECT LAST_INSERT_ID()"
                result = db_conn._execute_query(get_id_sql)
                if not result or "LAST_INSERT_ID()" not in result[0]:
                    print("❌ 无法获取自增ID（可能表结构错误）")
                    return ""

                raw_id = result[0]["LAST_INSERT_ID()"]
                global_event_id = str(raw_id).zfill(6)
                print(f"✅ 生成全局issue_id: {global_event_id}（user_id: {user_id}, agent_id: {agent_id}）")
                return global_event_id

        except Exception as e:
            # 捕获外键错误（如user_id/agent_id在关联表不存在）
            if "foreign key constraint fails" in str(e).lower():
                print(f"❌ 外键约束错误：请确保user_id={user_id}在users表、agent_id={agent_id}在agents表存在")
            else:
                print(f"❌ 生成全局event_id失败: {str(e)}")
            return ""

    def generate_agent_goals(self, full_formatted_text: str, life_events: str, agent_name: str, agent_id: int) -> str:
        prompt = f"""
以下是一位虚构角色的完整信息和其人生历程，请基于此信息，生成出该角色的完整生命周期的长期目标与短期目标。

角色完整信息：
{full_formatted_text}

角色生平事件：
{life_events}

请以 JSON 数组形式输出所有目标。
"""
        messages = [{"role": "user", "content": prompt}]
        response = self.client.call_api(
            messages=messages,
            temperature=0.6,
            top_p=0.9,
            max_tokens=1000
        )

        if not response or 'choices' not in response:
            raise Exception("大模型响应失败，无法生成角色目标")

        content = response['choices'][0]['message'].get('content', '')
        content = content.strip().replace('\ufeff', '')

        print("💡💡 接收到的原始响应内容：")
        print(content)
        start_index = content.find("[")
        end_index = content.rfind("]")

        if start_index != -1 and end_index != -1 and end_index > start_index:
            json_content = content[start_index:end_index + 1].strip()
        else:
            print("❌❌ 未找到有效的 JSON 数组结构（[...]）")
            json_content = ""

        if json_content:
            try:
                goals_data = json.loads(json_content)
                goals_with_version = {
                    "version": "1.0",
                    "goals": goals_data
                }
                goals_json = json.dumps(goals_with_version, ensure_ascii=False, indent=2)
                with self.db as db:
                    goal_id = db.insert_agent_goal(
                        user_id=self.user_id,
                        agent_id=agent_id,
                        goals_json=goals_json
                    )
                if goal_id:
                    print(f"✅ 智能体目标已成功存入数据库（goal_id: {goal_id}, agent_id: {agent_id}）")
                else:
                    print(f"❌ 智能体目标存入数据库失败（agent_id: {agent_id}）")
            except json.JSONDecodeError as e:
                print(f"❌ JSON 解析错误，无法处理目标数据：{e}")
            except Exception as e:
                print(f"❌ 处理目标数据时发生异常：{e}")

        return json_content

    def generate_agent_schedule(self, agent_profile: dict, agent_id: int) -> dict:
        """生成智能体的日程表"""
        try:
            basic_info = {
                "姓名": agent_profile.get("姓名", "未知"),
                "年龄": agent_profile.get("年龄", 0),
                "职业": agent_profile.get("职业", "自由职业"),
                "爱好": agent_profile.get("爱好", []),
                "教育背景": agent_profile.get("教育背景", ""),
                "家庭背景": agent_profile.get("家庭背景", "")
            }
            from schedule_generator import generate_agent_schedule
            schedule = generate_agent_schedule(basic_info, self.client.api_key)

            # 转换为JSON字符串
            schedule_json = json.dumps(schedule, ensure_ascii=False)

            # 存入数据库
            with self.db as db:
                schedule_id = db.insert_agent_daily_schedule(
                    user_id=self.user_id,
                    agent_id=agent_id,
                    schedule_json=schedule_json
                )
                if schedule_id:
                    print(f"✅ 智能体时间表已成功存入数据库（schedule_id: {schedule_id}）")
                else:
                    print(f"❌❌ 智能体时间表存入数据库失败")

            return schedule

        except Exception as e:
            print(f"❌❌ 生成日程表失败: {str(e)}")
            return {}

    def build_agent(self, user_input: str) -> Dict[str, Any]:
        print(f"开始构建智能体，使用模板文件: templates/templates.json")
        try:
            completed_info_text = self.complete_user_input(user_input)
            name = "unknown"  # 默认值
            for line in completed_info_text.splitlines():
                if line.startswith("姓名："):
                    try:
                        name = line.split("：", 1)[1].strip()  # 更安全地提取
                        if name:  # 确保不为空
                            break
                    except IndexError:
                        continue

            agent_state_text = self.generate_agent_properties(completed_info_text)
            agent_profile_dict, agent_id = self.format_agent_full_info(completed_info_text, agent_state_text, name)
            # 确保 agent_profile_dict 是字典类型
            if not isinstance(agent_profile_dict, dict):
                print(f"⚠️ agent_profile_dict 不是字典类型，而是 {type(agent_profile_dict)}")
                try:
                    # 尝试将其解析为字典
                    agent_profile_dict = json.loads(agent_profile_dict)
                except Exception as e:
                    print(f"❌❌ 无法将 agent_profile_dict 转换为字典: {e}")
                    agent_profile_dict = {"姓名": name}  # 创建基本字典作为备用

            # 生成并存储日程表（传入agent_id）
            schedule = self.generate_agent_schedule(agent_profile_dict, agent_id)  # 添加agent_id参数

            life_event_text = self.generate_life_events(agent_profile_dict, name, agent_id)
            agent_goals = self.generate_agent_goals(agent_profile_dict, life_event_text, name, agent_id)

            # 准备返回数据
            agent_data = {
                "生平事件记录": life_event_text,
                "目标": agent_goals,
                "智能体信息": agent_profile_dict,
                "agent_id": agent_id,
                "agent_name": name,
                "schedule": schedule,
                "user_id": self.user_id
            }

            if agent_id:
                print(f"🔗 开始生成事件链 (agent_id: {agent_id})")
                generator = EventTreeGenerator(
                    agent_name=name,  # 1. 智能体名称
                    api_key=self.client.api_key,  # 2. API密钥
                    agent_id=agent_id,  # 3. 智能体ID
                    user_id=self.user_id,  # 4. 用户ID（符合表结构要求）
                    agent_builder=self  # 5. 新增：传递 AgentBuilder 实例（解决参数缺失错误）
                )
                full_event_tree = generator.generate_and_save()
            generator.generate_and_save()

            return agent_data

        except Exception as e:
            print(f"❌❌❌❌ 智能体构建失败：{str(e)}")
            return None


if __name__ == "__main__":
    builder = AgentBuilder(api_key="sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV")
    user_input = """
世界观：现实世界
姓名：萧炎
年龄：16
职业：高中生
爱好：音乐、吉他
"""
    agent = builder.build_agent(user_input)