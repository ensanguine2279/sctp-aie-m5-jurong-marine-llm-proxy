"""How a team member calls OpenAI through the proxy.

    pip install openai
    export LLM_PROXY_URL=http://<proxy-host>:4000
    export LLM_PROXY_KEY=sk-...        # YOUR member key from the admin
    python python_client.py
"""
import os

import openai
from openai import OpenAI

client = OpenAI(
    base_url=os.environ.get("LLM_PROXY_URL", "http://localhost:4000"),
    api_key=os.environ["LLM_PROXY_KEY"],   # member key, NOT the real OpenAI key
)


def ask(prompt, model="gpt-4o-mini"):
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,            # cap output length = cap cost per call
        )
        u = r.usage
        print(f"[tokens in={u.prompt_tokens} out={u.completion_tokens}]")
        return r.choices[0].message.content
    except openai.APIStatusError as e:
        msg = str(e).lower()
        if "budget" in msg:
            raise RuntimeError("LLM budget used up for this key/team. Ask the proxy admin.") from e
        if e.status_code == 401:
            raise RuntimeError("Proxy rejected the key. Check LLM_PROXY_KEY.") from e
        raise


if __name__ == "__main__":
    print(ask("Say hello in five words."))
