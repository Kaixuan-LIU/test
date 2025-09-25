import os

class Config:
    # 从环境变量获取配置，提供默认值
    DB_HOST = os.getenv("DB_HOST", "101.200.229.113")
    DB_USER = os.getenv("DB_USER", "gongwei")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "Echo@123456")
    DB_PORT = int(os.getenv("DB_PORT", 3306))
    DB_CHARSET = os.getenv("DB_CHARSET", "utf8mb4")

    # API密钥
    API_KEY = os.getenv("CHATFIRE_API_KEY", "sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV")

    # 环境标识
    ENV = os.getenv("APP_ENV", "production")

    @property
    def DB_CONFIG(self):
        """根据环境动态生成数据库配置"""
        database = "echo" if self.ENV == "production" else "echo_test"
        return {
            "host": self.DB_HOST,
            "user": self.DB_USER,
            "password": self.DB_PASSWORD,
            "database": database,
            "port": self.DB_PORT,
            "charset": self.DB_CHARSET
        }

config = Config()