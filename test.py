from backend.config import config
print('provider:', config.llm.provider)
print('api_key:', config.llm.api_key[:10] + '...' if config.llm.api_key else 'EMPTY')
print('base_url:', config.llm.base_url)

import asyncio
from openai import AsyncOpenAI

async def test():
    client = AsyncOpenAI(
        api_key="sk-0eecd5f88d5947678aab1244482b0fec",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    try:
        resp = await client.chat.completions.create(
            model="qwen3.5-flash",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=50,
        )
        print("OK:", resp.choices[0].message.content)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")

asyncio.run(test())