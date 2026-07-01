from agents import Runner
from nutrition_agent import init_nutrition_agent


async def analyze_food_image(base64_image: str) -> dict:
    agent = init_nutrition_agent()

    input_messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Analyze this food image.",
                },
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{base64_image}",
                },
            ],
        }
    ]

    result = await Runner.run(agent, input_messages)

    return result.final_output.model_dump()
