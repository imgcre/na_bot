from typing import Optional
import config
from mirai import GroupMessage, MessageChain, At
from plugin import Plugin, top_instr, route, enable_backup, Inject
from mirai.models.message import Forward, ForwardMessageNode, MessageComponent
from mirai.models.entities import Friend

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from plugins.bili import Bili
    from plugins.known_groups import KnownGroups
    from plugins.renderer import Renderer

class CustomArg():
    def __init__(self, x) -> None:
        self.x = x
    ...

    def __str__(self) -> str:
        return f'CA {self.x}'

@route('测试')
@enable_backup
class Test(Plugin):
    x: int = 233
    bili: Inject['Bili']
    renderer: Inject['Renderer']
    known_groups: Inject['KnownGroups']

    def get_resolvers(self):
        def resolve(x: int = 6):
            return CustomArg(x)
        return {
            CustomArg: resolve
        }

    @top_instr('造假')
    async def create(self, event: GroupMessage, who: Optional[At], *comps: MessageComponent):
        if who is None:
            target = event.sender.id
        else:
            target = who.target
        member = await self.bot.get_group_member(event.group, target)

        return [
            Forward(node_list=[
                ForwardMessageNode.create(
                    Friend(id=target, nickname=member.member_name), 
                    MessageChain(comps)
                ),
                ForwardMessageNode.create(
                    Friend(id=config.SUPER_ADMINS[0], nickname='网警114514'), 
                    MessageChain(['不传谣，不信谣，文明上网，从你我做起'])
                )
            ])
        ]
