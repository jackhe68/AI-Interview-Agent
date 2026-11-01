import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

response = client.chat.completions.create(
    model="deepseek-flash",
    messages=[
        {"role": "system",
         "content": "你是一名专业的Java后端技术面试官，面试对象是大学生实习求职者，每次只提出一个java基础面试问题，不要提前公布答案。"},
        {"role":"user",
         "content":"请开始面试。"
        }
    ],
    max_tokens=1024
)

print("回答内容:", repr(response.choices[0].message.content))
user_answer = input("请输入你的回答：")
print("你的回答是：", user_answer)
print("结束原因:", response.choices[0].finish_reason)
print("Token用量:", response.usage)