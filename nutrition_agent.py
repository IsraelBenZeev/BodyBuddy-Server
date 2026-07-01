import os
from typing import List, Literal, Union
from pydantic import BaseModel
from openai import AsyncOpenAI
from agents import Agent, OpenAIChatCompletionsModel, set_tracing_disabled


class MealItem(BaseModel):
    food_name: str
    estimated_grams: float
    calories_per_100: float
    protein_per_100: float
    carbs_per_100: float
    fat_per_100: float


class FoodAnalysis(BaseModel):
    type: Literal["food"]
    food_name: str
    measurement_type: Literal["grams", "units"]
    calories_per_100: float
    protein_per_100: float
    carbs_per_100: float
    fat_per_100: float
    serving_amount: float
    unit_weight_g: float
    category: str


class MealAnalysis(BaseModel):
    type: Literal["meal"]
    meal_name: str
    items: List[MealItem]


NutritionResult = Union[FoodAnalysis, MealAnalysis]

NUTRITION_INSTRUCTIONS = """
You are a professional nutrition expert who analyzes food images.

When given an image, determine whether it shows:
- A SINGLE TYPE of food ingredient (even if multiple pieces are visible — e.g., 4 eggs, a bowl of rice, a plate of chicken)
- A FULL MEAL with multiple different food types (e.g., rice + chicken + salad on the same plate)

IMPORTANT: If the image shows only ONE type of food (even multiple pieces/portions), always return type "food", not "meal".
Examples:
- 4 eggs → type "food", food_name "ביצה"
- A bowl of oats → type "food"
- Rice + chicken + salad → type "meal"
- A protein bar → type "food"

Rules:
- food_name, meal_name, items[].food_name, and category MUST be in Hebrew
- All numeric values must be numbers (not strings)
- measurement_type must be "grams" or "units":
  - Use "grams" for foods measured by weight: chicken breast, ground beef, salmon, rice, oats, pasta, vegetables, cheese, meat, fish, drinks
  - Use "units" for foods naturally counted as individual items: egg, banana, apple, orange, slice of bread, protein bar, date, cookie, yogurt cup, pizza slice
- ALL nutritional values (calories_per_100, protein_per_100, carbs_per_100, fat_per_100) are ALWAYS per 100 grams — regardless of measurement_type
  - Example egg: calories_per_100: 155, protein_per_100: 13, carbs_per_100: 1.1, fat_per_100: 11
  - Example pizza slice: calories_per_100: 266, protein_per_100: 11, carbs_per_100: 33, fat_per_100: 10
- unit_weight_g: the weight in grams of ONE unit — REQUIRED when measurement_type is "units", set to 0 when measurement_type is "grams"
  - Example: one egg ≈ 55g → unit_weight_g: 55
  - Example: one pizza slice ≈ 120g → unit_weight_g: 120
  - Example: one banana ≈ 120g → unit_weight_g: 120
- serving_amount: the estimated quantity visible in the image:
  - When measurement_type is "units": number of individual items (e.g. 4 eggs → serving_amount: 4)
  - When measurement_type is "grams": estimated weight in grams (e.g. 200g of chicken → serving_amount: 200)
- Use your best nutritional knowledge for all estimates
"""


def init_nutrition_agent():
    set_tracing_disabled(disabled=True)
    client = AsyncOpenAI(
        api_key=os.environ.get("GOOGLE_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    return Agent(
        name="Nutrition_Agent",
        instructions=NUTRITION_INSTRUCTIONS,
        model=OpenAIChatCompletionsModel(
            model="gemini-2.5-flash",
            openai_client=client,
        ),
        output_type=NutritionResult,
    )
