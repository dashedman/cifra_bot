#standart libs
import asyncio
import time
import sys
import os
import logging
import json
import re

from logging.handlers import RotatingFileHandler
from configparser import ConfigParser
from pprint import pprint, pformat

#external libs
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from aiogram import Bot, Dispatcher, types
from aiogram.types.inline_keyboard import InlineKeyboardMarkup, InlineKeyboardButton as IKB
from aiogram.types.reply_keyboard import ReplyKeyboardMarkup, KeyboardButton as RKB
from aiogram.dispatcher.filters.builtin import IDFilter
from aiogram.utils.executor import start_polling
from aiogram.utils.exceptions import MessageNotModified, TelegramAPIError, UserDeactivated, RetryAfter, ChatNotFound, BotBlocked

from streamlink import Streamlink, StreamError, PluginError, NoPluginError

#internal libs
import ui_constants as uic



#configs
if not os.path.exists("config.ini"):
    print(uic.NO_CONFIG_MESSAGE)
    exit()

CONFIGS = ConfigParser()
CONFIGS.read("config.ini")

#logining
file_log = RotatingFileHandler("logs.log", mode='a', maxBytes=10240, backupCount=5)
console_out = logging.StreamHandler()

logging.basicConfig(
    handlers=(file_log, console_out),
    format='[%(asctime)s | %(levelname)s] %(name)s: %(message)s',
    datefmt='%b %d %H:%M:%S %Y',
    level=int(CONFIGS['logging']['level']))
LOGGER = logging.getLogger("bot")

#StreamLink Session
SLS = Streamlink()
#SLS.load_plugins(CONFIGS['streamlink']['plugins'])
SLS.set_plugin_option("twitch", "disable_hosting", True)
SLS.set_plugin_option("twitch", "disable_reruns", True)
SLS.set_plugin_option("twitch", "disable-ads", True)

#classes
class MyConnection(Connection):
    def __enter__(self):
        if not self.open:
            self.ping(reconnect=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        if exc_val:
            raise

#fuctions
def getStream(arguments, db, cur):
    page_number = int(arguments[0])
    arguments = arguments[1:]

    if(len(arguments) >= 5):
        cur.execute("""
            SELECT file_id, caption FROM streams WHERE author = %s AND year = %s AND month = %s AND day = %s AND part = %s
        """, arguments)
    else:
        cur.execute("""
            SELECT file_id, caption FROM streams WHERE author = %s AND year = %s AND month = %s AND day = %s
        """, arguments)
    return cur.fetchone()

def getVideo(id, db, cur):
    cur.execute("""
        SELECT file_id, caption FROM videos WHERE id = %s
    """, id)
    return cur.fetchone()

def getLastStream(arguments, db, cur):
    keys = []
    author = arguments[1]

    cur.execute("""
        SELECT file_id, caption, udata, year, month, day, part FROM streams WHERE author = %s ORDER BY udata DESC, part ASC
    """, [author])
    result = cur.fetchone()
    if(result['part']):
        keys.append([IKB(
            text=f"{result['caption']}",
            callback_data=f"1@{author}@{result['year']}@{result['month']}@{result['day']}@{result['part']}"
        )])
    else:
        keys.append([IKB(
            text=f"{result['caption']}",
            callback_data=f"1@{author}@{result['year']}@{result['month']}@{result['day']}"
        )])

    if result:
        udata = result['udata']

        while (result := cur.fetchone()) and (result['udata'] >= udata):
            if(result['part']):
                keys.append([IKB(
                    text=f"{result['caption']}",
                    callback_data=f"1@{author}@{result['year']}@{result['month']}@{result['day']}@{result['part']}"
                )])
            else:
                keys.append([IKB(
                    text=f"{result['caption']}",
                    callback_data=f"1@{author}@{result['year']}@{result['month']}@{result['day']}"
                )])

    #add control buttons
    keys.append([])

    keys[-1].append(IKB(text=uic.BACK, callback_data=f"1@{author}")) #back button
    keys[-1].append(IKB(text=uic.REFRESH, callback_data=f"last@{author}")) #refresh button

    return InlineKeyboardMarkup(inline_keyboard = keys)

def getKeyboard(arguments, db, cur):
    page_number = int(arguments[0])
    arguments = arguments[1:]
    keys = []

    #select mysql request
    if(len(arguments) == 0):
        cur.execute("""
            SELECT DISTINCT author FROM streams
        """)
        results = cur.fetchall()

        for result in results[(page_number-1)*10:page_number*10]:
            keys.append([IKB(
                text=result['author'],
                callback_data=f"1@{result['author']}"
            )])

        #add bonus button with videos
        keys.append([IKB(
            text=uic.VIDEOS,
            callback_data=f"videos@1"
        )])

    elif(len(arguments) == 1):
        cur.execute(f"""
            SELECT DISTINCT year FROM streams WHERE author = %s ORDER BY year DESC
        """, arguments)
        results = cur.fetchall()

        for result in results[(page_number-1)*10:page_number*10]:
            keys.append([IKB(
                text=result['year'],
                callback_data=f"1@{arguments[0]}@{result['year']}"
            )])

        keys.append([IKB(
            text=uic.LATESTS,
            callback_data=f"last@{arguments[0]}"
        )])

    elif(len(arguments) == 2):
        cur.execute(f"""
            SELECT DISTINCT month FROM streams WHERE author = %s AND year = %s ORDER BY month ASC
        """, arguments)
        results = cur.fetchall()

        for result in results[(page_number-1)*10:page_number*10]:
            keys.append([IKB(
                text=result['month'],
                callback_data=f"1@{'@'.join(arguments)}@{result['month']}"
            )])

    elif(len(arguments) == 3):
        cur.execute(f"""
            SELECT caption, day, part FROM streams WHERE author = %s AND year = %s AND month = %s ORDER BY day ASC, part ASC
        """, arguments)
        results = cur.fetchall()
        for result in results[(page_number-1)*10:page_number*10]:
            if(result['part']):
                keys.append([IKB(
                    text=f"{result['caption']}",
                    callback_data=f"1@{'@'.join(arguments)}@{result['day']}@{result['part']}"
                )])
            else:
                keys.append([IKB(
                    text=f"{result['caption']}",
                    callback_data=f"1@{'@'.join(arguments)}@{result['day']}"
                )])


    #add control buttons
    keys.append([])

    if(len(arguments) == 0):
        keys[-1].append(IKB(text=uic.REFRESH, callback_data=f"1")) #back button
    elif(len(arguments) == 1):
        keys[-1].append(IKB(text=uic.BACK, callback_data=f"1")) #back button
    else:
        keys[-1].append(IKB(text=uic.BACK, callback_data=f"1@{'@'.join(arguments[:-1])}")) #back button

    keys[-1].append( #previos page button
        IKB(text=uic.PREV, callback_data=f"{page_number-1}@{'@'.join(arguments)}")
        if page_number>1
        else IKB(text=uic.STOP, callback_data=f"pass")
    )
    keys[-1].append(IKB(text=f"{page_number}", callback_data=f"pass"))# info page button
    keys[-1].append( #next page button
        IKB(text=uic.NEXT, callback_data=f"{page_number+1}@{'@'.join(arguments)}")
        if page_number <= len(results)//10
        else IKB(text=uic.STOP, callback_data=f"pass")
    )

    return InlineKeyboardMarkup(inline_keyboard = keys)

def getFinderKeyboard(expresion, page, db, cur):
    page = int(page)
    keys = []


    #select mysql request
    cur.execute(f"""
        SELECT caption, author, day, month, year, part FROM streams WHERE caption LIKE %s ORDER BY udata DESC, part ASC
    """, [f"%{expresion}%"])

    results = cur.fetchall()
    if not results: return None

    for result in results[(page-1)*10:page*10]:
        if(result['part']):
            keys.append([IKB(
                text=f"{result['caption']}",
                callback_data=f"1@{result['author']}@{result['year']}@{result['month']}@{result['day']}@{result['part']}"
            )])
        else:
            keys.append([IKB(
                text=f"{result['caption']}",
                callback_data=f"1@{result['author']}@{result['year']}@{result['month']}@{result['day']}"
            )])


    #add control buttons
    keys.append([])

    keys[-1].append( #previos page button
        IKB(text=uic.PREV, callback_data=f"find@{expresion}@{page-1}")
        if page>1
        else IKB(text=uic.STOP, callback_data=f"pass")
    )
    keys[-1].append(IKB(text=f"{page}", callback_data=f"pass"))# info page button
    keys[-1].append( #next page button
        IKB(text=uic.NEXT, callback_data=f"find@{expresion}@{page+1}")
        if page <= len(results)//10
        else IKB(text=uic.STOP, callback_data=f"pass")
    )

    return InlineKeyboardMarkup(inline_keyboard = keys)

def getVideosKeyboard(page, db, cur):
    page = int(page)
    keys = []

    #select mysql request
    cur.execute("""
        SELECT id, caption FROM videos ORDER BY vorder ASC
    """)
    results = cur.fetchall()

    for result in results[(page-1)*10:page*10]:
        keys.append([IKB(
            text=result['caption'],
            callback_data=f"video@{result['id']}"
        )])

    #add control buttons
    keys.append([])

    keys[-1].append(IKB(text=uic.BACK, callback_data=f"1")) #back button

    keys[-1].append( #previos page button
        IKB(text=uic.PREV, callback_data=f"videos@{page-1}")
        if page>1
        else IKB(text=uic.STOP, callback_data=f"pass")
    )
    keys[-1].append(IKB(text=f"{page}", callback_data=f"pass"))# info page button
    keys[-1].append( #next page button
        IKB(text=uic.NEXT, callback_data=f"videos@{page+1}")
        if page <= len(results)//10
        else IKB(text=uic.STOP, callback_data=f"pass")
    )

    return InlineKeyboardMarkup(inline_keyboard = keys)

def getBottomKeyboard(db, cur):
    return ReplyKeyboardMarkup(
        [[RKB(uic.BOTTOM_KEYBOARD)]],
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False
    )

def addStream(args, reply, db, cur):
    streamer = args[0]
    date = time.strptime(args[1], "%d.%m.%Y")
    unix_data = time.mktime(date)
    part = args[2] if len(args)>=3 else None

    if not reply: return False
    if not reply.caption: return False
    if not reply.video: return False

    if part:
        cur.execute("""
            INSERT INTO streams(
                author,
                udata, year, month, day,
                file_id, caption, part
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
        """, [
            streamer,
            unix_data, date.tm_year, date.tm_mon, date.tm_mday,
            reply.video.file_id, reply.caption, part
        ])

    else:
        cur.execute("""
            INSERT INTO streams(
                author,
                udata, year, month, day,
                file_id, caption
            ) VALUES(%s,%s,%s,%s,%s,%s,%s)
        """, [
            streamer,
            unix_data, date.tm_year, date.tm_mon, date.tm_mday,
            reply.video.file_id, reply.caption
        ])
    db.commit()

    return True

def delStream(caption, db, cur):
    cur.execute("""
        DELETE FROM streams
        WHERE caption=%s
        LIMIT 1
    """, [caption])
    db.commit()

    return True

def addVideo(args, reply, db, cur):
    vorder = args[0]

    if not reply: return False
    if not reply.caption: return False
    if not reply.video: return False

    cur.execute("""
        INSERT INTO videos(
            vorder,
            file_id, caption
        ) VALUES(%s,%s,%s)
    """, [
        vorder,
        reply.video.file_id, reply.caption
    ])
    db.commit()

    return True

def delVideo(caption, db, cur):
    cur.execute("""
        DELETE FROM videos
        WHERE caption=%s
        LIMIT 1
    """, [caption])
    db.commit()

    return True

def addChat(chat_id, platform, streamer_id, db, cur):
    cur.execute("""
        INSERT INTO chats(
            id, platform, streamer_id
        ) VALUES(%s,%s,%s)
    """, [
        chat_id, platform, streamer_id
    ])
    db.commit()

    return True

def delChat(chat_id, platform, streamer_id, db, cur):
    cur.execute("""
        DELETE FROM chats
        WHERE id=%s AND platform=%s AND streamer_id=%s
    """, [chat_id, platform, streamer_id])
    db.commit()

    return True

def get_streamers():
    with open(CONFIGS['streamlink']['streamers'],"r",encoding='utf-8') as f:
        return json.load(f)

def set_streamers(streamers_update):
    with open(CONFIGS['streamlink']['streamers'],"w",encoding='utf-8') as f:
        json.dump(streamers_update, f, indent = 4)

def getNotifKeyboard(chat_id, page, db, cur):
    page = int(page)
    keys = []

    def in_notif(streamer, notifs):
        for notif in notifs:
            if(notif['platform'] == streamer['platform'] and notif['streamer_id'] == streamer['id']):
                return True
        return False
    #select notif from sql
    cur.execute("""
        SELECT platform, streamer_id FROM chats WHERE id=%s
    """, [chat_id])
    notifications = cur.fetchall()

    #select streamers from json
    streamers = get_streamers()
    for streamer in streamers:#[(page-1)*10:page*10]
        notif_on = in_notif(streamer, notifications)

        keys.append([IKB(
            text=f"{uic.YES if notif_on else uic.NO} {streamer['name']}",
            callback_data=f"notification@{1 if notif_on else 0}@{streamer['platform']}@{streamer['id']}"
        )])
    """
        #add control buttons
        keys.append([])

        keys[-1].append( #previos page button
            IKB(text=uic.PREV, callback_data=f"notifset@{page-1}")
            if page>1
            else IKB(text=uic.STOP, callback_data=f"pass")
        )
        keys[-1].append(IKB(text=f"{page}", callback_data=f"pass"))# info page button
        keys[-1].append( #next page button
            IKB(text=uic.NEXT, callback_data=f"notifset@{page+1}")
            if page <= len(streamers)//10
            else IKB(text=uic.STOP, callback_data=f"pass")
        )
    """
    return InlineKeyboardMarkup(inline_keyboard = keys)


async def broadcastStream(bot, streamer, text, db):

    async def stableSend(chat_id, text):
        try:
            await bot.send_message(chat_id, text)
        except BotBlocked:
            log.error(f"Target [ID:{chat_id}]: blocked by user")
            with db, db.cursor() as cur:
                delChat(chat_id, streamer['platform'], streamer['id'], db, cur)
        except ChatNotFound:
            log.error(f"Target [ID:{chat_id}]: invalid ID")
            with db, db.cursor() as cur:
                delChat(chat_id, streamer['platform'], streamer['id'], db, cur)
        except RetryAfter as e:
            log.error(f"Target [ID:{chat_id}]: Flood limit is exceeded. Sleep {e.timeout} seconds.")
            await asyncio.sleep(e.timeout)
            return await stableSend(chat_id, text)  # Recursive call
        except UserDeactivated:
            log.error(f"Target [ID:{chat_id}]: user is deactivated")
            with db, db.cursor() as cur:
                delChat(chat_id, streamer['platform'], streamer['id'], db, cur)
        except TelegramAPIError:
            log.exception(f"Target [ID:{chat_id}]: failed")
        else:
            return True
        return False


    LOGGER.info(f"Broadcast for {streamer['name']}...")

    with db, db.cursor() as cur:
        cur.execute("""
            SELECT id FROM chats WHERE platform=%s AND streamer_id=%s
        """, [streamer['platform'], streamer['id']])
        recipients = cur.fetchall()

    successfull_counter = 0
    for recipient in recipients:
        if await stableSend(recipient['id'], text):
            successfull_counter += 1

        await asyncio.sleep(0.04)

    if(successfull_counter == len(recipients)):
        LOGGER.info(f"Broadcast succesfull!")
    else:
        LOGGER.warning(f"Broadcast losses: {len(recipients) - successfull_counter} to {len(recipients)}!")

async def streams_demon(bot, db):

    async def check_stream(streamer, trusted_deep=3):
        url = f"{streamer['platform']}/{streamer['id']}"
        LOGGER.debug(f"Checking stream for {streamer['name']} platform:{streamer['platform']} id:{streamer['id']}")
        #рекурсивная проверка
        #для удобства квостовая рекурсия переделана в цикл
        async def cicle_check():
            level = 1
            while(level <= trusted_deep):
                #если глубина проверки больше дозволеной то стрим оффлайн
                try:
                    #Воспользуемся API streamlink'а. Через сессию получаем инфу о стриме. Если инфы нет - то считаем за офлайн.
                    if SLS.streams(url):
                        return True #online
                except PluginError as err:
                    #если проблемы с интернетом
                    await asyncio.sleep(60)
                level += 1
                #если говорит что стрим оффлайн проверим еще раз
            return False

        return (await cicle_check()), streamer

    #online profilactic
    streamers = get_streamers()
    for streamer in streamers:
        streamer['online'] = True
    set_streamers(streamers)

    while ALIVE:
        UPDATE_FLAG = False
        streamers = get_streamers()
        chekers = {check_stream(streamer, 2) for streamer in streamers}

        for cheker in asyncio.as_completed(chekers):
            online, streamer = await cheker

            if online and not streamer["online"]:
                await broadcastStream(bot, streamer, uic.build_stream_text(streamer), db)

            if(streamer["online"] != online):
                UPDATE_FLAG = True
            streamer["online"] = online

        if UPDATE_FLAG: set_streamers(streamers)

        await asyncio.sleep(30)


#main function
def start():
    LOGGER.info("Starting...")

    database = MyConnection(
        host=f"{CONFIGS['data-base']['host']}",
        user=CONFIGS['data-base']['login'],
        password=CONFIGS['data-base']['password'],
        database=CONFIGS['data-base']['name'],
        cursorclass=DictCursor
    )
    with database, database.cursor() as dbcursor:
        dbcursor.execute("""
            CREATE TABLE IF NOT EXISTS streams (
                id      Int             NOT NULL PRIMARY KEY AUTO_INCREMENT,
                author  Varchar(64)     NOT NULL,
                udata   Int             NOT NULL,
                year    Int             NOT NULL,
                month   TinyInt         NOT NULL,
                day     TinyInt         NOT NULL,
                file_id Varchar(255)    NOT NULL,
                caption Varchar(1024)   NOT NULL,
                part    TinyInt         NULL
            )
        """)
        dbcursor.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id      Int             NOT NULL PRIMARY KEY AUTO_INCREMENT,
                file_id Varchar(255)    NOT NULL,
                caption Varchar(1024)   NOT NULL,
                vorder  Int             NULL
            )
        """)
        dbcursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id          BigInt          NOT NULL,
                platform    Varchar(64)     NOT NULL,
                streamer_id Varchar(64)     NOT NULL
            )
        """)
        database.commit()

    bot = Bot(token=CONFIGS['telegram']['token'])
    dispatcher = Dispatcher(bot)

    #bot handlers
    @dispatcher.message_handler(commands=["start"])
    async def start_handler(message: types.Message):
        #processing command /start
        #get streamers from db
        #and
        #construct keyboard
        with database, database.cursor() as dbcursor:
            keyboard = getKeyboard([1], database, dbcursor)
        await message.reply(uic.START_CMD, reply_markup=keyboard)

    @dispatcher.message_handler(commands=["help"])
    async def help_handler(message: types.Message):
        #processing command /help
        await message.reply(uic.HELP_CMD)

    @dispatcher.message_handler(commands=["notifications"])
    async def notifications_handler(message: types.Message):
        #processing command /notifications
        #get streamers from json
        #and
        #construct keyboard
        with database, database.cursor() as dbcursor:
            keyboard = getNotifKeyboard(message.chat.id, 1, database, dbcursor)
        await message.reply(uic.NOTIFICATIONS_CMD, reply_markup=keyboard)

    @dispatcher.message_handler(commands=["find"])
    async def notifications_handler(message: types.Message):
        #processing command /find
        #get streams from db
        #and
        #construct keyboard
        command, expresion = message.get_full_command()
        if(len(expresion) < 3 or len(expresion) > 30):
            await message.reply(uic.FIND_NO_ARGS)
            return
        my_message = await message.reply(uic.WAIT)

        with database, database.cursor() as dbcursor:
            keyboard = getFinderKeyboard(expresion, 1, database, dbcursor)
        try:
            if keyboard:
                await my_message.edit_text(uic.FINDED, reply_markup=keyboard)
            else:
                await my_message.edit_text(uic.NOT_FOUND)
        except MessageNotModified:
            pass
        return

    @dispatcher.message_handler(commands=["info"])
    async def send_info(message: types.Message):
        await message.answer("```"+pformat(message.to_python())+"```", parse_mode="markdown")


    #DASHBOARD COMMANDS
    dashboard_filter = IDFilter(chat_id=CONFIGS['telegram']['dashboard'])
    @dispatcher.message_handler(dashboard_filter, commands=["vipinfo"])
    async def send_info(message: types.Message):
        await message.answer("```"+pformat(message.to_python())+"```", parse_mode="markdown")

    @dispatcher.message_handler(dashboard_filter, commands=["add"])
    async def add_handler(message: types.Message):
        #processing command /add streamer data [, part]
        #get streamers from db
        #and
        #construct keyboard
        command, args = message.get_full_command()
        args = re.sub(r"\\\s","@@",args)
        args = args.split()
        args = [re.sub(r"@@"," ",arg) for arg in args]

        succsces = None
        with database, database.cursor() as dbcursor:
            succsces = addStream(args, message.reply_to_message, database, dbcursor)

        if succsces:
            await message.reply(uic.ADDED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["addv"])
    async def addv_handler(message: types.Message):
        #processing command /add streamer data [, part]
        #get streamers from db
        #and
        #construct keyboard
        command, args = message.get_full_command()
        args = re.sub(r"\\\s","@@",args)
        args = args.split()
        args = [re.sub(r"@@"," ",arg) for arg in args]

        succsces = None
        with database, database.cursor() as dbcursor:
            succsces = addVideo(args, message.reply_to_message, database, dbcursor)

        if succsces:
            await message.reply(uic.ADDED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["del"])
    async def del_handler(message: types.Message):
        #processing command /del caption
        command, caption = message.get_full_command()

        succsces = None
        with database, database.cursor() as dbcursor:
            succsces = delStream(caption, database, dbcursor)

        if succsces:
            await message.reply(uic.DELETED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["delv"])
    async def delv_handler(message: types.Message):
        #processing command /del caption
        #get streamers from db
        #and
        #construct keyboard
        command, caption = message.get_full_command()
        succsces = None
        with database, database.cursor() as dbcursor:
            succsces = delVideo(caption, database, dbcursor)

        if succsces:
            await message.reply(uic.DELETED)
        else:
            await message.reply(uic.WRONG)


    @dispatcher.message_handler()
    async def unknow_cmd(message: types.Message):
        await message.answer(uic.UNKNOW_CMD)

    #CALLBACK
    @dispatcher.callback_query_handler()
    async def button_handler(callback_query: types.CallbackQuery):
        args = callback_query.data.split("@")
        if(args[0] == 'pass'): return

        if(args[0] == 'notification'):
            #args[1] - is on notif
            #args[2] - platform
            #args[3] - streamer
            with database, database.cursor() as dbcursor:
                if(not bool(int(args[1]))):
                    addChat(callback_query.message.chat.id, args[2], args[3], database, dbcursor)
                else:
                    delChat(callback_query.message.chat.id, args[2], args[3], database, dbcursor)

                keyboard = getNotifKeyboard(callback_query.message.chat.id, 1, database, dbcursor)
            try:
                await callback_query.message.edit_text(uic.NOTIFICATIONS_CMD, reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if(args[0] == 'notifset'):#args[1] = page
            with database, database.cursor() as dbcursor:
                keyboard = getNotifKeyboard(callback_query.message.chat.id, args[1], database, dbcursor)
            await callback_query.message.edit_text(uic.NOTIFICATIONS_CMD, reply_markup=keyboard)
            return

        if(args[0] == 'videos'): #args[1] = page
            with database, database.cursor() as dbcursor:
                keyboard = getVideosKeyboard(args[1], database, dbcursor)

            try:
                await callback_query.message.edit_text(uic.VIDEOS, reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if(args[0] == 'video'): #args[1] = id
            await callback_query.message.chat.do('upload_video')

            with database, database.cursor() as dbcursor:
                video = getVideo(args[1], database, dbcursor)
            if video:
                await callback_query.message.answer_video(video=video['file_id'], caption=video['caption'])
            else:
                await callback_query.message.answer(uic.NOT_FOUND)
            return

        if(args[0] == 'find'): # args[1] = expr; args[2] = page
            await callback_query.answer(uic.WAIT, show_alert=False)

            with database, database.cursor() as dbcursor:
                keyboard = getFinderKeyboard(args[1], args[2], database, dbcursor)

            try:
                if keyboard:
                    await callback_query.message.edit_text(uic.FINDED, reply_markup=keyboard)
                else:
                    await callback_query.message.edit_text(uic.NOT_FOUND)

            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if(args[0] == 'last'):
            with database, database.cursor() as dbcursor:
                keyboard = getLastStream(args, database, dbcursor)
            try:
                await callback_query.message.edit_text(uic.LATESTS, reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if(len(args) < 5):
            with database, database.cursor() as dbcursor:
                keyboard = getKeyboard(args, database, dbcursor)
            try:
                await callback_query.message.edit_text(uic.PICK_MSG[len(args)-1], reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)

        else:
            await callback_query.message.chat.do('upload_video')

            with database, database.cursor() as dbcursor:
                video = getStream(args, database, dbcursor)
            if video:
                await callback_query.message.answer_video(video=video['file_id'], caption=video['caption'])
            else:
                await callback_query.message.answer(uic.NOT_FOUND)

    demons = []
    async def on_startup(dispatcher):
        global ALIVE
        ALIVE = True
        LOGGER.info("Starting demons...")
        demons.append(
            asyncio.create_task(streams_demon(bot, database))
        )

        LOGGER.info("Listening...")

    async def on_shutdown(dispatcher):
        LOGGER.info("Shutdown... Please wait!")
        global ALIVE
        ALIVE = False
        for demon in demons:
            demon.cancel()



    start_polling(
        dispatcher,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown
    )

#start
if __name__ == "__main__":
    start()
