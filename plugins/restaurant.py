import json
import random
from plugin import Inject, Plugin, route, top_instr

from typing import TYPE_CHECKING

from utilities import throttle_config
if TYPE_CHECKING:
    from plugins.throttle import Throttle

@route('餐馆')
class Restaurant(Plugin):
    throttle: Inject['Throttle']

    @top_instr("吃什么")
    @throttle_config(name='吃饭', max_cooldown_duration=4*60*60)
    async def eat_what(self):
        async with self.throttle as passed:
            if not passed: return

            with open(self.path.data.of_file('foods.json'), encoding='utf-8') as f:
                foods: dict = json.load(f)
            choice = random.choice(foods)
            return [choice]
