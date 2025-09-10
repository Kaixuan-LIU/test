from linecache import cache
from flask import Flask, request, jsonify, send_file, session
from flask_cors import CORS
import secrets
import uuid
import os
from PIL import Image, ImageDraw, ImageFont
import io
import json
import random
from datetime import datetime
from Agent_builder import AgentBuilder
from database import DB_CONFIG, MySQLDB
from event_loop_tool import run_event_loop, get_intro_event
from daily_loop_tool import run_daily_loop

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 安全设置密钥
if 'FLASK_SECRET_KEY' in os.environ:
    app.secret_key = os.environ['FLASK_SECRET_KEY']  # 生产环境从环境变量获取
else:
    app.secret_key = secrets.token_hex(32)  # 开发环境生成随机密钥
    print("开发环境使用随机生成的密钥:", app.secret_key)

# 确保头像目录存在
if not os.path.exists('avatars'):
    os.makedirs('avatars')

# 一、头像接口 - 生成智能体头像
@app.route('/api/avatar', methods=['GET'])
def generate_avatar():
    agent_id = request.args.get('agent_id')
    if not agent_id:
        return jsonify({"error": "agent_id is required"}), 400

    # 生成简单的头像
    image = Image.new('RGB', (200, 200), color=get_random_color(agent_id))
    draw = ImageDraw.Draw(image)

    # 从agent_id中取前两个字符作为头像初始字母
    initials = agent_id[:2].upper() if agent_id else "?"

    # 确保中文显示正常
    try:
        font = ImageFont.truetype("simhei.ttf", 80)
    except IOError:
        # 如果找不到中文字体，使用默认字体
        font = ImageFont.load_default()

    draw.text((70, 60), initials, fill=(255, 255, 255), font=font)

    # 将图像转为字节流并返回
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)

    return send_file(img_byte_arr, mimetype='image/png')


def get_random_color(seed):
    """根据seed生成固定的随机颜色"""
    random.seed(seed)
    return (random.randint(50, 200), random.randint(50, 200), random.randint(50, 200))


#智能体接口
@app.route('/V1/agents', methods=['POST'])
def get_agent():
    # 获取请求体中的user_input参数
    data = request.json
    user_input = data.get('data', '')

    if not user_input:
        return jsonify({"error": "Missing 'user_input' parameter"}), 400

    try:
        # 创建AgentBuilder实例
        builder = AgentBuilder(api_key='sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV')
        # 通过实例调用方法
        agent_data = builder.build_agent(user_input)

        # 从agent_data中获取formatted_text
        formatted_text = agent_data.get("智能体信息", {})

        # 映射formatted_text字段到API响应字段
        response_data = {
            "user_id": agent_data["user_id"],
            "agent_id": agent_data["agent_id"],
            "agent_name": str(formatted_text.get("姓名", "")),
            "age": str(formatted_text.get("年龄", "")),
            "career": str(formatted_text.get("职业", "")),
            "country": str(formatted_text.get("国家地区", "")),
            "skill": str(formatted_text.get("个人技能", "")),
            "appearance": str(formatted_text.get("外貌", "")),
            "hobby": str(formatted_text.get("爱好", "")),
            "voice": str(formatted_text.get("声音", "")),
            "relation": str(formatted_text.get("与玩家关系", "")),
            "mbti": str(formatted_text.get("MBTI类型", "")),
            "icon_url": str(formatted_text.get("头像URL", ""))
        }

        return jsonify(response_data), 200

    except Exception as e:
        # 错误处理
        return jsonify({"error": f"Failed to build agent: {str(e)}"}), 500

# 三、对话接口 - 从memory文件夹下的Agentname文本文件中读取内容
# 三、对话接口 - 从memory文件夹下的Agentname文本文件中读取内容
"""
日常对话接口：
请求体：{"agent_id": "string", "content": "string", "user_id": "string", "session_id": "string(可选)"}
返回：{
    "agent_id": "string",
    "content": "string",
    "session_id": "string",
    "waiting_for_input": bool,
    "status": "string(active/ended)"
}
"""


@app.route('/api/daily', methods=['POST'])
def get_conversation():
    """
    日常对话接口：
    请求体：{"agent_id": "string", "content": "string", "user_id": "string", "session_id": "string(可选)"}
    返回：{
        "agent_id": "string",
        "content": "string",
        "session_id": "string",
        "waiting_for_input": bool,
        "status": "string(active/ended)"
    }
    """
    # 解析请求参数
    req_data = request.json
    agent_id = req_data.get("agent_id")
    content = req_data.get("content")
    user_id = req_data.get("user_id")
    session_id = req_data.get("session_id")

    # 验证必填参数
    if not all([agent_id, user_id]):
        return jsonify({"error": "缺少必填参数：agent_id 或 user_id"}), 400

    # 初始化或获取会话状态
    session_key = f'daily_{session_id}'
    session_data = (session.get(session_key, {})
                    or {
                        'conversation_counter': 0,
                        'pending_messages': [],
                        'waiting_for_input': True,
                        'initialized': False,
                        'agent_id': agent_id,
                        'user_id': user_id
                    })

    # 生成新会话ID（如果不存在）
    if not session_id:
        session_id = str(uuid.uuid4())
    try:
        # 正确使用数据库连接 - 使用 with 语句
        with MySQLDB(**DB_CONFIG) as db:
            # 在 with 块内执行所有数据库操作
            agent_data = db.get_agent_by_id(agent_id)
            goals_data = db.get_agent_goals(agent_id)
            events_data = db.get_agent_event_chains(agent_id)

            messages, name, new_session_data, session_id = run_daily_loop(
                agent_profile=json.loads(agent_data['full_json']),
                goals=json.loads(goals_data[0]['goals_json']),
                event_tree=json.loads(events_data[0]['chain_json']),
                agent_id=int(agent_id),
                user_id=int(user_id),
                user_input=content,
                session_id=session_id
            )


            dialog_json = {
                "dialog_history": messages,
                "session_data": new_session_data
            }

            # 检查会话是否已存在
            existing = db._execute_query(
                "SELECT * FROM dialogs WHERE session_id = %s",
                (session_id,)
            )

            if existing:
                # 更新现有会话
                db._execute_update(
                    """UPDATE dialogs
                       SET dialog_json = %s,
                           status      = %s,
                           updated_at  = NOW()
                       WHERE session_id = %s""",
                    (json.dumps(dialog_json, ensure_ascii=False),
                     "ended" if new_session_data.get('exit_requested') else "active",
                     session_id)
                )
            else:
                # 创建新会话
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                db._execute_update(
                    """INSERT INTO dialogs (session_id, user_id, agent_id, status,
                                            start_time, dialog_json, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())""",
                    (session_id, int(user_id), int(agent_id),
                     "active", current_time, json.dumps(dialog_json, ensure_ascii=False))
                )

        # 更新会话状态到缓存
        session[session_key] = new_session_data
        session.permanent = True

        # 获取最后一条AI回复
        ai_replies = [msg['content'] for msg in messages if msg['role'] == 'assistant']
        last_reply = ai_replies[-1] if ai_replies else "（暂时无法回复）"

        # 构造响应
        response = {
            "agent_id": agent_id,
            "content": last_reply,
            "session_id": session_id,
            "waiting_for_input": new_session_data.get('waiting_for_input', True),
            "status": "ended" if new_session_data.get('exit_requested') else "active"
        }

        return jsonify(response), 200

    except json.JSONDecodeError as e:
        return jsonify({"error": f"JSON解析失败：{str(e)}"}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"日常交互异常：{str(e)}"}), 500


# 四、事件接口
# 修改 Api.py 中 event 接口的实现，确保每次调用只处理一轮交互并返回
# Api.py 中 /api/event 接口的完整修改代码
@app.route('/api/event', methods=['POST'])
def event():
    """
    事件对话接口：基于dialogs表的会话管理
    请求体：{"agent_id": "string", "issue_id": "string"（可为空）, "content": "string", "user_id": "string", "session_id": "string"（可选）}
    返回：{"agent_id": "string", "issue_id": "string", "content": "string", "session_id": "string", "is_ended": bool, "status": string}
    """
    # 1. 解析请求参数
    req_data = request.json
    agent_id = req_data.get("agent_id")
    user_id = req_data.get("user_id")
    content = req_data.get("content")
    issue_id = req_data.get("issue_id")
    session_id = req_data.get("session_id")

    # 2. 验证必填参数
    if not all([agent_id, content, user_id]):
        return jsonify({"error": "缺少必填参数（agent_id/content/user_id）"}), 400

    try:
        with MySQLDB(**DB_CONFIG) as db:
            # 加载事件链数据
            events_data = db.get_agent_event_chains(agent_id)
            if not events_data:
                return jsonify({"error": f"未找到agent_id={agent_id}的事件链数据"}), 500
            chain_json = events_data[0]['chain_json']
            event_tree = json.loads(chain_json).get('event_tree', [])
            if not event_tree:
                return jsonify({"error": f"agent_id={agent_id}的事件链数据为空"}), 500

            # 初始化issue_id
            if not issue_id:
                intro_event = get_intro_event(event_tree)
                issue_id = intro_event["event_id"] if intro_event else f"EVT_{uuid.uuid4()}"

        # 调用事件循环处理
        event_result = run_event_loop(
            user_id=int(user_id),
            agent_id=int(agent_id),
            event_id=issue_id,
            user_input=content,
            session_id=session_id,
            event_tree=event_tree
        )

        # 构造响应
        return jsonify({
            "agent_id": agent_id,
            "issue_id": event_result["issue_id"],
            "content": event_result["content"],
            "session_id": event_result["session_id"],
            "is_ended": event_result["is_ended"],
            "status": event_result["event_status"]
        }), 200

    except json.JSONDecodeError as e:
        return jsonify({"error": f"会话数据解析失败：{str(e)}"}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"事件处理失败：{str(e)}"}), 500

# 增量事件查询接口（供 APP 定时轮询）
@app.route('/api/v1/events', methods=['GET'])
def list_events():
    # 1. 获取请求参数
    last_event_id = request.args.get('last_event_id')  # 新格式：6位数字字符串（如"000003"）
    limit = request.args.get('limit', type=int, default=20)

    # 2. 参数校验
    if not last_event_id:
        return jsonify({"code": 400, "msg": "last_event_id is required (format: '000000'-'999999')"}), 400
    try:
        # 解析为整数（忽略前导零）
        last_event_num = int(last_event_id)
        if last_event_num < 0 or last_event_num > 999999:
            raise ValueError("超出范围")
    except ValueError:
        return jsonify({"code": 400, "msg": "last_event_id format error (expected 6-digit number)"}), 400

    if limit < 1 or limit > 100:
        return jsonify({"code": 400, "msg": "limit must be between 1 and 100"}), 400

        # 3. 数据库查询：获取所有智能体的事件（按全局编号升序）
    try:
        with MySQLDB(**DB_CONFIG) as db:
            # 查询全局事件表，过滤编号大于last_event_num的事件
            events = db.get_events_after(last_event_num, limit)
    except Exception as e:
        return jsonify({"code": 500, "msg": f"Server error: {str(e)}"}), 500

        # 4. 格式化返回（事件中包含全局event_id）
    return_events = [
        {
            "event_id": event['global_event_id'],  # 6位数字字符串
            "agent_id": event['agent_id'],
            "name": event['name'],
            "type": event["type"],
            "tags": json.loads(event["tags"]),
            "time": event["time"],
            "location": event["location"],
            "cause": event["cause"],
            "characters": json.loads(event["characters"])
        } for event in events
    ]

    # 5. 判断是否有更多数据（基于查询结果是否达到limit）
    has_more = len(return_events) == limit
    return jsonify({
        "events": return_events,
        "has_more": has_more
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)