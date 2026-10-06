import os
from dotenv import load_dotenv
from groq import Groq
load_dotenv()
client = Groq(api_key=os.environ["GROQ_API_KEY"])
reply = client.chat.completions.create(
model="openai/gpt-oss-120b",
messages=[{"role": "user", "content": "In one line, what does RBI stand for?"}],
)
print(reply.choices[0].message.content)