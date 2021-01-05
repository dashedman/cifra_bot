#standart libs
import asyncio
import sqlite3
import time
import re
import argparse
import json
import sys
import os
import html
import ssl
import logging

#standart libs parts
from configparser import ConfigParser
from pprint import pprint, pformat
from collections import namedtuple, deque
from copy import deepcopy
from functools import partial
from random import randint

#external libs
import pymysql
from pymysql.cursors import DictCursor

from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_polling
from aiogram.types.inline_keyboard import InlineKeyboardMarkup, InlineKeyboardButton as IKB

from aiogram.utils.exceptions import MessageNotModified

#internal libs
import ui_constants as uic

#configs
if not os.path.exists("config.ini"):
    print(uic.NO_CONFIG_MESSAGE)
    exit()

CONFIGS = ConfigParser()
CONFIGS.read("config.ini")

#logining
file_log = logging.FileHandler("botlogs.log", mode = "w")
console_out = logging.StreamHandler()

logging.basicConfig(
    handlers=(file_log, console_out),
    format='[%(asctime)s | %(levelname)s] %(name)s: %(message)s',
    datefmt='%b %d %H:%M:%S %Y',
    level=int(CONFIGS['logging']['level']))
LOGGER = logging.getLogger("bot")


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

def getLastVideo(arguments, db, cur):
    cur.execute("""
        SELECT file_id, caption FROM streams WHERE author = %s ORDER BY udata DESC
    """, [arguments[1]])
    return cur.fetchone()

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
            text=uic.LAST_STREAM,
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


#main function
def start():
    LOGGER.info("Starting...")

    database = pymysql.connect(
        host=f"{CONFIGS['data-base']['host']}",
        user=CONFIGS['data-base']['login'],
        password=CONFIGS['data-base']['password'],
        database=CONFIGS['data-base']['name'],
        port=CONFIGS['data-base']['port'],
        cursorclass=DictCursor
    )
    dbcursor = database.cursor()
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
        keyboard = getKeyboard([1], database, dbcursor)
        await message.reply(uic.START_CMD, reply_markup=keyboard)

    @dispatcher.message_handler(commands=["add"])
    @dispatcher.message_handler(lambda message: message.chat.id == CONFIGS['telegram']['dashboard'])
    async def add_handler(message: types.Message):
        #processing command /add streamer data [, part]
        #get streamers from db
        #and
        #construct keyboard
        command, args = message.get_full_command()
        args = args.split()
        succsces = addStream(args, message.reply_to_message, database, dbcursor)
        if succsces:
            await message.reply(uic.ADDED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(commands=["del"])
    @dispatcher.message_handler(lambda message: message.chat.id == CONFIGS['telegram']['dashboard'])
    async def add_handler(message: types.Message):
        #processing command /del caption
        #get streamers from db
        #and
        #construct keyboard
        command, caption = message.get_full_command()
        succsces = delStream(caption, database, dbcursor)
        if succsces:
            await message.reply(uic.DELETED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(commands=["info"])
    async def send_info(message: types.Message):
        await message.answer("```"+pformat(message.to_python())+"```", parse_mode="markdown")

    @dispatcher.message_handler()
    async def unknow_cmd(message: types.Message):
        await message.answer(uic.UNKNOW_CMD)

    @dispatcher.callback_query_handler()
    async def button_handler(callback_query: types.CallbackQuery):
        args = callback_query.data.split("@")
        if(args[0] == 'pass'): return

        if(args[0] == 'last'):
            video = getLastVideo(args, database, dbcursor)
            if video:
                await callback_query.message.answer_video(video=video['file_id'], caption=video['caption'])
            else:
                await callback_query.message.answer(uic.NOT_FOUND)
            return

        if(len(args) < 5):
            keyboard = getKeyboard(args, database, dbcursor)
            try:
                await callback_query.message.edit_text(uic.PICK_MSG[len(args)-1], reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)

        else:
            video = getVideo(args, database, dbcursor)
            if video:
                await callback_query.message.answer_video(video=video['file_id'], caption=video['caption'])
            else:
                await callback_query.message.answer(uic.NOT_FOUND)


    async def on_startup(dispatcher):
        LOGGER.info("Listening...")
    async def on_shutdown(dispatcher):
        LOGGER.info("Shutdown...")

    start_polling(
        dispatcher,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown
    )
#start
if __name__ == "__main__":
    start()
