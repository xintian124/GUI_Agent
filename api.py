import requests


# 与llm交互
def call(chat, model, api_url, token):
    headers = {
        "Content-Type": "application/json",  # json格式
        "Authorization": f"Bearer {token}"  # API调用身份认证
    }  # 设置请求头

    data = {
        "model": model,
        "messages": [],  # 多轮对话历史
        "max_tokens": 2048,  # 控制输出长度
        'temperature': 0.0,  # 保证deterministic
        "seed": 3
    }

    # 把chat.py传来的对话历史逐条转换成openai官方api要求的格式
    # {
    #     "messages": [
    #         {"role": "system", "content": [...]},
    #         {"role": "user", "content": [...]}
    #     ]
    # }
    for role, content in chat:
        data["messages"].append({"role": role, "content": content})

    while True:
        try:
            res = requests.post(api_url, headers=headers, json=data)
            res_json = res.json()  # 解析返回json
            res_content = res_json['choices'][0]['message']['content']  # 取出模型的回答
        except:
            print("Network Error:")
            try:
                print(res.json())
            except:
                print("Request Failed")
        else:
            break
    
    return res_content
