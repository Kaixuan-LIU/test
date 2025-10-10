import json
import random
from datetime import datetime
from api_handler import ChatFireAPIClient


def generate_agent_schedule(agent_profile: dict, api_key: str) -> dict:
    """生成智能体的日程表"""
    try:
        # 构建提示词
        prompt = f"""
请根据以下角色信息，为其生成一个合理的周日程表。
角色信息：
{json.dumps(agent_profile, ensure_ascii=False, indent=2)}

请以JSON格式输出，包含以下字段：
- 周一：包含多个时间段，每个时间段有start_time、end_time、activity、status
- 周二：同上
- ...
- 周日：同上

示例格式：
{{
  "周一": [
    {{
      "start_time": "09:00",
      "end_time": "12:00",
      "activity": "工作",
      "status": "忙碌"
    }},
    {{
      "start_time": "12:00",
      "end_time": "13:00",
      "activity": "午餐",
      "status": "空闲"
    }}
  ],
  "周二": [...]
}}
"""

        # 调用API生成日程表
        client = ChatFireAPIClient(api_key=api_key)
        response = client.call_api([{"role": "user", "content": prompt}])
        content = response['choices'][0]['message']['content']

        # 添加调试信息
        print(f"🔍 接收到的原始响应内容：")
        print(content)
        
        # 提取JSON内容
        start_index = content.find("{")
        end_index = content.rfind("}")
        if start_index != -1 and end_index != -1 and end_index > start_index:
            json_content = content[start_index:end_index + 1].strip()
            
            # 添加调试信息
            print(f"🔍 提取的JSON内容：")
            print(json_content)
            
            # 尝试解析JSON
            try:
                schedule = json.loads(json_content)
                return schedule
            except json.JSONDecodeError as e:
                print(f"❌ JSON解析失败: {e}")
                print(f"❌ 错误位置: line {e.lineno}, column {e.colno}")
                print(f"❌ 错误字符: {e.msg}")
                return generate_default_schedule()
        else:
            print("❌ 未找到有效的 JSON 对象结构")
            return generate_default_schedule()
    except Exception as e:
        print(f"❌ 生成日程表失败: {e}")
        return generate_default_schedule()


def generate_default_schedule(agent_profile: dict) -> dict:
    """生成默认的周日程表"""
    name = agent_profile.get("姓名", "智能体")
    occupation = agent_profile.get("职业", "自由职业")
    hobbies = agent_profile.get("爱好", ["阅读"])

    # 基础模板
    base_schedule = {
        "工作日": [
            {"start_time": "07:00", "end_time": "08:00", "activity": "晨间准备", "status": "一般忙碌"},
            {"start_time": "08:00", "end_time": "12:00", "activity": occupation, "status": "忙碌"},
            {"start_time": "12:00", "end_time": "13:00", "activity": "午餐", "status": "空闲"},
            {"start_time": "13:00", "end_time": "17:00", "activity": occupation, "status": "忙碌"},
            {"start_time": "17:00", "end_time": "18:00", "activity": "通勤/休息", "status": "一般忙碌"},
            {"start_time": "18:00", "end_time": "19:00", "activity": "晚餐", "status": "空闲"},
            {"start_time": "19:00", "end_time": "21:00", "activity": hobbies[0], "status": "一般忙碌"},
            {"start_time": "21:00", "end_time": "23:00", "activity": "个人时间", "status": "空闲"}
        ],
        "周末": [
            {"start_time": "08:00", "end_time": "09:00", "activity": "早餐", "status": "空闲"},
            {"start_time": "09:00", "end_time": "12:00", "activity": "个人爱好", "status": "一般忙碌"},
            {"start_time": "12:00", "end_time": "13:00", "activity": "午餐", "status": "空闲"},
            {"start_time": "13:00", "end_time": "17:00", "activity": "社交/休闲", "status": "一般忙碌"},
            {"start_time": "17:00", "end_time": "19:00", "activity": "晚餐", "status": "空闲"},
            {"start_time": "19:00", "end_time": "22:00", "activity": "娱乐", "status": "空闲"}
        ]
    }

    return {
        "周一": base_schedule["工作日"],
        "周二": base_schedule["工作日"],
        "周三": base_schedule["工作日"],
        "周四": base_schedule["工作日"],
        "周五": base_schedule["工作日"],
        "周六": base_schedule["周末"],
        "周日": base_schedule["周末"]
    }


def check_current_status(schedule: list) -> dict:
    now = datetime.now()
    current_day = now.strftime("%A")  # 获取星期几（英文）

    # 将英文星期转换为中文
    weekdays_en_to_cn = {
        "Monday": "星期一",
        "Tuesday": "星期二",
        "Wednesday": "星期三",
        "Thursday": "星期四",
        "Friday": "星期五",
        "Saturday": "星期六",
        "Sunday": "星期日"
    }
    weekday_cn = weekdays_en_to_cn.get(current_day, "")

    current_hour = now.hour
    current_minute = now.minute

    # 查找匹配的时间段
    for item in schedule:
        if item["day"] == weekday_cn:
            start_time = item["start_time"].split(":")
            end_time = item["end_time"].split(":")

            start_hour, start_minute = map(int, start_time)
            end_hour, end_minute = map(int, end_time)

            # 将时间转换为分钟数进行比较
            current_total_minutes = current_hour * 60 + current_minute
            start_total_minutes = start_hour * 60 + start_minute
            end_total_minutes = end_hour * 60 + end_minute

            # 判断当前时间是否在某个事件时间范围内
            if start_total_minutes <= current_total_minutes < end_total_minutes:
                return {
                    "current_time": now.strftime("%Y-%m-%d %H:%M"),
                    "day": weekday_cn,
                    "current_activity": item["activity"],
                    "status": item["status"]
                }

    # 如果没有找到匹配项，返回默认值
    return {
        "current_time": now.strftime("%Y-%m-%d %H:%M"),
        "day": weekday_cn,
        "current_activity": "无安排",
        "status": "空闲"
    }