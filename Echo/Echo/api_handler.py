import requests
import argparse
import json
from typing import List, Dict, Optional, Union


class ChatFireAPIClient:
    def __init__(
            self,
            api_key: str = "sk-Ss0zBUF0GXksmrHrgw3CF1ECl8M7aQVHjlBXIWpPLyKxGLZf",
            base_url: str = "https://api.chatfire.cn",
            default_model: str = "gpt-4o"
    ):
        """
        初始化API客户端
        :param api_key: API密钥
        :param base_url: API基础URL
        :param default_model: 默认模型名称
        """
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model

    def call_api(
            self,
            messages: List[Dict[str, str]],
            model: Optional[str] = None,
            # 基础参数
            function_calling: Optional[Dict] = None,
            seed: Optional[int] = None,
            stop_sequence: Optional[Union[str, List[str]]] = None,
            temperature: Optional[float] = None,
            reasoning_effort: Optional[str] = None,
            logit_bias: Optional[Dict[int, float]] = None,
            # Mirostat相关
            mirostat: Optional[bool] = None,
            mirostat_eta: Optional[float] = None,
            mirostat_tau: Optional[float] = None,
            # 采样参数
            top_k: Optional[int] = None,
            top_p: Optional[float] = None,
            min_p: Optional[float] = None,
            # 惩罚参数
            frequency_penalty: Optional[float] = None,
            presence_penalty: Optional[float] = None,
            repeat_last_n: Optional[int] = None,
            tfs_z: Optional[float] = None,
            # Token控制
            tokens_to_keep: Optional[int] = None,
            max_tokens: Optional[int] = None,
            # Ollama特有参数
            ollama_repeat_penalty: Optional[float] = None,
            context_length: Optional[int] = None,
            num_batch: Optional[int] = None,
            use_mmap: Optional[bool] = None,
            use_mlock: Optional[bool] = None,
            **kwargs
    ) -> Optional[Dict]:
        """
        调用ChatFire API
        :param messages: 对话消息历史
        :param model: 模型名称
        :param function_calling: 函数调用配置
        :param seed: 随机种子
        :param stop_sequence: 停止序列
        :param temperature: 温度参数
        :param reasoning_effort: 推理努力级别
        :param logit_bias: Logit偏置
        :param mirostat: 是否启用Mirostat
        :param mirostat_eta: Mirostat学习率
        :param mirostat_tau: Mirostat目标困惑度
        :param top_k: Top K采样
        :param top_p: Top P采样
        :param min_p: 最小概率阈值
        :param frequency_penalty: 频率惩罚
        :param presence_penalty: 存在惩罚
        :param repeat_last_n: 重复最后N个token
        :param tfs_z: TFS-Z参数
        :param tokens_to_keep: 语境刷新时保留的token数量
        :param max_tokens: 最大生成token数
        :param ollama_repeat_penalty: Ollama重复惩罚
        :param context_length: 上下文长度
        :param num_batch: 批大小
        :param use_mmap: 是否使用mmap
        :param use_mlock: 是否使用mlock
        :param kwargs: 其他参数
        :return: API响应或None
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        url = f"{self.base_url}/v1/chat/completions"

        data = {
            "model": model or self.default_model,
            "messages": messages,
            "thinking": {"type": "enabled"}
        }

        # 添加可选参数
        if function_calling is not None:
            data["function_calling"] = function_calling
        if seed is not None:
            data["seed"] = seed
        if stop_sequence is not None:
            data["stop"] = stop_sequence
        if temperature is not None:
            data["temperature"] = temperature
        if reasoning_effort is not None:
            data["reasoning_effort"] = reasoning_effort
        if logit_bias is not None:
            data["logit_bias"] = logit_bias
        if mirostat is not None:
            data["mirostat"] = mirostat
        if mirostat_eta is not None:
            data["mirostat_eta"] = mirostat_eta
        if mirostat_tau is not None:
            data["mirostat_tau"] = mirostat_tau
        if top_k is not None:
            data["top_k"] = top_k
        if top_p is not None:
            data["top_p"] = top_p
        if min_p is not None:
            data["min_p"] = min_p
        if frequency_penalty is not None:
            data["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            data["presence_penalty"] = presence_penalty
        if repeat_last_n is not None:
            data["repeat_last_n"] = repeat_last_n
        if tfs_z is not None:
            data["tfs_z"] = tfs_z
        if tokens_to_keep is not None:
            data["tokens_to_keep"] = tokens_to_keep
        if max_tokens is not None:
            data["max_tokens"] = max_tokens

        # Ollama特有参数
        ollama_params = {}
        if ollama_repeat_penalty is not None:
            ollama_params["repeat_penalty"] = ollama_repeat_penalty
        if context_length is not None:
            ollama_params["context_length"] = context_length
        if num_batch is not None:
            ollama_params["num_batch"] = num_batch
        if use_mmap is not None:
            ollama_params["use_mmap"] = use_mmap
        if use_mlock is not None:
            ollama_params["use_mlock"] = use_mlock

        if ollama_params:
            data["ollama_options"] = ollama_params

        # 添加其他参数
        data.update(kwargs)

        try:
            response = requests.post(url, headers=headers, json=data, timeout=180)  # 180秒超时
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            print("⚠️ API请求超时，请稍后重试")
            return None

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='大语言模型API调用工具')

    # 必需参数
    parser.add_argument('--messages', required=True,
                        help='对话消息历史(JSON字符串或文件路径)')

    # 模型参数
    parser.add_argument('--model', help='模型名称')
    parser.add_argument('--api-key', help='API密钥')
    parser.add_argument('--base-url', help='API基础URL')

    # 基础参数
    parser.add_argument('--function-calling', type=json.loads,
                        help='函数调用配置(JSON字符串)')
    parser.add_argument('--seed', type=int, help='随机种子')
    parser.add_argument('--stop-sequence', help='停止序列(字符串或JSON数组)')
    parser.add_argument('--temperature', type=float, help='温度参数')
    parser.add_argument('--reasoning-effort', help='推理努力级别')
    parser.add_argument('--logit-bias', type=json.loads, help='Logit偏置(JSON)')

    # Mirostat参数
    parser.add_argument('--mirostat', type=bool, help='是否启用Mirostat')
    parser.add_argument('--mirostat-eta', type=float, help='Mirostat学习率')
    parser.add_argument('--mirostat-tau', type=float, help='Mirostat目标困惑度')

    # 采样参数
    parser.add_argument('--top-k', type=int, help='Top K采样')
    parser.add_argument('--top-p', type=float, help='Top P采样')
    parser.add_argument('--min-p', type=float, help='最小概率阈值')

    # 惩罚参数
    parser.add_argument('--frequency-penalty', type=float, help='频率惩罚')
    parser.add_argument('--presence-penalty', type=float, help='存在惩罚')
    parser.add_argument('--repeat-last-n', type=int, help='重复最后N个token')
    parser.add_argument('--tfs-z', type=float, help='TFS-Z参数')

    # Token控制
    parser.add_argument('--tokens-to-keep', type=int,
                        help='语境刷新时保留的token数量')
    parser.add_argument('--max-tokens', type=int, help='最大生成token数')

    # Ollama参数
    parser.add_argument('--ollama-repeat-penalty', type=float,
                        help='Ollama重复惩罚')
    parser.add_argument('--context-length', type=int, help='上下文长度')
    parser.add_argument('--num-batch', type=int, help='批大小')
    parser.add_argument('--use-mmap', type=bool, help='是否使用mmap')
    parser.add_argument('--use-mlock', type=bool, help='是否使用mlock')

    # 输出参数
    parser.add_argument('--output', help='输出结果文件路径')

    return parser.parse_args()


def load_messages(messages_input: str) -> List[Dict[str, str]]:
    """加载消息历史"""
    try:
        # 尝试作为文件路径打开
        try:
            with open(messages_input, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, OSError):
            # 如果不是文件路径，尝试直接解析为JSON
            return json.loads(messages_input)
    except json.JSONDecodeError as e:
        raise ValueError(f"无效的messages格式: {e}")


def main():
    args = parse_arguments()

    try:
        messages = load_messages(args.messages)
    except ValueError as e:
        print(f"错误: {e}")
        return

    # 处理停止序列参数
    stop_sequence = None
    if args.stop_sequence:
        try:
            stop_sequence = json.loads(args.stop_sequence)
        except json.JSONDecodeError:
            stop_sequence = args.stop_sequence

    # 初始化客户端
    client = ChatFireAPIClient(
        api_key=args.api_key if args.api_key else None,
        base_url=args.base_url if args.base_url else None,
        default_model=args.model if args.model else None
    )

    # 调用API
    result = client.call_api(
        messages=messages,
        model=args.model,
        function_calling=args.function_calling,
        seed=args.seed,
        stop_sequence=stop_sequence,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
        logit_bias=args.logit_bias,
        mirostat=args.mirostat,
        mirostat_eta=args.mirostat_eta,
        mirostat_tau=args.mirostat_tau,
        top_k=args.top_k,
        top_p=args.top_p,
        min_p=args.min_p,
        frequency_penalty=args.frequency_penalty,
        presence_penalty=args.presence_penalty,
        repeat_last_n=args.repeat_last_n,
        tfs_z=args.tfs_z,
        tokens_to_keep=args.tokens_to_keep,
        max_tokens=args.max_tokens,
        ollama_repeat_penalty=args.ollama_repeat_penalty,
        context_length=args.context_length,
        num_batch=args.num_batch,
        use_mmap=args.use_mmap,
        use_mlock=args.use_mlock
    )

    if result is None:
        print("API调用失败")
        return

    # 输出结果
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # 保存到文件
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"结果已保存到 {args.output}")
        except IOError as e:
            print(f"无法保存结果到文件: {e}")


if __name__ == "__main__":
    main()