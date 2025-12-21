import os
from skls_generator.generator import Generator
from skls_generator.gen_backends.google_gen import GoogleGenAI

from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv(override=True)


client = GoogleGenAI(
        api_key=os.getenv("GEMINI_API_KEY")
    )

generator = Generator(client)

class Person(BaseModel):
    name: str = Field(description="Pesron full name")
    age: int = Field(description="age")


a = generator.generate_one_shot(
    pydantic_model=Person,
    prompt="Джек 33 года. Его фамилия Томпсон"
)

print(a.__dict__)