import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

response = client.responses.create(
    model=os.getenv("MODEL_NAME", "gpt-4.1"),
    input="Say hello",
)

print(response.output_text)
