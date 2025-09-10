import os
import json
from collections import defaultdict
from typing import List, Dict
import jieba
from Agent_builder import AgentBuilder
from api_handler import ChatFireAPIClient
from database import MySQLDB, DB_CONFIG
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


class AgentGenerator:
    def __init__(self, world_descriptions: List[str], api_key: str, db_config: dict, base_template: str = None):
        """
        智能体批量生成器
        参数:
            world_descriptions: 世界观描述列表
            api_key: API密钥
            db_config: 数据库配置
            base_template: 基础模板
        """
        self.world_descriptions = world_descriptions
        self.api_key = api_key
        self.db = MySQLDB(**db_config)
        self.base_template = base_template or """
        请根据以下世界观描述创建智能体:
        {world_description}

        要求:
        - 智能体需包含: 姓名、职业、核心性格特征
        - 添加3个独特个性标签
        - 包含1个专业知识领域
        """

    def generate_agents(self, num_per_world: int = 3):
        """批量生成智能体"""
        all_agents = []

        for world_desc in self.world_descriptions:
            for _ in range(num_per_world):
                # 生成智能体配置
                agent_config = self._generate_agent_config(world_desc)

                # 创建智能体
                builder = AgentBuilder(api_key=self.api_key)
                agent_data = builder.build_agent(agent_config)
                metadata = self._create_metadata(agent_data, world_desc)
                all_agents.append(metadata)

        return all_agents

    def _generate_agent_config(self, world_desc: str) -> str:
        """使用AI生成智能体配置描述"""
        prompt = self.base_template.format(world_description=world_desc)

        # 调用API生成配置
        response = ChatFireAPIClient(api_key=self.api_key).call_api(
            [{"role": "user", "content": prompt}],
            max_tokens=300
        )

        return response['choices'][0]['message']['content']

    def auto_classify(self, agent_metadatas: List[Dict]) -> Dict:
        """通过关键词提取直接分类智能体"""
        # 提取所有智能体的特征文本
        texts = [
            f"{m['basic']['profession']} {' '.join(m['basic']['personality_tags'])} {' '.join(m['basic']['knowledge_domains'])}"
            for m in agent_metadatas
        ]

        # 提取关键词并创建分类
        classified_agents = self._keyword_classification(texts, agent_metadatas)

        # 合并相似类别
        merged_classification = self._merge_similar_categories(classified_agents)

        return merged_classification

    def _keyword_classification(self, texts: List[str], agents: List[Dict]) -> Dict:
        """核心关键词分类逻辑"""
        # 特征提取：获取每个文本的前3个关键词
        vectorizer = TfidfVectorizer(tokenizer=jieba.cut, stop_words=self._get_stop_words())
        tfidf_matrix = vectorizer.fit_transform(texts)
        feature_names = vectorizer.get_feature_names_out()

        # 创建类别字典
        categories = defaultdict(list)

        # 为每个智能体分配类别
        for i, agent in enumerate(agents):
            # 获取当前文档的TF-IDF向量
            row = tfidf_matrix[i].toarray()[0]

            # 获取TF-IDF最高的前3个关键词
            top_keyword_indices = np.argsort(row)[::-1][:3]
            top_keywords = [feature_names[idx] for idx in top_keyword_indices if row[idx] > 0]

            if not top_keywords:
                categories['其他'].append(agent)
                continue

            # 创建复合类别标签
            category_label = '_'.join(top_keywords)
            categories[category_label].append(agent)

        return dict(categories)

    def _merge_similar_categories(self, classified_dict: Dict) -> Dict:
        """合并相似类别"""
        # 创建相似度映射表
        merged_dict = {}
        category_mapping = {}

        for category in list(classified_dict.keys()):
            if not category:
                continue

            # 提取核心词根（取每个关键词的第一个字）
            core_roots = ''.join([word[0] for word in category.split('_') if word])

            # 查找相似类别
            merged = False
            for existing in merged_dict:
                # 相似性判断：共享核心词根或包含关系
                shared_roots = sum(1 for char in core_roots if char in existing) >= 2
                contains = core_roots in existing or existing in core_roots

                if shared_roots or contains:
                    merged_dict[existing].extend(classified_dict[category])
                    category_mapping[category] = existing
                    merged = True
                    break

            if not merged:
                merged_dict[core_roots] = classified_dict[category]
                category_mapping[category] = core_roots

        # 重命名类别为可读性更好的标签
        final_classification = {}
        for category, agents in merged_dict.items():
            # 获取最常出现的三个关键词作为最终标签
            all_keywords = []
            for agent in agents:
                profession = agent['basic']['profession']
                tags = agent['basic']['personality_tags']
                domains = agent['basic']['knowledge_domains']

                all_keywords.extend(jieba.cut(profession))
                all_keywords.extend(tags)
                all_keywords.extend(domains)

            # 统计词频
            word_freq = defaultdict(int)
            for word in all_keywords:
                if len(word) > 1:  # 忽略单字词
                    word_freq[word] += 1

            # 取最高频的3个词
            top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:3]
            final_label = '|'.join([word for word, _ in top_keywords])

            final_classification[final_label] = agents

        return final_classification

    def _get_stop_words(self) -> List[str]:
        """获取中文停用词表"""
        return [
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到',
            '说', '要',
            '去', '你', '会', '着', '没有', '看', '好', '自己', '这', '中', '为', '我们', '他', '会', '等', '年', '月',
            '日'
        ]

    def _create_metadata(self, agent_data: Dict, world_desc: str) -> Dict:
        """创建元数据"""
        # 从agent_data中提取关键特征
        return {
            "agent_id": agent_data.get("agent_id", ""),
            "world_description": world_desc,
            "basic": {
                "profession": agent_data.get("职业", ""),
                "personality_tags": agent_data.get("性格标签", []),
                "knowledge_domains": agent_data.get("知识领域", [])
            },
            "interaction": {
                "language_style": agent_data.get("语言风格", ""),
                "core_prompt": agent_data.get("核心提示词", "")
            },
            "technical": {
                "generation_version": "v2.0-flexible",
                "api_config": {"model": "gpt-4-turbo"}
            }
        }

    def save_agents(self, agents: List[Dict]):
        """保存智能体元数据到数据库"""
        for agent_meta in agents:
            self._save_metadata(agent_meta)
        print(f"✅ 成功保存 {len(agents)} 个智能体元数据")

    def generate_and_save_agents(self, num_per_world: int = 3) -> List[Dict]:
        """批量生成并保存智能体"""
        agents = self.generate_agents(num_per_world)  # 生成
        self.save_agents(agents)  # 保存
        return agents


def run_generation():
    """运行批量生成"""
    API_KEY = "sk-Jgb98JXxJ0nNfB2vcNoQ0ZZg1B5zYbM1TgsGmc1LOrNPMIPV"
    DB_CONFIG = {
        "host": "101.200.229.113",
        "user": "gongwei",
        "password": "Echo@123456",
        "database": "echo",
        "port": 3306,
        "charset": "utf8mb4"
    }

    # 世界观描述
    WORLD_DESCRIPTIONS = [
        "一个医疗科技高度发达的未来世界",
        "一个文学创作成为主要生产力的社会",
        "一个法律AI主导司法体系的数字时代"
    ]

    generator = AgentGenerator(
        world_descriptions=WORLD_DESCRIPTIONS,
        api_key=API_KEY,
        db_config=DB_CONFIG
    )

    # 批量生成并保存智能体
    agents = generator.generate_and_save_agents(num_per_world=5)

    # 返回生成的智能体ID列表
    agent_ids = [agent["agent_id"] for agent in agents]
    print(f"📋 生成的智能体ID列表: {agent_ids}")
    return agent_ids


if __name__ == "__main__":
    agent_ids = run_generation()