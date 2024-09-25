import nest_asyncio
nest_asyncio.apply()
from mirai import Mirai, MessageEvent, Plain, WebSocketAdapter
import config

bot = Mirai(config.BOT_QQ_ID, adapter=WebSocketAdapter(
    verify_key=config.MIRAI_VERIFY_KEY, 
    host=config.MIRAI_HOST, 
    port=config.MIRAI_PORT
))


@bot.on(MessageEvent)
async def on_message(event: MessageEvent):
    for c in event.message_chain:
        if isinstance(c, Plain):
            if c.text.startswith('#'):
                await bot.send(event, ['正在维护中...'])

def main():
    bot.run()

if __name__ == '__main__':
    main()
