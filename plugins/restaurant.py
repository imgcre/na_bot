import json
import random
from plugin import Plugin, route, top_instr

@route('餐馆')
class Restaurant(Plugin):

    @top_instr("吃什么")
    async def eat_what(self):
        with open(self.path.data.of_file('foods.json'), encoding='utf-8') as f:
            foods: dict = json.load(f)
        choice = random.choice(foods)
        return [choice]
