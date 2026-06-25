import json
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
                    "text": "Analyze this food image and return the nutritional information as JSON.",
                },
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{base64_image}",
                },
            ],
        }
    ]

    result = await Runner.run(agent, input_messages)

    output = result.final_output.strip()

    if output.startswith("```"):
        output = output.split("```")[1]
        if output.startswith("json"):
            output = output[4:]
        output = output.strip()

    return json.loads(output)
