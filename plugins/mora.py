from typing import List, Optional

from mirai import At
from mirai.models.entities import GroupMember

from plugin import Plugin, enable_backup, top_instr, InstrAttr, route, Inject
import random
import random
from enum import Enum
from utilities import AchvEnum, AchvOpts, AchvRarity, GroupLocalStorage
from dataclasses import dataclass, field

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.achv import Achv

class MoraAchv(AchvEnum):
    FIRST_WIN = 0, '首胜', '与bot的猜拳获得首次胜利', AchvOpts(display='✌️')
    CONSECUTIVE_WINS_3 = 1, '三连胜', '与bot的猜拳获得连续三次胜利', AchvOpts(rarity=AchvRarity.UNCOMMON, custom_obtain_msg='运气爆棚', display='👌')

class Gesture(Enum):
    Rock = '👊'
    Paper = '✋'
    Scissor = '✌️'

class MoraResult(Enum):
    Draw = '平局'
    PlayerWin = '玩家胜利'
    BotWin = 'bot胜利'

@dataclass
class MoraMan():
    results: List[MoraResult] = field(default_factory=list)

    def play(self, player_gesture: Gesture):
        bot_gesture = random.choice([e for e in Gesture])
        result = self.determine_winner(player_gesture, bot_gesture)
        self.results.append(result)
        return result, bot_gesture

    @property
    def consecutive_wins(self):
        cnt = 0
        while cnt < len(self.results):
            if self.results[-(cnt+1)] != MoraResult.PlayerWin:
                break
            cnt += 1
        return cnt

    def determine_winner(self, player_gesture: Gesture, computer_gesture: Gesture):
        if player_gesture == computer_gesture:
            return MoraResult.Draw
        elif (player_gesture == Gesture.Rock and computer_gesture == Gesture.Scissor) or \
            (player_gesture == Gesture.Paper and computer_gesture == Gesture.Rock) or \
            (player_gesture == Gesture.Scissor and computer_gesture == Gesture.Paper):
            return MoraResult.PlayerWin
        else:
            return MoraResult.BotWin


@route('mora')
@enable_backup
class RusRou(Plugin):
    gls: GroupLocalStorage[MoraMan] = GroupLocalStorage[MoraMan]()
    achv: Inject['Achv']
    
    @top_instr('猜拳', InstrAttr.NO_ALERT_CALLER, InstrAttr.FORECE_BACKUP)
    async def start(self, gesture: Optional[Gesture], mora_man: MoraMan, member: GroupMember):

        if gesture is None:
            gesture = random.choice([e for e in Gesture])

        result, bot_gesture = mora_man.play(gesture)

        if result == MoraResult.PlayerWin:
            await self.achv.submit(MoraAchv.FIRST_WIN)
        
        if mora_man.consecutive_wins >= 3:
            await self.achv.submit(MoraAchv.CONSECUTIVE_WINS_3)

        return [
            At(target=member.id), f' 出了{gesture.value}, bot出了{bot_gesture.value} -> {result.value}'
        ]

        # return [
        #     f'剪刀石头布对局, bot出了{bot_gesture.value}, 玩家出了{gesture.value}, {result.value}, 请总结对局结果(指明玩家和bot各自出的手势)'
        # ]
            

            

