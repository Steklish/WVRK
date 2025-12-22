import os
from skls_generator.generator import Generator


class Agent:
    def __init__(self, client):
        self.generator = Generator(client)

    def generate_task(self, pydantic_model, prompt: str):
        return self.generator.generate_one_shot(
            pydantic_model=pydantic_model,
            prompt=prompt
        )