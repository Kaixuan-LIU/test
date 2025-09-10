import datetime

import pymysql
from pymysql import MySQLError
from typing import Dict, List, Optional, Any
import json
from app_config import config


class MySQLDB:
    def __init__(self, host: str, user: str, password: str, database: str, port: int = 3306, charset: str = 'utf8mb4', test_mode=False,**kwargs):
        """初始化数据库连接参数"""
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.port = port
        self.charset = charset
        self.test_mode = test_mode
        self.connection = None  # 仅初始化变量，不在__init__中创建连接
        self.kwargs = kwargs

    def __enter__(self):
        """上下文管理器进入时创建连接"""
        try:
            self.connection = pymysql.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database,
                port=self.port,
                charset=self.charset,
                cursorclass=pymysql.cursors.DictCursor
            )
            return self
        except MySQLError as e:
            print(f"数据库连接失败: {e}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出时关闭连接"""
        if self.connection:
            self.connection.close()

    def _execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """执行查询并返回字典格式结果"""
        with self.connection.cursor() as cursor:
            try:
                cursor.execute(query, params or ())
                result = cursor.fetchall()
                return result
            except MySQLError as e:
                print(f"查询执行失败: {e}")
                raise

    def _execute_update(self, query: str, params: tuple = None) -> int:
        """执行插入/更新/删除操作并返回影响行数"""
        with self.connection.cursor() as cursor:
            try:
                cursor.execute(query, params or ())
                self.connection.commit()
                return cursor.rowcount
            except MySQLError as e:
                self.connection.rollback()
                print(f"更新操作失败: {e}")
                raise

    def _format_query(self, query: str) -> str:
        """替换SQL中的{table}为实际表名"""
        if not hasattr(self, 'current_table'):
            return query
        return query.replace('{table}', self.current_table)

    # ------------------------------ 模板表操作 ------------------------------
    def get_template_by_type_key(self, template_type: str, template_key: str, version: str = '1.0') -> Optional[Dict]:
        """根据类型、键名和版本获取模板"""
        self.current_table = "test_templates" if self.test_mode else "templates"
        query = """
            SELECT template_id, template_type, template_key, content_json, version, is_active, created_at, updated_at
            FROM {table} 
            WHERE template_type = %s AND template_key = %s AND version = %s AND is_active = TRUE
        """
        query = self._format_query(query)
        result = self._execute_query(query, (template_type, template_key, version))
        return result[0] if result else None

    def get_active_templates_by_type(self, template_type: str) -> List[Dict]:
        """获取指定类型的所有活跃模板"""
        self.current_table = "test_templates" if self.test_mode else "templates"
        query = """
            SELECT template_id, template_type, template_key, content_json, version, is_active, created_at, updated_at
            FROM {table} 
            WHERE template_type = %s AND is_active = TRUE
        """
        query = self._format_query(query)
        return self._execute_query(query, (template_type,))

    def get_active_mbti_templates(self) -> List[Dict]:
        """获取所有活跃的MBTI模板"""
        self.current_table = "test_templates" if self.test_mode else "templates"
        query = """
               SELECT template_id, template_type, template_key, content_json, version, is_active, created_at, updated_at
               FROM {table} 
               WHERE template_type = 'mbti' AND is_active = TRUE
           """
        query = self._format_query(query)
        return self._execute_query(query)

    def get_agent_daily_schedules(self, agent_id: int) -> List[Dict]:
        """获取指定智能体的所有日常时间表（按更新时间倒序）"""
        self.current_table = "test_agent_schedules" if self.test_mode else "agent_schedules"
        query = """
                SELECT schedule_id, user_id, agent_id, schedule_json, created_at, updated_at
                FROM {table}
                WHERE agent_id = %s
                ORDER BY updated_at DESC \
                """
        query = self._format_query(query)
        return self._execute_query(query, (agent_id,))

    # ------------------------------ 用户表操作 ------------------------------
    def get_user_by_phone(self, phone: str) -> Optional[Dict]:
        """通过手机号获取用户信息"""
        self.current_table = "test_users" if self.test_mode else "users"
        query = """
            SELECT user_id, phone, password_hash, nickname, avatar_url, gender, birthday, signature,
                   region, interests, is_verified, status, last_login_ip, last_login_time,
                   created_at, updated_at
            FROM {table}
            WHERE phone = %s
        """
        query = self._format_query(query)
        result = self._execute_query(query, (phone,))
        return result[0] if result else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """通过用户ID获取用户信息"""
        self.current_table = "test_users" if self.test_mode else "users"
        query = """
            SELECT user_id, phone, password_hash, nickname, avatar_url, gender, birthday, signature,
                   region, interests, is_verified, status, last_login_ip, last_login_time,
                   created_at, updated_at
            FROM {table}
            WHERE user_id = %s
        """
        query = self._format_query(query)
        result = self._execute_query(query, (user_id,))
        return result[0] if result else None

    # ------------------------------ 智能体表操作 ------------------------------
    def get_agent_by_id(self, agent_id: int) -> Optional[Dict]:
        """通过agent_id获取智能体信息"""
        self.current_table = "test_agents" if self.test_mode else "agents"
        query = """
            SELECT agent_id, user_id, agent_name, full_json, created_at, updated_at
            FROM {table} 
            WHERE agent_id = %s
        """
        query = self._format_query(query)
        result = self._execute_query(query, (agent_id,))
        return result[0] if result else None

    def insert_agent(self, user_id: int, agent_name: str, full_json: str) -> Optional[int]:
        """插入智能体并返回自增ID"""
        self.current_table = "test_agents" if self.test_mode else "agents"
        try:
            # 从完整JSON中提取基础属性
            full_data = json.loads(full_json)
            basic_attrs = json.dumps(full_data.get("基础属性", {}))

            insert_sql = """
                INSERT INTO {table} (user_id, agent_name, full_json, base_attributes)
                VALUES (%s, %s, %s, %s)
                """
            insert_sql = self._format_query(insert_sql)
            self._execute_update(insert_sql, (user_id, agent_name, full_json, basic_attrs))
            # 获取自增ID
            result = self._execute_query("SELECT LAST_INSERT_ID()")
            return result[0]['LAST_INSERT_ID()'] if result else None
        except MySQLError as e:
            print(f"插入智能体失败: {e}")
            return None

    def get_agent(self, agent_id: int) -> List[Dict]:
        """获取智能体"""
        self.current_table = "test_agents" if self.test_mode else "agents"
        query = """
            SELECT agent_id, user_id, agent_name, full_json, created_at, updated_at
            FROM {table} 
            WHERE agent_id = %s  -- 去掉多余的AND
            ORDER BY created_at DESC
        """
        query = self._format_query(query)
        return self._execute_query(query, (agent_id,))

    def get_agents_by_mbti(self, mbti_type: str) -> List[Dict]:
        """通过MBTI类型筛选智能体"""
        self.current_table = "test_agents" if self.test_mode else "agents"
        query = """
            SELECT agent_id, user_id, template_id, name, age, birthday, worldview, education,
                   family_background, occupation, country_region, mbti_type, psychological_state,
                   ideal, hobbies, voice_desc, skills, knowledge_system, relationship_with_user,
                   status_tags, feature_tags, experience_tags, relationship_tags, avatar_url,
                   is_active, created_at, updated_at
            FROM {table} 
            WHERE mbti_type = %s AND is_active = TRUE
        """
        query = self._format_query(query)
        return self._execute_query(query, (mbti_type,))

    # ------------------------------ 智能体生平事件表操作 ------------------------------
    def insert_agent_life_event(self, user_id: int, agent_id: int, event_json: str) -> bool:
        """
        插入智能体生平事件
        返回值：True表示成功，False表示失败
        """
        self.current_table = "test_agent_life_events" if self.test_mode else "agent_life_events"
        insert_sql = """
        INSERT INTO {table} (user_id, agent_id, event_json)
        VALUES (%s, %s, %s)
        """
        insert_sql = self._format_query(insert_sql)
        try:
            # 执行插入，返回影响行数（1表示成功）
            row_count = self._execute_update(insert_sql, (user_id, agent_id, event_json))
            return row_count == 1
        except MySQLError as e:
            print(f"插入智能体生平事件失败: {e}")
            return False

    def get_agent_life_events(self, agent_id: int) -> List[Dict]:
        """获取指定智能体的所有生平事件（按创建时间倒序）"""
        self.current_table = "test_agent_life_events" if self.test_mode else "agent_life_events"
        query = """
        SELECT user_id, agent_id, event_json, created_at, updated_at
        FROM {table}
        WHERE agent_id = %s
        ORDER BY created_at DESC
        """
        query = self._format_query(query)
        return self._execute_query(query, (agent_id,))

    def get_incremental_events(self, last_event_id, limit):
        MAX_LIMIT = 100
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
        query = """
                SELECT chain_id   AS id,
                       user_id,
                       chain_json AS content,
                       created_at
                FROM agent_event_chains
                WHERE chain_id > %s
                ORDER BY chain_id DESC
                    LIMIT %s
                """
        params = (last_event_id, limit + 1)
        try:
            with self.connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            self.connection.rollback()
            raise e

    # ------------------------------ 智能体目标表操作 ------------------------------
    def insert_agent_goal(self, user_id: int, agent_id: int, goals_json: str) -> Optional[int]:
        """插入智能体目标并返回目标ID"""
        self.current_table = "test_agent_goals_json" if self.test_mode else "agent_goals_json"
        insert_sql = """
        INSERT INTO {table} (user_id, agent_id, goals_json)
        VALUES (%s, %s, %s)
        """
        insert_sql = self._format_query(insert_sql)
        try:
            self._execute_update(insert_sql, (user_id, agent_id, goals_json))
            # 获取自增的goal_id
            result = self._execute_query("SELECT LAST_INSERT_ID()")
            return result[0]['LAST_INSERT_ID()'] if result else None
        except MySQLError as e:
            print(f"插入智能体目标失败: {e}")
            return None

    def get_agent_goals(self, agent_id: int) -> List[Dict]:
        """获取指定智能体的所有目标（按创建时间倒序）"""
        self.current_table = "test_agent_goals_json" if self.test_mode else "agent_goals_json"
        query = """
        SELECT goal_id, user_id, agent_id, goals_json, created_at, updated_at
        FROM {table}
        WHERE agent_id = %s
        ORDER BY created_at DESC
        """
        query = self._format_query(query)
        return self._execute_query(query, (agent_id,))


    # ------------------------------ 智能体事件链表操作 ------------------------------
    def insert_agent_event_chain(self, user_id: int, agent_id: int, chain_json: str) -> Optional[int]:
        """插入智能体事件链并返回chain_id"""
        self.current_table = "test_agent_event_chains" if self.test_mode else "agent_event_chains"
        insert_sql = """
        INSERT INTO {table} (user_id, agent_id, chain_json)
        VALUES (%s, %s, %s)
        """
        insert_sql = self._format_query(insert_sql)
        try:
            self._execute_update(insert_sql, (user_id, agent_id, chain_json))
            # 获取自增ID
            result = self._execute_query("SELECT LAST_INSERT_ID()")
            return result[0]['LAST_INSERT_ID()'] if result else None
        except MySQLError as e:
            print(f"插入智能体事件链失败: {e}")
            return None

    def get_agent_event_chains(self, agent_id: int) -> List[Dict]:
        """获取指定智能体的所有事件链（按创建时间倒序）"""
        self.current_table = "test_agent_event_chains" if self.test_mode else "agent_event_chains"
        query = """
        SELECT chain_id, user_id, agent_id, chain_json, created_at, updated_at
        FROM {table}
        WHERE agent_id = %s
        ORDER BY created_at DESC
        """
        query = self._format_query(query)
        return self._execute_query(query, (agent_id,))

    def get_events_after(self, last_event_num: int, limit: int) -> list:
        """
        查询全局事件表中，编号大于 last_event_num 的前 limit 条事件（按编号升序）
        :param last_event_num: 最后一个已知事件的编号（整数）
        :param limit: 最大返回条数
        :return: 事件字典列表
        """
        MAX_LIMIT = 100  # 限制最大查询条数，避免性能问题
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT

        query = """
                SELECT
                    -- 全局事件编号（格式化6位字符串）
                    LPAD(id, 6, '0')                                 AS global_event_id,
                    -- 智能体ID
                    agent_id,
                    -- 从 event_json 中提取事件字段（需与实际JSON结构匹配）
                    JSON_UNQUOTE(JSON_EXTRACT(event_json, '$.name')) AS name,
                    JSON_UNQUOTE(JSON_EXTRACT(event_json, '$.type')) AS type,
                    JSON_EXTRACT(event_json, '$.tags')               AS tags, -- 数组类型保留JSON格式
                    JSON_UNQUOTE(JSON_EXTRACT(event_json, '$.time')) AS time,
                JSON_UNQUOTE(JSON_EXTRACT(event_json, '$.location')) AS location,
                JSON_UNQUOTE(JSON_EXTRACT(event_json, '$.cause')) AS cause,
                JSON_EXTRACT(event_json, '$.characters') AS characters  -- 数组类型保留JSON格式
                FROM
                    global_event_counter -- 表名修正为实际存在的表名
                WHERE
                    id \
                    > %s -- 主键id作为事件编号判断依据
                ORDER BY
                    id ASC -- 按主键升序，确保时序正确
                    LIMIT %s; \
                """

        params = (last_event_num, limit)
        try:
            with self.connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()  # 返回字典列表，键为上述别名
        except Exception as e:
            self.connection.rollback()
            raise e
    def get_agent_events_by_stage(self, agent_id: int, stage_name: str) -> List[Dict]:
        """获取智能体特定阶段的事件"""
        self.current_table = "test_agent_event_chains" if self.test_mode else "agent_event_chains"
        query = """
            SELECT agent_id, user_id, stage_name, stage_time_range, event_id, event_type,
                   event_name, event_time, location, characters, cause, process, result,
                   impact, importance, urgency, tags, trigger_conditions, dependencies,
                   is_completed, created_at, updated_at
            FROM {table}
            WHERE agent_id = %s AND stage_name = %s 
            ORDER BY importance DESC
        """
        query = self._format_query(query)
        return self._execute_query(query, (agent_id, stage_name))

    def get_uncompleted_events(self, agent_id: int) -> List[Dict]:
        """获取智能体未完成的事件"""
        self.current_table = "test_agent_event_chains" if self.test_mode else "agent_event_chains"
        query = """
            SELECT agent_id, user_id, stage_name, stage_time_range, event_id, event_type,
                   event_name, event_time, location, characters, cause, process, result,
                   impact, importance, urgency, tags, trigger_conditions, dependencies,
                   is_completed, created_at, updated_at
            FROM {table}
            WHERE agent_id = %s AND is_completed = FALSE 
            ORDER BY urgency DESC, importance DESC
        """
        query = self._format_query(query)
        return self._execute_query(query, (agent_id,))

    def generate_global_event_id(self, agent_id: int, event_json: str) -> str:
        """生成全局唯一事件编号（6位数字字符串）"""
        self.current_table = "test_global_event_counter" if self.test_mode else "global_event_counter"
        insert_sql = """
                     INSERT INTO {table} (agent_id, event_json)
                     VALUES (%s, %s) \
                     """
        insert_sql = self._format_query(insert_sql)
        self._execute_update(insert_sql, (agent_id, event_json))
        # 获取自增ID作为全局编号
        result = self._execute_query("SELECT LAST_INSERT_ID()")
        global_id = result[0]['LAST_INSERT_ID()'] if result else 0
        return f"{global_id:06d}"  # 格式化为6位字符串（如1→000001）

    def create_dialog_session(self, session_id: str, user_id: int, agent_id: int, current_event_id: str):
        self.current_table = "test_agent_dialog_memory" if self.test_mode else "agent_dialog_memory"
        insert_sql = """
            INSERT INTO {table} (session_id, user_id, agent_id, current_event_id, dialog_json, event_status)
            VALUES (%s, %s, %s, %s, %s, 'active')
        """
        insert_sql = self._format_query(insert_sql)
        # 初始化空对话历史JSON
        init_dialog = json.dumps([])
        self._execute_update(insert_sql, (session_id, user_id, agent_id, current_event_id, init_dialog))
    def insert_agent_daily_schedule(self, user_id: int, agent_id: int, schedule_json: str) -> Optional[int]:
        """插入智能体日常时间表并返回schedule_id"""
        self.current_table = "test_agent_schedules" if self.test_mode else "agent_schedules"
        insert_sql = """
                     INSERT INTO {table} (user_id, agent_id, schedule_json)
                     VALUES (%s, %s, %s) \
                     """
        insert_sql = self._format_query(insert_sql)
        try:
            self._execute_update(insert_sql, (user_id, agent_id, schedule_json))
            # 获取自增ID
            result = self._execute_query("SELECT LAST_INSERT_ID()")
            return result[0]['LAST_INSERT_ID()'] if result else None
        except MySQLError as e:
            print(f"插入智能体日常时间表失败: {e}")
            return None

#对话历史记忆表操作
    def insert_dialog_memory(self, user_id: int, agent_id: int, dialog_json: str) -> Optional[int]:
        """插入对话历史记忆并返回memory_id"""
        self.current_table = "test_agent_dialog_memory" if self.test_mode else "agent_dialog_memory"
        insert_sql = """
        INSERT INTO {table} (user_id, agent_id, dialog_json)
        VALUES (%s, %s, %s)
        """
        insert_sql = self._format_query(insert_sql)
        try:
            self._execute_update(insert_sql, (user_id, agent_id, dialog_json))
            result = self._execute_query("SELECT LAST_INSERT_ID()")
            return result[0]['LAST_INSERT_ID()'] if result else None
        except MySQLError as e:
            print(f"插入对话历史记忆失败: {e}")
            return None

    def update_dialog_memory(self, session_id: str, new_message: Dict):
        self.current_table = "test_dialogs" if self.test_mode else "dialogs"
        # 1. 查询当前对话历史
        query = "SELECT dialog_json FROM {table} WHERE session_id = %s"
        query = self._format_query(query)
        result = self._execute_query(query, (session_id,))
        if not result:
            raise ValueError(f"会话{session_id}不存在")

        # 2. 追加新消息到历史（保持JSON结构）
        dialog_history = json.loads(result[0]['dialog_json'])
        dialog_history.append(new_message)  # 格式：{"role": "user/agent", "content": "...", "time": "..."}

        # 3. 更新回数据库
        update_sql = """
                     UPDATE {table}
                     SET dialog_json = %s, updated_at = CURRENT_TIMESTAMP
                     WHERE session_id = %s \
                     """
        update_sql = self._format_query(update_sql)
        self._execute_update(update_sql, (json.dumps(dialog_history), session_id))

    def update_session_status(self, session_id: str, status: str):
        self.current_table = "test_agent_dialog_memory" if self.test_mode else "agent_dialog_memory"
        update_sql = """
                     UPDATE {table}
                     SET event_status = %s, updated_at = CURRENT_TIMESTAMP
                     WHERE session_id = %s \
                     """
        update_sql = self._format_query(update_sql)
        self._execute_update(update_sql, (status, session_id))

    # 调整：获取会话详情（包含对话历史和事件信息）
    def get_session_detail(self, event_id: str) -> Optional[Dict]:
        self.current_table = "test_dialogs" if self.test_mode else "dialogs"
        query = """
                SELECT event_id, user_id, agent_id, dialog_json, event_status, created_at
                FROM {table}
                WHERE event_id = %s -- 用 event_id 代替 session_id 作为查询条件 \
                """
        query = self._format_query(query)
        result = self._execute_query(query, (event_id,))  # 传入 event_id 作为参数
        return result[0] if result else None

    # 调整：按用户和智能体查询会话列表（替代原event_session的查询）
    def get_sessions_by_user_agent(self, user_id: int, agent_id: int) -> List[Dict]:
        self.current_table = "test_agent_dialog_memory" if self.test_mode else "agent_dialog_memory"
        query = """
                SELECT session_id, current_event_id, event_status, created_at
                FROM {table}
                WHERE user_id = %s \
                  AND agent_id = %s
                ORDER BY created_at DESC \
                """
        query = self._format_query(query)
        return self._execute_query(query, (user_id, agent_id))

    def update_event_status(self, agent_id: int, event_id: str, status: str) -> int:
        """
        更新 agent_event_chains 表中指定事件的状态（存储在 chain_json 中）
        :param agent_id: 智能体ID（用于定位事件链记录）
        :param event_id: 目标事件ID（如E001）
        :param status: 要更新的状态（成功/失败/未完成等）
        :return: 受影响的行数（1表示成功，0表示未找到记录）
        """
        # 切换测试/正式表
        self.current_table = "test_agent_event_chains" if self.test_mode else "agent_event_chains"

        # 1. 查询该智能体最新的事件链记录（按更新时间倒序取第一条）
        query_chain = """
                      SELECT chain_id, chain_json
                      FROM {table}
                      WHERE agent_id = %s
                      ORDER BY updated_at DESC LIMIT 1 \
                      """
        query_chain = self._format_query(query_chain)
        chain_result = self._execute_query(query_chain, (agent_id,))

        if not chain_result:
            raise ValueError(f"未找到 agent_id={agent_id} 的事件链记录")

        # 提取主键 chain_id 和事件链 JSON
        chain_id = chain_result[0]["chain_id"]
        chain_json = chain_result[0]["chain_json"]
        chain_data = json.loads(chain_json)  # 解析 JSON 为字典
        event_tree = chain_data.get("event_tree", [])  # 事件链核心结构

        # 2. 遍历事件树，定位目标事件并更新状态
        event_updated = False
        for stage in event_tree:
            if isinstance(stage, dict) and "事件列表" in stage:
                for event in stage["事件列表"]:
                    if event.get("event_id") == event_id:
                        # 更新事件状态和时间戳
                        event["status"] = status
                        event["updated_at"] = datetime.datetime.now().isoformat()
                        event_updated = True
                        break
                if event_updated:
                    break

        if not event_updated:
            raise ValueError(f"事件链中未找到 event_id={event_id} 的事件")

        # 3. 将更新后的事件链 JSON 回写数据库
        updated_chain_json = json.dumps(chain_data, ensure_ascii=False)  # 确保中文正常序列化
        update_query = """
                       UPDATE {table}
                       SET chain_json = %s, updated_at = CURRENT_TIMESTAMP
                       WHERE chain_id = %s -- 用主键 chain_id 定位记录，更新更高效 \
                       """
        update_query = self._format_query(update_query)

        # 执行更新并返回受影响的行数（1表示成功）
        return self._execute_update(update_query, (updated_chain_json, chain_id))
    def get_agent_dialog_memories(self, agent_id: int) -> List[Dict]:
        """获取指定智能体的所有对话历史（按时间倒序）"""
        self.current_table = "test_agent_dialog_memory" if self.test_mode else "agent_dialog_memory"
        query = """
        SELECT memory_id, user_id, agent_id, dialog_json, created_at, updated_at
        FROM {table}
        WHERE agent_id = %s
        ORDER BY created_at DESC
        """
        query = self._format_query(query)
        return self._execute_query(query, (agent_id,))

    def get_user_agent_dialogs(self, user_id: int, agent_id: int) -> List[Dict]:
        """获取指定用户与智能体的对话历史（按时间正序，即对话发生顺序）"""
        self.current_table = "test_agent_dialog_memory" if self.test_mode else "agent_dialog_memory"
        query = """
        SELECT memory_id, dialog_json, created_at
        FROM {table}
        WHERE user_id = %s AND agent_id = %s
        ORDER BY created_at ASC
        """
        query = self._format_query(query)
        return self._execute_query(query, (user_id, agent_id))

    def save_agent_dialog_memory(self, user_id: int, agent_id: int, dialog_data: List[Dict]) -> bool:
        # 检查是否存在历史记录
        self.current_table = "test_agent_dialog_memory" if self.test_mode else "agent_dialog_memory"
        check_query = """
          SELECT memory_id 
          FROM {table} 
          WHERE user_id = %s AND agent_id = %s
          LIMIT 1
          """
        check_query = self._format_query(check_query)
        update_query = """
          UPDATE {table} 
          SET dialog_json = %s 
          WHERE memory_id = %s
          """
        update_query = self._format_query(update_query)
        insert_query = """
          INSERT INTO {table} 
          (user_id, agent_id, dialog_json) 
          VALUES (%s, %s, %s)
          """
        insert_query = self._format_query(insert_query)
        try:
            dialog_json = json.dumps(dialog_data, ensure_ascii=False)
            exists = self._execute_query(check_query, (user_id, agent_id))
            if exists:
                # 更新现有记录
                row_count = self._execute_update(
                    update_query,
                    (dialog_json, exists[0]['memory_id'])
                )
                return row_count > 0
            else:
                # 插入新记录
                row_count = self._execute_update(
                    insert_query,
                    (user_id, agent_id, dialog_json)
                )
                return row_count > 0
        except Exception as e:
            print(f"❌❌ 保存对话记忆失败: {e}")
            return False

# 日常对话记录表操作
    def insert_agent_message(self, user_id: int, agent_id: int, role: str, content: str,
                           issue_id: str, timestamp: str, activity: str, status: str) -> bool:
        """插入单条对话消息"""
        self.current_table = "test_agent_messages" if self.test_mode else "agent_messages"
        insert_sql = """
        INSERT INTO {table}
        (user_id, agent_id, role, content, issue_id, timestamp, activity, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        insert_sql = self._format_query(insert_sql)
        try:
            self._execute_update(insert_sql, (user_id, agent_id, role, content,
                                            issue_id, timestamp, activity, status))
            return True
        except Exception as e:
            print(f"❌❌ 插入单条消息失败: {e}")
            return False

    def get_agent_dialog_memory(self, user_id: int, agent_id: int) -> List[Dict]:
        self.current_table = "test_agent_messages" if self.test_mode else "agent_messages"
        query = """
                SELECT role, content, issue_id, timestamp, activity, status
                FROM {table}
                WHERE user_id = %s AND agent_id = %s
                ORDER BY timestamp ASC
                """
        query = self._format_query(query)
        try:
            result = self._execute_query(query, (user_id, agent_id))
            if result and result[0].get('dialog_json'):
                return json.loads(result[0]['dialog_json'])
            return []
        except Exception as e:
            print(f"❌❌ 获取对话记忆失败: {e}")
            return []

    def save_session_state(self, user_id: int, agent_id: int, session_data: dict) -> bool:
        self.current_table = "test_agent_schedules" if self.test_mode else "agent_schedules"
        try:
            # 检查是否存在记录
            check_query = """
                SELECT schedule_id 
                FROM {table} 
                WHERE user_id = %s AND agent_id = %s
            """
            check_query = self._format_query(check_query)
            result = self._execute_query(check_query, (user_id, agent_id))

            if result:
                # 更新现有记录到 schedule_json
                update_query = """
                    UPDATE {table} 
                    SET schedule_json = %s, updated_at = NOW()
                    WHERE schedule_id = %s
                """
                update_query = self._format_query(update_query)
                self._execute_update(update_query,
                                     (json.dumps(session_data), result[0]['schedule_id']))
            else:
                # 插入新记录到 schedule_json
                insert_query = """
                    INSERT INTO {table} 
                    (user_id, agent_id, schedule_json) 
                    VALUES (%s, %s, %s)
                """
                insert_query = self._format_query(insert_query)
                self._execute_update(insert_query,
                                     (user_id, agent_id, json.dumps(session_data)))
            return True
        except Exception as e:
            print(f"❌❌❌❌ 保存会话状态失败: {e}")
            return False

    def get_session_state(self, user_id: int, agent_id: int) -> Optional[dict]:
        self.current_table = "test_agent_schedules" if self.test_mode else "agent_schedules"
        try:
            query = """
                SELECT schedule_json 
                FROM {table} 
                WHERE user_id = %s AND agent_id = %s
                ORDER BY updated_at DESC 
                LIMIT 1
            """
            query = self._format_query(query)
            result = self._execute_query(query, (user_id, agent_id))
            if result and result[0].get('schedule_json'):
                return json.loads(result[0]['schedule_json'])
            return None
        except Exception as e:
            print(f"❌❌❌❌ 获取会话状态失败: {e}")
            return None

# 配置数据库连接信息
DB_CONFIG = {
    "host": "101.200.229.113",
    "user": "gongwei",
    "password": "Echo@123456",
    "database": "echo",
    "port": 3306,
    "charset": "utf8mb4"
}

TEST_DB_CONFIG = {
    "host": "101.200.229.113",
    "user": "gongwei",
    "password": "Echo@123456",
    "database": "echo_test",  # 专用测试数据库
    "port": 3306,
    "charset": "utf8mb4",
    "test_mode": True
}

def main():
    # 1. 读取生效的智能体模板（agent_info类型）
    with MySQLDB(**DB_CONFIG) as db:
        # 查询模板表：获取agent_info类型的生成模板
        agent_template = db.get_active_template(
            template_type="agent_info",
            template_key="agent_generation_template"
        )
        if agent_template:
            print("获取到智能体模板：")
            print("模板内容JSON:", agent_template["content_json"])
            print("模板版本:", agent_template["version"])

    # 2. 读取指定智能体详情
    with MySQLDB(**DB_CONFIG) as db:
        agent_id = 1  # 示例智能体ID
        agent = db.get_agent_by_id(agent_id)
        if agent:
            print(f"\n智能体 {agent_id} 详情：")
            print("姓名:", agent["name"])
            print("世界观:", agent["worldview"])
            print("MBTI类型:", agent["mbti_type"])

    # 3. 读取用户的所有智能体
    with MySQLDB(**DB_CONFIG) as db:
        user_id = 100  # 示例用户ID
        user_agents = db.get_agents_by_user(user_id)
        print(f"\n用户 {user_id} 的智能体列表（共{len(user_agents)}个）：")
        for ag in user_agents:
            print(f"- {ag['name']}（ID: {ag['agent_id']}）")

    # 4. 读取智能体的生平事件
    with MySQLDB(**DB_CONFIG) as db:
        agent_id = 1  # 示例智能体ID
        events = db.get_agent_events(agent_id)
        print(f"\n智能体 {agent_id} 的生平事件（共{len(events)}个）：")
        for event in events:
            print(f"{event['year_desc']}（{event['age_at_event']}）：{event['event_description'][:50]}...")
 # 5. 读取所有活跃的MBTI模板
    with MySQLDB(**DB_CONFIG) as db:
        mbti_templates = db.get_active_mbti_templates()
        print(f"\nMBTI 模板列表（共{len(mbti_templates)}个）：")
        for template in mbti_templates:
            print(f"模板键名: {template['template_key']}, 版本: {template['version']}")
            print("内容JSON:", template["content_json"])


if __name__ == "__main__":
    main()
