import asyncio
import traceback
import uuid
import config
from event_types import ViolationEvent
from mirai import At, Image, Plain, GroupMessage, MessageChain, MessageEvent, Voice
from plugin import Context, Inject, Plugin, autorun, delegate, instr, fall_instr, nudge_instr, recall_instr, top_instr, InstrAttr, route
from mirai.models.message import Quote, MarketFace, ShortVideo
from mirai.models.events import NudgeEvent, Event, GroupRecallEvent
from mirai.models.entities import Group, GroupMember
import openai
import os
import random
import json
import time
import inspect
from typing import Callable, Dict, List, Optional
from enum import Enum
import math
from mirai.models.message import MessageComponent
import aiohttp
from asyncify import asyncify
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkimage.v2 import *
from huaweicloudsdksis.v1.region.sis_region import SisRegion
from huaweicloudsdksis.v1 import *
from mako.lookup import TemplateLookup
from abc import ABC, abstractmethod
from PIL import Image as PImage
from io import BytesIO
import base64
import aiofile
from graiax import silkcoder
import re
import glob
from pathlib import Path
from enum import Enum, auto
import google.generativeai as genai
from google.generativeai.files import file_types
from google.generativeai.types import Tool
from google.generativeai.protos import FunctionResponse, Part
import random

from typing import TYPE_CHECKING

from utilities import AchvRarity, SourceOp, breakdown_chain_sync, get_logger, handler
if TYPE_CHECKING:
    from plugins.rest import Rest
    from plugins.check_in import CheckIn
    from plugins.ai_ext import AiExt
    from plugins.achv import Achv
    from plugins.events import Events
    from plugins.festival import Festival

logger = get_logger()

genai.configure(api_key=config.GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-pro')

class Dir(Enum):
    motions = auto()
    logs = auto()

@route('gpt')
class Gpt(Plugin):
    chat_ctx: 'ChatContextMan'

    rest: Inject['Rest']
    check_in: Inject['CheckIn']
    ai_ext: Inject['AiExt']
    achv: Inject['Achv']
    events: Inject['Events']
    festival: Inject['Festival']

    def __init__(self) -> None:
        self.history = []
        self.enabled = False
        self.chat_ctx = ChatContextMan(self)
        self.news: List[str] = []


    @autorun
    async def post_init(self):
        with open(self.path.data.of_file('known_members.json'), encoding='utf-8') as f:
            j = json.load(f)
        self.member_man = MemberMan({
            **{int(k):v for k,v in j.items()},
            self.bot.qq: 'bot'
        })

    @handler
    @delegate()
    async def on_violation(self, event: ViolationEvent, group: Group):
        history = self.chat_ctx.get_group_history(group.id)

        member = await self.bot.get_group_member(group.id, event.member_id)
        who = self.member_man.get_name_from_id(member.id, await self.achv.get_raw_member_name())

        if event.hint is None:
            msg = f'"{who}"违规了, 违规次数(功德)计数增加至{event.count}'
        else:
            msg = f'"{who}"违规了, 原因: {event.hint}, 违规次数(功德)计数增加至{event.count}'
        
        await history.append_system_msg(msg)
        logger.debug(f'[{msg=}]')

    @recall_instr()
    async def on_recall(self, event: GroupRecallEvent):
        if event.operator is not None and event.operator.id != self.bot.qq: return
        history = self.chat_ctx.get_group_history(event.group.id)
        member = await self.bot.get_group_member(event.group.id, event.author_id)
        who = self.member_man.get_name_from_id(event.author_id, await self.achv.get_raw_member_name())
        await history.append_system_msg(f'bot撤回了群成员"{who}"的消息, 被撤回消息的的消息id: {event.message_id}')


    @instr('清空')
    async def clear(self, event: MessageEvent):
        history = self.chat_ctx.get_history_from_event(event)
        await history.clear()
        return '我是一只小猫咪，UWU，脑袋空空的，什么也不知道'
    
    # @instr('关')
    # @admin
    # async def close(self):
    #     self.enabled = False
    #     return 'gpt已关闭, 只保留对戳一戳的反应'
    
    # @instr('开')
    # @admin
    # async def open(self):
    #     self.enabled = True
    #     return 'gpt已开启'

    async def load_image(self, img: Image):
        logger.debug(img.url)  
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(img.url) as resp:
                    content_type = resp.headers.get('Content-Type')
                    pimg: PImage.Image = PImage.open(BytesIO(await resp.read()))
            if content_type != 'image/gif':
                return pimg
            buffered = BytesIO()
            pimg.convert('RGB').save(buffered, format="JPEG")
            return PImage.open(buffered)
        except Exception as e:
            ...
        return '[图片:无法查看]'
        ...

    async def analyze_voice(self, voice: Voice):
        credentials = BasicCredentials(config.HUAWEICLOUD_AK, config.HUAWEICLOUD_SK)

        rnd_str = uuid.uuid4()
        target_silk_file_path = self.path.data.cache.of_file(f'{rnd_str}.silk')
        target_mp3_file_path = self.path.data.cache.of_file(f'{rnd_str}.mp3')
        await voice.download(target_silk_file_path)
        await silkcoder.async_decode(target_silk_file_path, target_mp3_file_path)
        logger.debug(f'save -> {target_mp3_file_path}')

        async with aiofile.async_open(target_mp3_file_path, 'rb') as mp3_file:
            binary = await mp3_file.read()
            b64str = base64.b64encode(binary)

        credentials = BasicCredentials("UFQMCKOESKRGI3YY2FK0", "5yCSOZsFLJ4tR5gZINi3Os6ahRkFGKnM1d81Ik7A") \

        client = SisClient.new_builder() \
            .with_credentials(credentials) \
            .with_region(SisRegion.value_of("cn-north-4")) \
            .build()

        try:
            request = RecognizeShortAudioRequest()
            configbody = Config(
                audio_format="mp3",
                _property="chinese_16k_travel",
                add_punc="yes"
            )
            request.body = PostShortAudioReq(
                data=b64str,
                config=configbody
            )
            response = await asyncify(client.recognize_short_audio)(request)
            # response.result.score
            text = response.result.text
            return text if len(text) > 0 else '{听不到任何内容}'
        except exceptions.ClientRequestException as e:
            logger.debug(e.status_code)
            logger.debug(e.request_id)
            logger.debug(e.error_code)
            logger.debug(e.error_msg)
        finally:
            os.remove(target_silk_file_path)
            os.remove(target_mp3_file_path)
        return '无法识别'

    async def preprocess_chain(self, chain: MessageChain):
        chain = chain[:]
        async def map_comp(c: MessageComponent):
            if isinstance(c, Plain):
                return c.text
            if isinstance(c, At):
                return f'@{self.member_man.get_name_from_id(c.target, await self.achv.get_raw_member_name())} '
            if isinstance(c, Image):
                return await self.load_image(c)
            if isinstance(c, ShortVideo):
                logger.debug(f'[正在下载视频...]')
                path = await c.download(self.path.data.cache)
                logger.debug(f'[正在上传视频...]')
                file = genai.upload_file(path)
                prev_ts = time.time()
                while file.state.name == "PROCESSING":
                    if time.time() - prev_ts > 5:
                        logger.debug(f'[视频:上传失败,超时]')
                        return f'[视频:上传失败,超时]'
                    await asyncio.sleep(0.1)
                    logger.debug('.', end='')
                    file = genai.get_file(file.name)

                if file.state.name == "FAILED":
                    logger.debug(f'[视频上传失败]')
                else:
                    logger.debug(f'[视频上传成功, {time.time() - prev_ts:.2f}s]')
                    return file
                ...
            if isinstance(c, Quote):
                return ''
            if isinstance(c, MarketFace):
                name = c.name[1:-1] if c.name != '' else '未知'
                logger.debug(f'{c.id=} {c.name=}')
                return f'[表情: {name}]'
            if isinstance(c, Voice):
                return f'[语音: {await self.analyze_voice(c)}]'
            return c
        chain = await asyncio.gather(*[map_comp(c) for c in chain])
        chain_new = []
        prev_ele = None
        for c in chain:
            if not isinstance(c, (str, PImage.Image, file_types.File)):
                continue
            if prev_ele is not None and isinstance(prev_ele, str) and isinstance(c, str):
                chain_new.append(' ')
            prev_ele = c
            chain_new.append(c)
        # chain = MessageChain(chain_new)
        return chain_new
    
    async def postprocess_chain(self, chain: MessageChain):
        chain = chain[:]
        async def map_comp(c: MessageComponent):
            if isinstance(c, Image):
                return await self.load_image(c)
            return str(c)
        return await asyncio.gather(*[map_comp(c) for c in chain])

    @delegate()
    async def run(self, event: Event, member: GroupMember, *, chain: MessageChain, ob_mode=False):
        if chain is not None:
            chain = await self.preprocess_chain(chain)
        history = self.chat_ctx.get_history_from_event(event)
        # logger.debug(f'{type(event)=}')
        # logger.debug(f'{chain=}')
        if isinstance(event, MessageEvent):
            should_return = ob_mode
            who = self.member_man.get_name_from_id(member.id, await self.achv.get_raw_member_name())

            for m in event.message_chain:
                if isinstance(m, Quote):
                    logger.debug('[find quote]')
                    target = self.member_man.get_name_from_id(m.sender_id, await self.achv.get_raw_member_name())
                    if target is None: target = '陌生人'
                    logger.debug(f'[msgid: {event.message_chain.message_id}]')
                    logger.debug(f'[repl orginal msgid: {m.id}]')
                    await history.append_system_msg(f'【消息id: {event.message_chain.message_id}】{who}回复{target}, "{who}"所回复的原内容的消息id是【{m.id}】，并说:')
                    logger.debug(f'{target} <- {who}: {chain}')
                    # if m.sender_id == self.bot.qq:
                    #     should_return = False
                        # should_return = random.random() > 0.1
                    break
            else:
                if isinstance(event, GroupMessage):
                    logger.debug(f'[msgid: {event.message_chain.message_id}]')
                    if ob_mode:
                        await history.append_system_msg(f'【消息id: {event.message_chain.message_id}】{who}在群里说:')
                    else:
                        await history.append_system_msg(f'【消息id: {event.message_chain.message_id}】(本条消息如果缺乏主语，那么就是群友在直接和你对话){who}在群里对你说:')
                else:
                    await history.append_system_msg(f'{who}私下和你说:')
                logger.debug(f'bot <- {who}: {chain}')


            # chain = await self.postprocess_chain(chain)
            await history.append({"role": "user", "content": chain})
            
            if should_return:
                return
            
            return await self.chat(history)

        elif isinstance(event, NudgeEvent):
            if event.target != self.bot.qq:
                return
            logger.debug('[handle nudge]')
            def_name = '陌生人'
            if event.subject.kind == 'Group':
                member = await self.bot.get_group_member(event.subject.id, event.from_id)
                if member is not None:
                    def_name = await self.achv.get_raw_member_name()
            logger.debug(f'{def_name=}')
            who = self.member_man.get_name_from_id(member.id, def_name)
            actions = [
                '揉了揉你的脑袋',
                '摸了摸你的肚皮',
                '挠了挠你的下巴',
                '搓了搓你的尾巴',
                '轻轻捏了捏你的耳朵',
                '给你闻了些猫薄荷',
                '用逗猫棒陪你玩',
                # '撸了撸你的小肉丁',
                '蹭了蹭你的肉垫',
                '亲了亲你的脸颊',
                '顺了顺你的后背',
                '投喂了你一罐沙丁鱼罐头',
                '揪了揪你的胡须',
                '指尖划过你的后背',
                '刺挠着你',
                '揉搓你的原始袋',
                '往你的耳朵里吹气',
                '抱着你猛吸了一口',
                '向空中抛出了鸡肉冻干',
                '在你面前使用激光笔',
                '把你抱到了被窝里',
                '用麻袋把你套走了',
                '正在给你做头部按摩',
                '帮助你顺毛',
                '叫着你的名字',
                '碰了碰你的鼻子',
                '对着你眨了眨眼',
                '朝你丢了颗乒乓球',
                '给你变了个纸杯魔术',
                '对着你喵喵叫',
                '把你高高抱起',
                '在你旁边认真工作',
                '和你玩起了躲猫猫',
                '扔出了回旋镖',
            ]
            await history.append_system_msg(f'事件："{who}"{random.choice(actions)}，请富有文采地表达你的愉悦，本次输出请尽量简短，字数最好30字以内，请提及与你互动的群友的名字(即"{who}")，以及生动描述被互动的部位的状态，输出中坚决不可以出现\"谢谢\"、\"软软的\"、\"舒服\"等词语')
            return await self.chat(history, limited_history=True)

    @delegate()
    async def increase_affection(self, source_op: Optional[SourceOp]):
        try:
            if source_op is not None:
                await source_op.send('好感度提升了!')
        except:
            ...
        logger.debug('[increase_affection func called]')
        ...

    async def create_talk(self, history: 'History', *, limited_history=False):
        def mapper(msg):
            return {
                'role': {
                    'user': 'user',
                    'system': 'user',
                    'assistant': 'model'
                }[msg['role']],
                'parts': msg['content']
            }
        
        import functools

        def reducer(combined, next_ele):
            if len(combined) == 0:
                return [next_ele]
            last_msg = combined[-1]
            if last_msg['role'] == next_ele['role']:
                flatten = lambda x: [y for l in x for y in flatten(l)] if type(x) is list else [x]
                return [*combined[:-1], {
                    'role': last_msg['role'],
                    'parts': flatten([last_msg['parts'], next_ele['parts']])
                }]
            return [
                *combined, next_ele
            ]
            ...

        while True:
            resp = (await model.generate_content_async(
                functools.reduce(reducer, map(mapper, await history.merged(limited_history=limited_history)), []), 
                safety_settings=[ 
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"}, 
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"}, 
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"}, 
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                ],
                tools=[Tool([
                    {
                        'name': 'increase_affection',
                        'description': '增加bot对当前群友的好感度',
                        'parameters': {
                            'type_': 'OBJECT',
                            'properties': {
                                'val': {'type_': 'NUMBER'},
                             },
                             'required': ['val']
                        }
                    }
                ])]
            ))
            # logger.debug(f'{resp=}')

            if 'function_call' in resp.candidates[0].content.parts[0]:
                function_call = resp.candidates[0].content.parts[0].function_call
                if function_call.name == 'increase_affection':
                    await self.increase_affection()
                    await history.append({"role": "system", "content": Part(
                        function_response  = FunctionResponse(
                            name = 'increase_affection',
                            response = {
                                'result': True
                            }
                        )
                    )})
                    continue
            break

        return {
            'choices': [
                {
                    'message': {
                        'role': 'assistant',
                        'content': resp.candidates[0].content.parts[0].text
                    }
                }
            ]
        }

    @delegate()
    async def response_with_ai(self, event: MessageEvent, *, msg: List[MessageComponent]):
        history = self.chat_ctx.get_history_from_event(event)
        who = self.member_man.get_name_from_id(event.sender.id, await self.achv.get_raw_member_name())
        try:
            def map_text(c: MessageComponent):
                if isinstance(c, Plain):
                    return c.text.replace('你', who)
                elif isinstance(c, str):
                    return c.replace('你', who)
                return c
            text = "".join([map_text(m) for m in msg])
            await history.append_system_msg(f'请按照你的设定的说话方式向{who}说以下内容【{text}】, 请复述:')
            resp = await self.chat(history)
            await self.ai_ext.as_chat_seq(mc=resp)
            return
        except:
            ...
        return [f'{who}{"".join(msg)}~']

    async def chat(self, history: 'History', *, limited_history=False):
        try_count = 4

        while try_count > 0:
            comm_failed = False
            while True:
                logger.debug('[发起gpt请求]')
                try:
                    response = await self.create_talk(history, limited_history=limited_history)
                    logger.debug(f'{response=}')
                except:
                    traceback.print_exc()
                    comm_failed = True
                    break
                logger.debug('[结束gpt请求]')
                
                msg = random.choice(response['choices'])['message']
                logger.debug(msg)
                break

            if comm_failed:
                logger.debug('[gpt请求发生错误]')
                try_count -= 1
                continue

            say = msg['content']
            logger.debug(f'bot -> {say}')
            # self.append_system_msg(f'bot在群里说:')
            
            if any([c in say for c in ['{bot}', '{system}', '在群里说:']]): 
                logger.debug('[检测到在模拟系统消息, 重试中]')
                await history.append_system_msg(f'请勿输出或模拟系统消息！')
                try_count -= 1
                continue
            await history.append(msg)
            if len(say) > 500:
                logger.debug('[字数超出限制, 重试中]')
                if try_count > 1:
                    await history.append_system_msg(f'你的回复字数过多, 请精简后重新回复, 字数最好控制在100字以内')
                else:
                    await history.append_system_msg(f'你的回复字数过多, 且即将超过重试次数，请向群友表达自己无法精简回复内容的歉意')
                try_count -= 1
                continue
            history.update_last_chat_tsc()

            # say = say.split('\n\n')[0]

            async def motion_op(s, ctx):
                if 'image-append' in ctx:
                    return
                img_paths = glob.glob(self.path.data[Dir.motions].of_file(f'{s}.*'))
                if len(img_paths) > 0: # and random.random() < 0.8
                    ctx['image-append'] = True
                    return Image(path=img_paths[0])
                # return f'[未知表情:{s}]'
            ctx = {}
            chain = await self.breakdown_chain(say, r'\[表情:(.*?)\]', motion_op, ctx)
            chain = await self.breakdown_chain(chain, r'\[([^:]*?)\]', motion_op, ctx)

            async def instrction_op(s, ctx):
                if s == '睡眠':
                    return await self.rest.go_to_sleep()
                if s == '签到':
                    return await self.check_in.do_check_in()
            chain = await self.breakdown_chain(chain, r'\[指令:(.*?)\]', instrction_op)

            async def no_op(s, ctx):
                ...
            chain = await self.breakdown_chain(chain, r'\[(.*?)\]', no_op)

            logger.debug(chain)
            return chain
        ...

    async def breakdown_chain(self, chain, regex, cb, ctx=None):
        if ctx is None:
            ctx = {}
        new_chain = []
        if type(chain) is str:
            chain = [chain]
        for comp in chain:
            txt = None
            if isinstance(comp, str):
                txt = comp
            if isinstance(comp, Plain):
                txt = comp.text
            if txt is None:
                new_chain.append(comp)
                continue
            of_sp = re.split(regex, txt)
            for idx, s in enumerate(of_sp):
                if idx % 2 != 0:
                    s = await cb(s, ctx)
                    logger.debug(f'{s=}')
                if s is not None and s != '':
                    if type(s) is list:
                        new_chain.extend(s)
                    else:
                        new_chain.append(s)
        return new_chain

    @autorun
    async def initiative_talk(self, ctx: Context):
        while True:
            await asyncio.sleep(1)
            with ctx:
                tasks = []
                h = self.chat_ctx.groups.get(139825481, None)
                hs = [h] if h is not None else []
                # for history in self.chat_ctx.groups.values():
                for history in hs:
                    async def fn():
                        prob = (
                            math.log10(1 + history.member_speaking_times_during_last_initiative_talk) 
                            * 1 / (60 * 60) # 平均半小时说一句话
                        )
                        if (time.time() - history.member_last_speak_tsc) > 5 * 60:
                            prob = 0
                        history.set_initiative_talk_prob(prob)
                        history.set_last_initiative_talk_prob_update_tsc(time.time())
                        await history._update_log_file()
                        # with open(os.path.join(RESOURCE_PATH, 'prob.log'), 'wt', encoding='utf-8') as f:
                        #     f.write(f'prob: {prob}')
                        if random.uniform(0, 1) < prob:
                            logger.info(f'主动发言: {history.id}')
                            await history.append_system_msg(f'bot主动发言, 请考虑所有聊天记录进行发言(不一定要回复最后一条消息), 请勿使用第二人称称谓')
                            for _ in range(5):
                                try:
                                    content = await self.chat(history)
                                    history.member_speaking_times_during_last_initiative_talk = 0
                                    group = await self.bot.get_group(history.id)
                                    async with self.override(group):
                                        await self.ai_ext.as_chat_seq(mc=content)
                                    break
                                except Exception as e:
                                    logger.info(f'主动发言: {e}')
                            else:
                                await history.pop()
                            logger.info(f'主动发言完成: {history.id}')
                    tasks.append(fn())
                await asyncio.gather(*tasks)

    @autorun
    async def update_news(self):
        while True:
            try:
                await self.chat_ctx.update_news()
            except: ...
            logger.info('新闻已更新')
            await asyncio.sleep(60 * 60)

    @nudge_instr(InstrAttr.INTERCEPT_EXCEPTIONS)
    async def nudge(self, event: NudgeEvent):
        # if event.subject.kind != 'Group':
        #     return
        
        if event.target != self.bot.qq:
            return
        
        checkin_ts_today = await self.check_in.get_checkin_ts_today()

        if checkin_ts_today is None:
            return

        if time.time() - checkin_ts_today < 60:
            return

        if not await self.ai_ext.check_avaliable(): return
        resp = await self.run(chain=None)
        await self.ai_ext.as_chat_seq(mc=resp)
        await self.ai_ext.mark_invoked()

    @delegate()
    async def get_current_member_name(self, member: GroupMember):
        return self.member_man.get_name_from_id(member.get_name(), await self.achv.get_raw_member_name())

    # async def response_with_ai(self, event: MessageEvent, msg: List[MessageComponent]):
    #     history = self.chat_ctx.get_history_from_event(event)
    #     who = self.member_man.get_name_from_id(event.sender.id, await self.achv.get_raw_member_name())
    #     try:
    #         def map_text(c: MessageComponent):
    #             if isinstance(c, Plain):
    #                 return c.text.replace('你', who)
    #             elif isinstance(c, str):
    #                 return c.replace('你', who)
    #             return c
    #         text = "".join([map_text(m) for m in msg])
    #         await history.append_system_msg(f'请按照你的设定的说话方式向{who}说以下内容【{text}】, 请复述:')
    #         resp = await self.chat(history)
    #         await self.ai_ext.as_chat_seq(mc=resp)
    #         return
    #     except:
    #         ...
    #     return [f'{who}{"".join(msg)}~']
    
    # async def response_with_limited_ai(self, event: MessageEvent, msg: List[MessageComponent]):
    #     history = self.chat_ctx.get_history_from_event(event)
    #     who = self.member_man.get_name_from_id(event.sender.id, await self.achv.get_raw_member_name())
    #     try:
    #         def map_text(c: MessageComponent):
    #             if isinstance(c, Plain):
    #                 return c.text.replace('你', who)
    #             elif isinstance(c, str):
    #                 return c.replace('你', who)
    #             return c
    #         text = "".join([map_text(m) for m in msg])
    #         await history.append_system_msg(f'请按照你的设定的说话方式向{who}说以下内容【{text}】, 请复述:')
    #         resp = await self.chat(history, limited_history=True)
    #         await self.ai_ext.as_chat_seq(mc=resp)
    #         return
    #     except:
    #         ...
    #     return [f'{who}{"".join(msg)}~']

    @delegate()
    async def enhanced_run(self, *, comps: list[MessageComponent], recall: bool=False):
        if not await self.ai_ext.check_avaliable(recall=recall): return
        resp = await self.run(chain=MessageChain(comps))
        await self.ai_ext.as_chat_seq(mc=resp)
        await self.ai_ext.mark_invoked()
        ...

    @top_instr('ai|狸花|bot', InstrAttr.NO_ALERT_CALLER)
    async def forced_trigger(self, *comps: MessageComponent):
        await self.enhanced_run(comps=comps, recall=True)
        
    @fall_instr()
    async def chat_instr(self, event: MessageEvent, *comps: MessageComponent):
        ob_mode = True
        if isinstance(event, GroupMessage): 
            history = self.chat_ctx.get_history_from_event(event)
            history.member_speaking_times_during_last_initiative_talk += 1
            history.update_member_last_speak_tsc()
            for c in event.message_chain:
                if isinstance(c, At) and c.target == self.bot.qq:
                    try:
                        await self.enhanced_run(comps=comps)
                        return
                    except: 
                        break
                if isinstance(c, Quote) and c.sender_id == self.bot.qq and self.ai_ext.is_chat_seq_msg(c.id):
                    try:
                        await self.enhanced_run(comps=comps)
                        return
                    except: 
                        break
                    ...
        return await self.run(chain=event.message_chain, ob_mode=ob_mode)

def internal(func: Callable):
    func._gpt_function_internal_ = True
    return func


class MemberMan():
    def __init__(self, members: Dict[int, str]) -> None:
        self.members = members
        pass
    
    def get_name_from_id(self, id: int, _def = None):
        return self.members.get(id, _def)

    def get_id_from_name(self, name: str, _def = None):
        return next(iter([k for k,v in self.members.items() if v == name]), _def)

mako_lookup = TemplateLookup(directories=[Plugin.path.data])
bot_profile = PImage.open(Plugin.path.data.of_file('test.jpg'))

class History(ABC):
    ctx: 'ChatContextMan'
    origin: list
    id: int
    last_chat_tsc: int # 单位: 秒

    def __init__(self, ctx: 'ChatContextMan', id: int) -> None:
        self.ctx = ctx
        self.origin = []
        self.id = id
        self.last_chat_tsc = 0

    async def append_system_msg(self, content):
        localtime = time.localtime()
        week_list = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        time_str = f"{{system}}时间: {time.strftime('%Y年%m月%d日 %H时%M分%S秒',localtime)} {week_list[localtime.tm_wday]}"
        await self.append({"role": "system", "content": f"{time_str}\n{content}"})

    async def append(self, v):
        self.origin.append(v)
        if len(self.origin) > 34:
            # 找到20条内第一个system
            self.origin = self.origin[-34:]
            while self.origin[0]['role'] != 'system':
                self.origin.pop(0)
        await self._update_log_file()

    async def pop(self):
        self.origin.pop()
        await self._update_log_file()
    
    async def clear(self):
        self.origin.clear()
        await self._update_log_file()

    def update_last_chat_tsc(self):
        self.last_chat_tsc = time.time()

    async def _update_log_file(self):
        ...
        # async with aiofile.async_open(Plugin.path.data[Dir.logs].of_file(f'{self._get_log_filename_prefix()}.{self.id}.log.json'), 'wt', encoding='utf-8') as f:
        #     await f.write(json.dumps(self._get_log_content(), indent=2, ensure_ascii=False))

    async def merged(self, *, limited_history=False) -> list:
        if limited_history:
            return [
                {"role": "system", "content": await self._get_banner()},
                *self.origin[-1:],
            ]
        else:
            return [
                {"role": "system", "content": await self._get_banner()},
                *self.origin,
            ]

    async def _get_raw_banner(self) -> str:
        obtained_achvs = None
        current_member_name = None
        try: 
            current_member_name = await self.ctx.outer.get_current_member_name()
            obtained_achvs = await self.ctx.outer.achv.get_obtained()
        except: ...
        
        return (
            mako_lookup
                .get_template(self._get_banner_filename())
                .render(
                    news=self.ctx.sample_news(),
                    motions=self.ctx.motions,
                    curr_time=time.strftime('%Y年%m月%d日 %H时%M分%S秒',time.localtime()),
                    rarities=AchvRarity,
                    all_achvs=self.ctx.outer.achv.get_registed_achvs(),
                    obtained_achvs=obtained_achvs,
                    current_member_name=current_member_name,
                    festival_countdowns=self.ctx.outer.festival.get_countdowns()
                )
        )

    async def _get_banner(self) -> list:
        def img_op(s, ctx):
            img_path = Plugin.path.data.of_file(s)
            return PImage.open(img_path)
        
        return breakdown_chain_sync(
            await self._get_raw_banner(),
            r'\[img:(.*?)\]',
            img_op
        )

    @abstractmethod
    def _get_banner_filename(self) -> str: ...

    @abstractmethod
    def _get_log_filename_prefix(self) -> str: ...

    async def _get_log_content(self):
        return {
            'messages': await self.merged(),
            'last_chat_tsc': self.last_chat_tsc
        }

class FriendHistory(History):
    def _get_banner_filename(self) -> str:
        return 'init.group.mako'
    
    def _get_log_filename_prefix(self) -> str:
        return 'fri'

class GroupHistory(History):
    member_speaking_times_during_last_initiative_talk: int
    member_last_speak_tsc: int
    initiative_talk_prob: float
    last_initiative_talk_prob_update_tsc: float

    def __init__(self, ctx: 'ChatContextMan', id: int) -> None:
        self.member_speaking_times_during_last_initiative_talk = 0
        self.member_last_speak_tsc = 0
        self.initiative_talk_prob = 0
        self.last_initiative_talk_prob_update_tsc = 0
        super().__init__(ctx, id)

    def update_member_last_speak_tsc(self):
        self.member_last_speak_tsc = time.time()

    def set_initiative_talk_prob(self, val: float):
        self.initiative_talk_prob = val

    def set_last_initiative_talk_prob_update_tsc(self, val: float):
        self.last_initiative_talk_prob_update_tsc = val

    def _get_banner_filename(self) -> str:
        return 'init.group.mako'
    
    def _get_log_filename_prefix(self) -> str:
        return 'group'
    
    async def _get_log_content(self):
        return {
            **await super()._get_log_content(),
            'mstdlit': self.member_speaking_times_during_last_initiative_talk,
            'itprob': self.initiative_talk_prob,
            'litptsc': self.last_initiative_talk_prob_update_tsc
        }

class ChatContextMan():
    news: List[str]
    groups: Dict[int, GroupHistory]
    friends: Dict[int, FriendHistory]
    outer: 'Gpt'

    def __init__(self, outer: 'Gpt') -> None:
        self.news = []
        self.groups = {}
        self.friends = {}
        self.outer = outer

    def get_group_history(self, group_id: int) -> GroupHistory:
        if group_id not in self.groups:
            self.groups[group_id] = GroupHistory(self, group_id)
        return self.groups[group_id]

    def get_friend_history(self, qq_id: int) -> FriendHistory:
        if qq_id not in self.friends:
            self.friends[qq_id] = FriendHistory(self, qq_id)
        return self.friends[qq_id]

    def get_history_from_event(self, event: Event):
        if isinstance(event, NudgeEvent):
            if event.subject.kind == 'Group':
                return self.get_group_history(event.subject.id)
            else:
                return self.get_friend_history(event.subject.id)
        elif isinstance(event, MessageEvent):
            if isinstance(event, GroupMessage):
                return self.get_group_history(event.group.id)
            else:
                return self.get_friend_history(event.sender.id)
        else:
            raise NotImplementedError('not impl')
        
    @property
    def motions(self):
        return [f'[表情:{Path(x).stem}]' for x in glob.glob(Plugin.path.data[Dir.motions].of_file('*'))]

    def sample_news(self, *, count=10):
        return random.sample(self.news, min(count, len(self.news)))

    async def update_news(self):
        self.news = await self._fetch_news()

    async def _fetch_news(self):
        async with aiohttp.ClientSession() as session:
            async with session.get('https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc') as response:
                j = await response.json()
                return [e['Title'] for e in j['data']]

