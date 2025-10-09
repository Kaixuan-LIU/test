import json
import random
from datetime import datetime
from api_handler import ChatFireAPIClient


def generate_agent_schedule(agent_profile: dict, api_key: str) -> dict:
    client = ChatFireAPIClient(api_key=api_key)

    prompt = f"""
请根据以下智能体信息生成完整的周日程表（周一到周日）：
{json.dumps(agent_profile, ensure_ascii=False, indent=2)}

要求：
1. 按每日24h安排事件
2. 包含工作日和周末的不同安排
3. 白天每个事件持续时间0.5-3小时，夜晚可以安排长时间睡眠时间
4. 事件内容符合智能体的职业、爱好和个人特点
5. 为每个时间段分配状态标签："空闲"/"一般忙碌"/"忙碌"，睡眠时间为忙碌
6. 返回JSON格式：键为星期几，值为该天的日程列表
7. 示例格式：
{{
  "周一": [
    {{"start_time": "07:30", "end_time": "08:00", "activity": "晨练", "status": "一般忙碌"}},
    {{"start_time": "08:00", "end_time": "09:00", "activity": "早餐", "status": "空闲"}},
    ...
  ],
  "周二": [...],
  ...
}}
"""

    try:
        response = client.call_api(
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=3000
        )
        content = response["choices"][0]["message"]["content"]

        # JSON提取
        if content.strip().startswith("{"):
            return json.loads(content)
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1:
            return json.loads(content[start_idx:end_idx + 1])

    except Exception as e:
        print(f"⚠️ 日程生成错误: {e}")

    return generate_default_schedule(agent_profile)


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