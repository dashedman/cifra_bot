#standart libs
import asyncio
import time
import sys
import os
import logging
import json
import re

#standart libs parts
from logging.handlers import RotatingFileHandler
from configparser import ConfigParser
from pprint import pprint, pformat

#external libs
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_polling
from aiogram.utils.exceptions import MessageNotModified
from aiogram.types.inline_keyboard import InlineKeyboardMarkup, InlineKeyboardButton as IKB
from aiogram.types.reply_keyboard import ReplyKeyboardMarkup, KeyboardButton as RKB

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
file_log = RotatingFileHandler("logs.log", mode='a', maxBytes=5120, backupCount=5)
console_out = logging.StreamHandler()

logging.basicConfig(
    handlers=(file_log, console_out),
    format='[%(asctime)s | %(levelname)s] %(name)s: %(message)s',
    datefmt='%b %d %H:%M:%S %Y',
    level=int(CONFIGS['logging']['level']))
LOGGER = logging.getLogger("bot")

#StreamLink Session
SLS = Streamlink()
SLS.load_plugins(CONFIGS['streamlink']['plugins'])
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
def getVideo(arguments, db, cur):
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


async def sendStream(bot, streamer, text, db):
    LOGGER.info(f"Sending for {streamer['name']}...")

    with db, db.cursor() as cur:
        cur.execute("""
            SELECT id FROM chats WHERE platform=%s AND streamer_id=%s
        """, [streamer['platform'], streamer['id']])
        recipients = cur.fetchall()

    senders = [
        asyncio.create_task(
            bot.send_message(recipient['id'], text)
        ) for recipient in recipients
    ]

    await asyncio.wait(senders)
    LOGGER.info(f"Sending succesfull!")

async def streams_demon(bot, db):

    async def check_stream(streamer, trusted_deep=3):
        url = f"{streamer['platform']}/{streamer['id']}"
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
                    continue
                level += 1
                #если говорит что стрим оффлайн проверим еще раз
            return False

        return await cicle_check()

    #online profilactic
    streamers = get_streamers()
    for streamer in streamers:
        streamer['online'] = True
    set_streamers(streamers)

    while ALIVE:
        UPDATE_FLAG = False
        for streamer in (streamers := get_streamers()):
            online = await check_stream(streamer, 2)

            if online and not streamer["online"]:
                await sendStream(bot, streamer, uic.build_stream_text(streamer), db)

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

    @dispatcher.message_handler(commands=["info"])
    async def send_info(message: types.Message):
        await message.answer("```"+pformat(message.to_python())+"```", parse_mode="markdown")

    @dispatcher.message_handler(commands=["add"])
    @dispatcher.message_handler(lambda message: message.chat.id == CONFIGS['telegram']['dashboard'])
    async def add_handler(message: types.Message):
        #processing command /add streamer data [, part]
        #get streamers from db
        #and
        #construct keyboard
        command, args = message.get_full_command()
        args = re.sub(r"\\\s","@@",args)
        args = args.split()
        args = [re.sub(r"@@"," ",arg) for arg in args]

        with database, database.cursor() as dbcursor:
            succsces = addStream(args, message.reply_to_message, database, dbcursor)

        if succsces:
            await message.reply(uic.ADDED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(commands=["del"])
    @dispatcher.message_handler(lambda message: message.chat.id == CONFIGS['telegram']['dashboard'])
    async def del_handler(message: types.Message):
        #processing command /del caption
        #get streamers from db
        #and
        #construct keyboard
        command, caption = message.get_full_command()
        with database, database.cursor() as dbcursor:
            succsces = delStream(caption, database, dbcursor)

        if succsces:
            await message.reply(uic.DELETED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler()
    async def unknow_cmd(message: types.Message):
        await message.answer(uic.UNKNOW_CMD)

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
            with database, database.cursor() as dbcursor:
                video = getVideo(args, database, dbcursor)
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
            await asyncio.wait_for(demon, None)



    start_polling(
        dispatcher,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown
    )

#start
if __name__ == "__main__":
    start()
