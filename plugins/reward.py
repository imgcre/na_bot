
from dataclasses import dataclass, field
import time
import typing
from plugin import Inject, Plugin, delegate, enable_backup, route

from typing import TYPE_CHECKING

from utilities import RewardCategoryInfo, RewardEnum, RewardInfo, UserSpec
if TYPE_CHECKING:
    from plugins.voucher import Voucher

@dataclass
class RewardRecordItem():
    consume_id: float
    reward: RewardEnum
    created_ts: int = field(default_factory=time.time)

@dataclass
class RewardHistoryMan():
    obtained_reward_records: list[RewardRecordItem] = field(default_factory=list)

    def is_eligible(self, reward_enum: RewardEnum):
        info: RewardInfo = reward_enum.value
        category_info: RewardCategoryInfo = info.opts.category.value

        if info.opts.max_claims is not None and info.opts.max_claims < len([rr for rr in self.obtained_reward_records if rr.reward is reward_enum]):
            return False

        if category_info.opts.is_exclusive and len([rr for rr in self.obtained_reward_records if typing.cast(RewardInfo, rr.reward.value).opts.category is info.opts.category]) > 0:
            return False

        return True
    
    def append(self, reward_enum: RewardEnum, consume_id: float):
        self.obtained_reward_records.append(RewardRecordItem(consume_id=consume_id, reward=reward_enum))
        ...
    ...

@route('奖励系统')
@enable_backup
class Reward(Plugin):
    user_histories: UserSpec[RewardHistoryMan] = UserSpec[RewardHistoryMan]()

    voucher: Inject['Voucher']

    @delegate()
    async def get_reward(self, reward_enum: RewardEnum, man: RewardHistoryMan):
        info: RewardInfo = reward_enum.value
        is_satisfied = await self.voucher.is_satisfied(cnt=info.opts.ticket_cost)

        if not is_satisfied:
            raise RuntimeError(f'兑奖券不足, 需要{info.opts.ticket_cost}张')
        
        if not man.is_eligible(reward_enum):
            raise RuntimeError(f'无法兑换奖励, 与已获得的奖励相冲突')
        
        self.backup_man.set_dirty()
        consume_id = await self.voucher.consume(cnt=info.opts.ticket_cost)
        man.append(reward_enum, consume_id)
