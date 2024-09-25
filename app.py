import nest_asyncio

nest_asyncio.apply()
# NFC先改，改完在这里测试
import traceback
from activator import SharpActivator
from mirai import Event, MessageChain, Mirai, MessageEvent, Plain, WebSocketAdapter
import plugin
from plugin import CommandNotFoundError
from mirai.models.events import MemberCardChangeEvent, GroupRecallEvent, NudgeEvent, MemberJoinRequestEvent, MemberJoinEvent, MemberUnmuteEvent
from mirai.models.api import RespOperate
import zhconv
import config

bot = Mirai(config.BOT_QQ_ID, adapter=WebSocketAdapter(
    verify_key=config.MIRAI_VERIFY_KEY, 
    host=config.MIRAI_HOST, 
    port=config.MIRAI_PORT
))

activator = SharpActivator()

engine = plugin.Engine(bot)

@bot.on(MemberJoinRequestEvent)
async def on_join_req(event: MemberJoinRequestEvent):
    with engine.of(event) as ctx:
        async def resp(op: RespOperate, msg='bot自动处理'):
            await bot.resp_member_join_request_event(event.event_id, event.from_id, event.group_id, op, msg)
        await ctx.exec_join(resp)

@bot.on(Event)
async def on_event(event: Event):
    if isinstance(event, (MemberCardChangeEvent, GroupRecallEvent, MemberJoinEvent, MemberUnmuteEvent, NudgeEvent)):
        with engine.of(event) as ctx:
            await ctx.exec()

@bot.on(MessageEvent)
async def on_message(event: MessageEvent):
    with engine.of(event) as ctx:
        def map_text(comp):
            if isinstance(comp, Plain):
                t = comp.text
                t = t.replace('‭', '')
                t = zhconv.convert(t, 'zh-cn')
                return Plain(t)
            return comp

        event.message_chain = MessageChain([map_text(c) for c in event.message_chain])

        await ctx.exec_any(event.message_chain)

        chain = activator.check(event)
        if chain is None: 
            await ctx.exec_fall(event.message_chain)
            return

        try:
            await ctx.exec_cmd(chain)
        except CommandNotFoundError as e:
            traceback.print_exc()
            try:
                await ctx.exec_cmd(['ai', *chain])
            except: ...
            ...
        except Exception as e:
            # raise
            traceback.print_exc()
            await ctx.send()

def main():
    engine.load()
    bot.run()

if __name__ == '__main__':
    main()