# standart libs
import asyncio
import time
import os
import logging
import json
import re
import random
import traceback
from enum import Enum
# import aiohttp # zya

from logging.handlers import RotatingFileHandler
from configparser import ConfigParser
from pprint import pformat
from typing import Any

import aiofiles as aiofiles
# external libs
from aiohttp_requests import requests

from pymysql.connections import Connection
from pymysql.cursors import DictCursor

import aiogram.utils.markdown as md
from aiogram import Bot, Dispatcher, types
from aiogram.types.inline_keyboard import InlineKeyboardMarkup, InlineKeyboardButton as IKB
from aiogram.dispatcher import DEFAULT_RATE_LIMIT
from aiogram.dispatcher.filters.builtin import IDFilter
from aiogram.dispatcher.handler import CancelHandler, current_handler
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.utils.executor import start_polling
from aiogram.utils.exceptions import MessageNotModified, TelegramAPIError, UserDeactivated, RetryAfter, ChatNotFound, \
    BotBlocked, Throttled, BadRequest
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from streamlink import Streamlink, PluginError

# internal libs
import ui_constants as uic

# configs
if not os.path.exists("config.ini"):
    print(uic.NO_CONFIG_MESSAGE)
    exit()

alive = False

CONFIGS = ConfigParser()
CONFIGS.read("config.ini")

# logining
file_log = RotatingFileHandler("logs.log", mode='a', maxBytes=20480, backupCount=7)
console_out = logging.StreamHandler()

logging.basicConfig(
    handlers=(file_log, console_out),
    format='[%(asctime)s | %(levelname)s] %(name)s: %(message)s',
    datefmt='%b %d %H:%M:%S %Y',
    level=int(CONFIGS['logging']['level'])
)
LOGGER = logging.getLogger("bot")

# StreamLink Session
SLS = Streamlink()
# SLS.load_plugins(CONFIGS['streamlink']['plugins'])
SLS.set_plugin_option("twitch", "disable_hosting", True)
SLS.set_plugin_option("twitch", "disable_reruns", True)
SLS.set_plugin_option("twitch", "disable-ads", True)


class StreamingPlatform(Enum):
    Wasd = 'wasd.tv'
    Twitch = 'twitch.tv'
    Trovo = 'trovo.live'


# classes
class MyConnection(Connection):
    def __enter__(self):
        if not self.open:
            self.ping(reconnect=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class ThrottlingMiddleware(BaseMiddleware):
    """
    Simple middleware
    """

    def __init__(self, throttling_rate_limit=DEFAULT_RATE_LIMIT, key_prefix='antiflood_'):
        self.rate_limit = throttling_rate_limit
        self.prefix = key_prefix
        super(ThrottlingMiddleware, self).__init__()

    async def on_process_message(self, message: types.Message, _):
        """
        This handler is called when dispatcher receives a message

        :param message:
        :param _:
        """

        # Get current handler
        handler = current_handler.get()

        # Get dispatcher from context
        dispatcher = Dispatcher.get_current()
        # If handler was configured, get rate limit and key from handler
        if handler:
            limit = getattr(handler, 'throttling_rate_limit', self.rate_limit)
            key = getattr(handler, 'throttling_key', f"{self.prefix}_{handler.__name__}")
        else:
            limit = self.rate_limit
            key = f"{self.prefix}_message"

        if message.chat.id == CONFIGS['telegram'].getint('dashboard'):
            return
        # Use Dispatcher.throttle method.
        try:
            await dispatcher.throttle(key, rate=limit)
        except Throttled as t:
            # Execute action
            await self.message_throttled(message, t)

            # Cancel current handler
            raise CancelHandler()

    @staticmethod
    async def message_throttled(message: types.Message, throttled: Throttled):
        """
        Notify user only on first exceed and notify about unlocking only on last exceed

        :param message:
        :param throttled:
        """

        # Prevent flooding
        if throttled.exceeded_count == 2:
            await message.reply(f"Don't flood.\nSilence for {throttled.rate} sec.")
        elif throttled.exceeded_count >= 2:
            pass

    async def on_process_callback_query(self, callback_query: types.CallbackQuery, _):
        """
        This handler is called when dispatcher receives a callback_query

        :param callback_query:
        :param _:
        """
        # Get current handler
        handler = current_handler.get()

        # Get dispatcher from context
        dispatcher = Dispatcher.get_current()
        # If handler was configured, get rate limit and key from handler
        if handler:
            limit = getattr(handler, 'throttling_rate_limit', self.rate_limit)
            key = getattr(handler, 'throttling_key', f"{self.prefix}_{handler.__name__}_{callback_query.data}")
        else:
            limit = self.rate_limit
            key = f"{self.prefix}_callback_query_{callback_query.data}"

        # Use Dispatcher.throttle method.
        try:
            await dispatcher.throttle(key, rate=limit)
        except Throttled as t:
            # Execute action
            await self.callback_query_throttled(callback_query, t)

            # Cancel current handler
            raise CancelHandler()

    @staticmethod
    async def callback_query_throttled(callback_query: types.CallbackQuery, throttled: Throttled):
        """
        Notify user only on first exceed and notify about unlocking only on last exceed

        :param callback_query:
        :param throttled:
        """

        # Prevent flooding
        if throttled.exceeded_count == 2:
            await callback_query.answer("Don't flood. Please wait.", show_alert=False)
        elif throttled.exceeded_count >= 2:
            pass


# fuctions
def get_stream(arguments, cur):
    arguments = arguments[1:]

    if len(arguments) >= 5:
        cur.execute("""
            SELECT file_id, caption FROM streams 
            WHERE author = %s AND year = %s AND month = %s AND day = %s AND part = %s
        """, arguments)
    else:
        cur.execute("""
            SELECT file_id, caption FROM streams WHERE author = %s AND year = %s AND month = %s AND day = %s
        """, arguments)
    return cur.fetchone()


def get_streams_by_args(args, cur):
    streamer = args[0]
    date = time.strptime(args[1], "%d.%m.%Y")

    cur.execute("""
        SELECT file_id, caption FROM streams WHERE author = %s AND year = %s AND month = %s AND day = %s
    """, [streamer, date.tm_year, date.tm_mon, date.tm_mday])
    return cur.fetchall()


def get_video(vid, cur):
    cur.execute("""
        SELECT file_id, caption FROM videos WHERE id = %s
    """, vid)
    return cur.fetchone()


def get_video_2(vid, cur):
    cur.execute("""
        SELECT file_id, caption FROM videos2 WHERE id = %s
    """, vid)
    return cur.fetchone()


def get_video_3(vid, cur):
    cur.execute("""
        SELECT file_id, caption FROM videos3 WHERE id = %s
    """, vid)
    return cur.fetchone()


def get_last_stream(arguments, cur):
    keys = []
    author = arguments[1]

    cur.execute("""
        SELECT file_id, caption, udata, year, month, day, part FROM streams 
        WHERE author = %s ORDER BY udata DESC, part ASC
    """, [author])
    result = cur.fetchone()
    if result['part']:
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
            if result['part']:
                keys.append([IKB(
                    text=f"{result['caption']}",
                    callback_data=f"1@{author}@{result['year']}@{result['month']}@{result['day']}@{result['part']}"
                )])
            else:
                keys.append([IKB(
                    text=f"{result['caption']}",
                    callback_data=f"1@{author}@{result['year']}@{result['month']}@{result['day']}"
                )])

    # add control buttons
    keys.append([])

    keys[-1].append(IKB(text=uic.BACK, callback_data=f"1@{author}"))  # back button
    keys[-1].append(IKB(text=uic.REFRESH, callback_data=f"last@{author}"))  # refresh button

    return InlineKeyboardMarkup(inline_keyboard=keys)


def get_keyboard(arguments, cur):
    page_number = int(arguments[0])
    arguments = arguments[1:]
    results: list[dict[str, Any]]
    keys = []

    # select mysql request
    if len(arguments) == 0:
        # add bonus button with videos
        keys.append([
            IKB(
                text=uic.VIDEOS,
                callback_data=f"videos@1"
            ),
            IKB(
                text=uic.VIDEOS2,
                callback_data=f"videos2@1"
            ),
            IKB(
                text=uic.VIDEOS3,
                callback_data=f"videos3@1"
            )
        ])

        cur.execute("""
            SELECT DISTINCT author FROM streams
        """)
        results = cur.fetchall()

        for result in results[(page_number - 1) * 10:page_number * 10]:
            keys.append([IKB(
                text=result['author'],
                callback_data=f"1@{result['author']}"
            )])

    elif len(arguments) == 1:
        cur.execute(f"""
            SELECT DISTINCT year FROM streams WHERE author = %s ORDER BY year DESC
        """, arguments)
        results = cur.fetchall()

        for result in results[(page_number - 1) * 10:page_number * 10]:
            keys.append([IKB(
                text=result['year'],
                callback_data=f"1@{arguments[0]}@{result['year']}"
            )])

        keys.append([IKB(
            text=uic.LATESTS,
            callback_data=f"last@{arguments[0]}"
        )])

    elif len(arguments) == 2:
        cur.execute(f"""
            SELECT DISTINCT month FROM streams WHERE author = %s AND year = %s ORDER BY month ASC
        """, arguments)
        results = cur.fetchall()

        for result in results[(page_number - 1) * 10:page_number * 10]:
            keys.append([IKB(
                text=result['month'],
                callback_data=f"1@{'@'.join(arguments)}@{result['month']}"
            )])

    elif len(arguments) == 3:
        cur.execute(f"""
            SELECT caption, day, part FROM streams 
            WHERE author = %s AND year = %s AND month = %s ORDER BY day ASC, part ASC
        """, arguments)
        results = cur.fetchall()
        for result in results[(page_number - 1) * 10:page_number * 10]:
            if result['part']:
                keys.append([IKB(
                    text=f"{result['caption']}",
                    callback_data=f"1@{'@'.join(arguments)}@{result['day']}@{result['part']}"
                )])
            else:
                keys.append([IKB(
                    text=f"{result['caption']}",
                    callback_data=f"1@{'@'.join(arguments)}@{result['day']}"
                )])
    else:
        results = []

    # add control buttons
    keys.append([])

    if len(arguments) == 0:
        keys[-1].append(IKB(text=uic.REFRESH, callback_data=f"1"))  # back button
    elif len(arguments) == 1:
        keys[-1].append(IKB(text=uic.BACK, callback_data=f"1"))  # back button
    else:
        keys[-1].append(IKB(text=uic.BACK, callback_data=f"1@{'@'.join(arguments[:-1])}"))  # back button

    if page_number > 1:  # previos page button
        keys[-1].append(IKB(text=uic.PREV, callback_data=f"{page_number - 1}@{'@'.join(arguments)}"))

    keys[-1].append(IKB(text=f"{page_number}", callback_data=f"pass"))  # info page button

    if page_number <= (len(results) - 1) // 10:  # next page button
        keys[-1].append(IKB(text=uic.NEXT, callback_data=f"{page_number + 1}@{'@'.join(arguments)}"))

    return InlineKeyboardMarkup(inline_keyboard=keys)


def get_finder_keyboard(expresion, page, cur):
    page = int(page)
    keys = []

    # select mysql request
    cur.execute(f"""
        SELECT caption, author, day, month, year, part FROM streams WHERE caption LIKE %s ORDER BY udata DESC, part ASC
    """, [f"%{expresion}%"])

    results = cur.fetchall()
    if not results:
        return None

    for result in results[(page - 1) * 10:page * 10]:
        if result['part']:
            keys.append([IKB(
                text=f"{result['caption']}",
                callback_data=f"1@{result['author']}"
                              f"@{result['year']}@{result['month']}@{result['day']}@{result['part']}"
            )])
        else:
            keys.append([IKB(
                text=f"{result['caption']}",
                callback_data=f"1@{result['author']}@{result['year']}@{result['month']}@{result['day']}"
            )])

    # add control buttons
    keys.append([])

    if page > 1:  # previos page button
        keys[-1].append(IKB(text=uic.PREV, callback_data=f"find@{expresion}@{page - 1}"))

    keys[-1].append(IKB(text=f"{page}", callback_data=f"pass"))  # info page button

    if page <= (len(results) - 1) // 10:  # next page button
        keys[-1].append(IKB(text=uic.NEXT, callback_data=f"find@{expresion}@{page + 1}"))

    return InlineKeyboardMarkup(inline_keyboard=keys)


def get_videos_keyboard(page, cur):
    page = int(page)
    keys = []

    # select mysql request
    cur.execute("""
        SELECT id, caption FROM videos ORDER BY vorder ASC
    """)
    results = cur.fetchall()

    for result in results[(page - 1) * 10:page * 10]:
        keys.append([IKB(
            text=result['caption'],
            callback_data=f"video@{result['id']}"
        )])

    # add control buttons
    keys.append([])

    keys[-1].append(IKB(text=uic.BACK, callback_data=f"1"))  # back button

    if page > 1:  # previos page button
        keys[-1].append(IKB(text=uic.PREV, callback_data=f"videos@{page - 1}"))

    keys[-1].append(IKB(text=f"{page}", callback_data=f"pass"))  # info page button

    if page <= (len(results) - 1) // 10:  # next page button
        keys[-1].append(IKB(text=uic.NEXT, callback_data=f"videos@{page + 1}"))

    return InlineKeyboardMarkup(inline_keyboard=keys)


def get_videos_2_keyboard(page, cur):
    page = int(page)
    keys = []

    # select mysql request
    cur.execute("""
        SELECT id, caption FROM videos2 ORDER BY vorder ASC
    """)
    results = cur.fetchall()

    for result in results[(page - 1) * 10:page * 10]:
        keys.append([IKB(
            text=result['caption'],
            callback_data=f"video2@{result['id']}"
        )])

    # add control buttons
    keys.append([])

    keys[-1].append(IKB(text=uic.BACK, callback_data=f"1"))  # back button

    if page > 1:  # previos page button
        keys[-1].append(IKB(text=uic.PREV, callback_data=f"videos2@{page - 1}"))

    keys[-1].append(IKB(text=f"{page}", callback_data=f"pass"))  # info page button

    if page <= (len(results) - 1) // 10:  # next page button
        keys[-1].append(IKB(text=uic.NEXT, callback_data=f"videos2@{page + 1}"))

    return InlineKeyboardMarkup(inline_keyboard=keys)


def get_videos_3_keyboard(page, cur):
    page = int(page)
    keys = []

    # select mysql request
    cur.execute("""
        SELECT id, caption FROM videos3 ORDER BY vorder ASC
    """)
    results = cur.fetchall()

    for result in results[(page - 1) * 10:page * 10]:
        keys.append([IKB(
            text=result['caption'],
            callback_data=f"video3@{result['id']}"
        )])

    # add control buttons
    keys.append([])

    keys[-1].append(IKB(text=uic.BACK, callback_data=f"1"))  # back button

    if page > 1:  # previos page button
        keys[-1].append(IKB(text=uic.PREV, callback_data=f"videos3@{page - 1}"))

    keys[-1].append(IKB(text=f"{page}", callback_data=f"pass"))  # info page button

    if page <= (len(results) - 1) // 10:  # next page button
        keys[-1].append(IKB(text=uic.NEXT, callback_data=f"videos3@{page + 1}"))

    return InlineKeyboardMarkup(inline_keyboard=keys)


def get_stream_parts(streamer, unix_data, cur):
    cur.execute("""
        SELECT part FROM streams WHERE author=%s AND udata=%s
    """, [streamer, unix_data])
    raw = cur.fetchall()
    return [dct.get('part') or 'single' for dct in raw]


def add_stream(args, reply, db, cur):
    streamer = args[0]
    date = time.strptime(args[1], "%d.%m.%Y")
    unix_data = time.mktime(date)
    part = args[2] if len(args) >= 3 else None

    if not reply:
        return None
    if not reply.caption:
        return None
    if not reply.video:
        return None

    before = get_stream_parts(streamer, unix_data, cur)

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

    after = get_stream_parts(streamer, unix_data, cur)

    return before, after


def del_stream(caption, db, cur):
    cur.execute("""
        DELETE FROM streams
        WHERE caption=%s
        LIMIT 1
    """, [caption])
    db.commit()

    return True


def add_video(args, reply, db, cur):
    vorder = args[0]

    if not reply:
        return False
    if not reply.caption:
        return False
    if not reply.video:
        return False

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


def add_video_2(args, reply, db, cur):
    vorder = args[0]

    if not reply:
        return False
    if not reply.caption:
        return False
    if not reply.video:
        return False

    cur.execute("""
        INSERT INTO videos2(
            vorder,
            file_id, caption
        ) VALUES(%s,%s,%s)
    """, [
        vorder,
        reply.video.file_id, reply.caption
    ])
    db.commit()

    return True


def add_video_3(args, reply, db, cur):
    vorder = args[0]

    if not reply:
        return False
    if not reply.caption:
        return False
    if not reply.video:
        return False

    LOGGER.info(f'Add video3 {vorder} {reply.video.file_id} {reply.caption}')

    cur.execute("""
        INSERT INTO videos3(
            vorder,
            file_id, caption
        ) VALUES(%s,%s,%s)
    """, [
        vorder,
        reply.video.file_id,
        reply.caption
    ])
    db.commit()

    return True


def del_video(caption, db, cur):
    cur.execute("""
        DELETE FROM videos
        WHERE caption=%s
        LIMIT 1
    """, [caption])
    db.commit()

    return True


def del_video_2(caption, db, cur):
    cur.execute("""
        DELETE FROM videos2
        WHERE caption=%s
        LIMIT 1
    """, [caption])
    db.commit()

    return True


def del_video_3(caption, db, cur):
    cur.execute("""
        DELETE FROM videos3
        WHERE caption=%s
        LIMIT 1
    """, [caption])
    db.commit()

    return True


def add_chat(chat_id, platform, streamer_id, db, cur):
    cur.execute("""
        SELECT * FROM chats WHERE id=%s AND platform=%s AND streamer_id=%s
    """, [chat_id, platform, streamer_id])

    if not cur.fetchone():
        cur.execute("""
            INSERT INTO chats(
                id, platform, streamer_id
            ) VALUES(%s,%s,%s)
        """, [
            chat_id, platform, streamer_id
        ])
        db.commit()
        return True
    return False


def del_chat(chat_id, platform, streamer_id, db, cur, limit=None):
    if limit is None:
        cur.execute("""
            DELETE FROM chats
            WHERE id=%s AND platform=%s AND streamer_id=%s
        """, [chat_id, platform, streamer_id])
    else:
        cur.execute("""
            DELETE FROM chats
            WHERE id=%s AND platform=%s AND streamer_id=%s LIMIT %s
        """, [chat_id, platform, streamer_id, limit])
    db.commit()

    return True


async def correct_chats(db, cur):
    cur.execute("""
        SELECT id, platform, streamer_id FROM chats
    """)
    chats = cur.fetchall()
    unique_chats = set()
    unique_streamers = {(streamer['platform'], streamer['id']) for streamer in get_streamers()}

    old_counter = 0
    twink_counter = 0

    for chat in chats:
        if (chat['platform'], chat['streamer_id']) not in unique_streamers:
            del_chat(chat['id'], chat['platform'], chat['streamer_id'], db, cur, limit=1)
            old_counter += 1
            continue

        tuple_key = (chat['id'], chat['platform'], chat['streamer_id'])
        if tuple_key in unique_chats:
            del_chat(chat['id'], chat['platform'], chat['streamer_id'], db, cur, limit=1)
            twink_counter += 1
            continue

        unique_chats.add(tuple_key)
        await asyncio.sleep(0)

    return old_counter, twink_counter


def add_mark(user_id, reply, db, cur):
    if not reply.caption:
        return False

    # get stream id
    cur.execute(f"""
        SELECT id FROM streams WHERE caption=%s
    """, [reply.caption])

    result = cur.fetchone()
    if not result:
        return None

    stream_id = result['id']

    cur.execute("""
        INSERT INTO marks(
            user_id,
            stream_id
        ) VALUES(%s,%s)
    """, [
        user_id,
        stream_id
    ])
    db.commit()

    return True


def del_mark(user_id, reply, db, cur):
    if not reply.caption:
        return False

    # get stream id
    cur.execute(f"""
        SELECT id FROM streams WHERE caption=%s
    """, [reply.caption])

    result = cur.fetchone()
    if not result:
        return None

    stream_id = result['id']

    cur.execute("""
        DELETE FROM marks
        WHERE user_id=%s AND stream_id=%s
        LIMIT 1
    """, [
        user_id,
        stream_id
    ])
    db.commit()

    return True


def get_marks(user_id, page, cur):
    page = int(page)
    keys = []

    # select mysql request
    cur.execute("""
        SELECT stream_id FROM marks WHERE user_id=%s
    """, [user_id])
    results = cur.fetchall()

    for result in results[(page - 1) * 10:page * 10]:
        cur.executemany("""
            SELECT caption, author, day, month, year, part FROM streams WHERE id=%s
        """, [result['stream_id']])
        result = cur.fetchone()

        if result['part']:
            keys.append([IKB(
                text=f"{result['caption']}",
                callback_data=f"1@{result['author']}"
                              f"@{result['year']}@{result['month']}@{result['day']}@{result['part']}"
            )])
        else:
            keys.append([IKB(
                text=f"{result['caption']}",
                callback_data=f"1@{result['author']}@{result['year']}@{result['month']}@{result['day']}"
            )])

    # add control buttons
    keys.append([])

    keys[-1].append(IKB(text=uic.REFRESH, callback_data=f"marks@{user_id}@{page}"))  # back button

    if page > 1:  # previos page button
        keys[-1].append(IKB(text=uic.PREV, callback_data=f"marks@{user_id}@{page - 1}"))

    keys[-1].append(IKB(text=f"{page}", callback_data=f"pass"))  # info page button

    if page <= (len(results) - 1) // 10:  # next page button
        keys[-1].append(IKB(text=uic.NEXT, callback_data=f"marks@{user_id}@{page + 1}"))

    return InlineKeyboardMarkup(inline_keyboard=keys)


def get_streamers():
    with open(CONFIGS['streamlink']['streamers'], "r", encoding='utf-8') as f:
        return json.load(f)


def set_streamers(streamers_update):
    with open(CONFIGS['streamlink']['streamers'], "w", encoding='utf-8') as f:
        json.dump(streamers_update, f, indent=4)


def get_notif_keyboard(chat_id, _, cur):
    keys = []

    def in_notif(streamer_data, notifs):
        for notif in notifs:
            if notif['platform'] == streamer_data['platform'] and notif['streamer_id'] == streamer_data['id']:
                return True
        return False

    # select notif from sql
    cur.execute("""
        SELECT platform, streamer_id FROM chats WHERE id=%s
    """, [chat_id])
    notifications = cur.fetchall()

    # select streamers from json
    streamers = get_streamers()
    for streamer in streamers:  # [(page-1)*10:page*10]
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
            if page < len(streamers)//10
            else IKB(text=uic.STOP, callback_data=f"pass")
        )
    """
    return InlineKeyboardMarkup(inline_keyboard=keys)


def get_last_up():
    info_table = ""

    # select streamers from json
    streamers = get_streamers()
    for streamer in streamers:  # [(page-1)*10:page*10]
        info_table += (
                uic.build_last_stream(streamer) +
                "\n"
        )

    """
        keys.append([IKB(
            text=f"{uic.YES if notif_on else uic.NO} {streamer['name']}",
            callback_data=f"lastup@{streamer['platform']}@{streamer['id']}"
        )])

        -----------------------------------------------
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
            if page < len(streamers)//10
            else IKB(text=uic.STOP, callback_data=f"pass")
        )

        ------------------------------------------------
        return InlineKeyboardMarkup(inline_keyboard = keys)
    """
    return info_table


def get_cooldowns():
    info_table = ""

    # select streamers from json
    streamers = get_streamers()
    for streamer in streamers:  # [(page-1)*10:page*10]
        info_table += (
                uic.build_cooldown(
                    streamer,
                    time.gmtime(max(
                        0.0,
                        (streamer['lastdown'] + CONFIGS['streamlink'].getfloat('cooldown')) - time.time()
                    ))
                ) +
                "\n"
        )

    return info_table


async def broadcast_text(bot, text, db):
    async def stable_send(chat_id, platform, streamer_id, msg_text):
        try:
            await bot.send_message(chat_id, msg_text)
        except BotBlocked:
            LOGGER.error(f"Target [ID:{chat_id}]: blocked by user")
            with db, db.cursor() as cur:
                del_chat(chat_id, platform, streamer_id, db, cur)
        except ChatNotFound:
            LOGGER.error(f"Target [ID:{chat_id}]: invalid ID")
            with db, db.cursor() as cur:
                del_chat(chat_id, platform, streamer_id, db, cur)
        except RetryAfter as e:
            LOGGER.error(f"Target [ID:{chat_id}]: Flood limit is exceeded. Sleep {e.timeout} seconds.")
            await asyncio.sleep(e.timeout)
            return await stable_send(chat_id, platform, streamer_id, msg_text)  # Recursive call
        except UserDeactivated:
            LOGGER.error(f"Target [ID:{chat_id}]: user is deactivated")
            with db, db.cursor() as cur:
                del_chat(chat_id, platform, streamer_id, db, cur)
        except TelegramAPIError:
            LOGGER.exception(f"Target [ID:{chat_id}]: failed")
        else:
            return True
        return False

    LOGGER.info(f"Broadcast info{{ {text:32}{'...' if len(text) > 32 else ''} }}")

    with db, db.cursor() as cursor:
        cursor.execute("""
            SELECT id, platform, streamer_id FROM chats
        """)
        recipients = cursor.fetchall()

    # test on unicue broadcast
    repeated = set()

    repeated_counter = 0
    successfull_counter = 0
    for recipient in recipients:
        if recipient['id'] in repeated:
            repeated_counter += 1
            continue

        if await stable_send(recipient['id'], recipient['platform'], recipient['streamer_id'], text):
            successfull_counter += 1
            repeated.add(recipient['id'])

        await asyncio.sleep(0.04)

    if successfull_counter + repeated_counter == len(recipients):
        LOGGER.info(f"Broadcast succesfull!\n\tAmount: {successfull_counter}\n\tRepeaded: {repeated_counter}.")
        return f"Broadcast succesfull!\n\tAmount: {successfull_counter}\n\tRepeaded: {repeated_counter}."
    else:
        LOGGER.warning(
            f"Broadcast losses: {len(recipients) - successfull_counter} "
            f"to {len(recipients)}!\n\tRepeaded: {repeated_counter}.")
        return f"Broadcast losses: {len(recipients) - successfull_counter} " \
               f"to {len(recipients)}!\n\tRepeaded: {repeated_counter}."


async def broadcast_stream(bot, streamer, text, broadcast_id, db):
    async def stable_send(chat_id, msg_text):
        try:
            await bot.send_message(chat_id, msg_text)
        except BotBlocked:
            LOGGER.error(f"Target [ID:{chat_id}]: blocked by user")
            with db, db.cursor() as cur:
                del_chat(chat_id, streamer['platform'], streamer['id'], db, cur)
        except ChatNotFound:
            LOGGER.error(f"Target [ID:{chat_id}]: invalid ID")
            with db, db.cursor() as cur:
                del_chat(chat_id, streamer['platform'], streamer['id'], db, cur)
        except RetryAfter as e:
            LOGGER.error(f"Target [ID:{chat_id}]: Flood limit is exceeded. Sleep {e.timeout} seconds.")
            await asyncio.sleep(e.timeout)
            return await stable_send(chat_id, msg_text)  # Recursive call
        except UserDeactivated:
            LOGGER.error(f"Target [ID:{chat_id}]: user is deactivated")
            with db, db.cursor() as cur:
                del_chat(chat_id, streamer['platform'], streamer['id'], db, cur)
        except TelegramAPIError:
            LOGGER.exception(f"Target [ID:{chat_id}]: failed")
        else:
            return True
        return False

    LOGGER.info(f"Broadcast_[{broadcast_id}] for {streamer['name']}...")

    with db, db.cursor() as cursor:
        cursor.execute("""
            SELECT id FROM chats WHERE platform=%s AND streamer_id=%s
        """, [streamer['platform'], streamer['id']])
        recipients = cursor.fetchall()

    successfull_counter = 0
    for recipient in recipients:
        if await stable_send(recipient['id'], text):
            successfull_counter += 1

        await asyncio.sleep(0.04)

    if successfull_counter == len(recipients):
        LOGGER.info(f"Broadcast succesfull!")
    else:
        LOGGER.warning(f"Broadcast losses: {len(recipients) - successfull_counter} to {len(recipients)}!")


async def streams_demon(bot, db):
    async def check_stream(streamer_):
        LOGGER.debug(f"Checking stream for {streamer_['name']} platform:{streamer_['platform']} id:{streamer_['id']}")

        if streamer['platform'] == StreamingPlatform.Wasd:
            stream_out_json_file = '/home/ubuntu/cifra/check_streams_main/check_wasd.json'
        elif streamer['platform'] == StreamingPlatform.Twitch:
            stream_out_json_file = '/home/ubuntu/cifra/check_streams_main/check_twitch.json'
        else:
            return False, streamer_
        # Проверка статуса стрима во внешнем json-файле
        try:
            async with aiofiles.open(
                    stream_out_json_file,
                    mode='r',
                    encoding='utf-8'
            ) as f:  # Выгружаем содержимое json-файла по wasd
                contents = await f.read()
        except Exception:
            return False, streamer_
        stream_out_json_data = json.loads(contents)

        for streamer_out in stream_out_json_data:
            # Проверяем статус стрима во внешнем json-файле
            if str(streamer_out['channel_id']) == str(streamer['channel_id']):
                # Проверяем только по текущему каналу и текущей платформе
                if streamer_out['stream_status']:
                    # Имя текущего стрима
                    streamer['last_stream_name'] = streamer_out['last_stream_name']
                    return True, streamer_  # online
                else:
                    return False, streamer_  # offline

    # online profilactic
    streamers = get_streamers()
    for streamer in streamers:
        streamer['online'] = True
        streamer.setdefault('lastup', 0)
        streamer.setdefault('lastdown', 0)
    set_streamers(streamers)

    while alive:
        update_flag = False
        streamers = get_streamers()
        chekers = {check_stream(streamer, 2) for streamer in streamers}
        check_id = random.randint(1, 999)

        # итератор в порядке завершения проверок
        for cheker in asyncio.as_completed(chekers):
            online, streamer = await cheker

            LOGGER.debug(f"{streamer['name']} online - [{streamer['online']} -> {online}]")
            if online and not streamer["online"]:
                if time.time() - streamer['lastdown'] > CONFIGS['streamlink'].getfloat('cooldown'):  # one hour
                    streamer['lastup'] = time.time()
                    stream_name = ''

                    try:
                        # Выгрузка названия стрима
                        stream_name = streamer['last_stream_name']
                        stream_name = f'«{stream_name}»'
                    except Exception:
                        # Если ошибки - то в качестве имени стрима пихаем пустую строку
                        LOGGER.error(traceback.format_exc())

                    await broadcast_stream(bot, streamer, uic.build_stream_text(streamer, stream_name), check_id, db)
                else:
                    LOGGER.warning(
                        f"Stream broadcast[{check_id}] cooldown({time.time() - streamer['lastdown']}) "
                        f"for {streamer['name']} platform:{streamer['platform']} id:{streamer['id']}")
                    await bot.send_message(
                        CONFIGS['telegram']['dashboard'],
                        f"Stream broadcast[{check_id}] cooldown({int(time.time() - streamer['lastdown'])}) "
                        f"for {streamer['name']} platform:{streamer['platform']} id:{streamer['id']}"
                    )

            if streamer["online"] and not online:
                streamer['lastdown'] = time.time()

            if streamer["online"] != online:
                update_flag = True

            streamer["online"] = online

        if update_flag:
            set_streamers(streamers)

        await asyncio.sleep(30)


# main function
def start():
    LOGGER.info("Starting...")

    # connection to database
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
            CREATE TABLE IF NOT EXISTS videos2 (
                id      Int             NOT NULL PRIMARY KEY AUTO_INCREMENT,
                file_id Varchar(255)    NOT NULL,
                caption Varchar(1024)   NOT NULL,
                vorder  Int             NULL
            )
        """)
        dbcursor.execute("""
            CREATE TABLE IF NOT EXISTS videos3 (
                id      Int             NOT NULL PRIMARY KEY AUTO_INCREMENT,
                file_id Varchar(255)    NOT NULL,
                caption Varchar(1024) CHARACTER SET utf8 COLLATE utf8_general_ci NOT NULL,
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
        dbcursor.execute("""
            CREATE TABLE IF NOT EXISTS marks (
                user_id     BigInt          NOT NULL,
                stream_id   Int             NOT NULL
            )
        """)
        database.commit()

    # create bot
    bot = Bot(token=CONFIGS['telegram']['token'])
    storage = MemoryStorage()
    dispatcher = Dispatcher(bot, storage=storage)

    middleware = ThrottlingMiddleware(throttling_rate_limit=7)
    dispatcher.middleware.setup(middleware)

    # bot handlers
    @dispatcher.message_handler(commands=["start"])
    async def start_handler(message: types.Message):
        # processing command /start
        # get streamers from db
        # and
        # construct keyboard
        with database, database.cursor() as cur:
            keyboard = get_keyboard([1], cur)
        await message.reply(uic.START_CMD, reply_markup=keyboard)

    @dispatcher.message_handler(commands=["help"])
    async def help_handler(message: types.Message):
        # processing command /help
        await message.reply(uic.HELP_CMD)

    @dispatcher.message_handler(commands=["notifications"])
    async def notifications_handler(message: types.Message):
        # processing command /notifications
        # get streamers from json
        # and
        # construct keyboard
        with database, database.cursor() as cur:
            keyboard = get_notif_keyboard(message.chat.id, 1, cur)
        await message.reply(uic.NOTIFICATIONS_CMD, reply_markup=keyboard)

    @dispatcher.message_handler(commands=["lastup"])
    async def notifications_handler(message: types.Message):
        last_up_info = get_last_up()
        await message.reply(uic.LASTUP + "\n" + md.hpre(last_up_info), parse_mode="html")

    @dispatcher.message_handler(commands=["find"])
    async def find_handler(message: types.Message):
        # processing command /find
        # get streams from db
        # and
        # construct keyboard
        command, expresion = message.get_full_command()
        if len(expresion) < 3 or len(expresion) > 30:
            await message.reply(uic.FIND_NO_ARGS)
            return
        my_message = await message.reply(uic.WAIT)

        with database, database.cursor() as cur:
            keyboard = get_finder_keyboard(expresion, 1, cur)
        try:
            if keyboard:
                await my_message.edit_text(uic.FINDED, reply_markup=keyboard)
            else:
                await my_message.edit_text(uic.NOT_FOUND)
        except MessageNotModified:
            pass
        return

    @dispatcher.message_handler(commands=["review", "r"])
    async def review_handler(message: types.Message):
        # processing command /find
        # get streams from db
        # and
        # construct keyboard
        command, msg_for_dev = message.get_full_command()
        if len(msg_for_dev) < 3:
            await message.reply(uic.TO_SMALL)
            return

        try:
            if message.reply_to_message is not None:
                await message.reply_to_message.forward(CONFIGS['telegram']['dashboard'])
            await message.forward(CONFIGS['telegram']['dashboard'])
            await bot.send_message(CONFIGS['telegram']['dashboard'], uic.build_review_info(message), parse_mode="html")

            await message.answer(uic.SENDED)
        except BadRequest:
            await message.answer(uic.WRONG)
        except Exception:
            await message.answer(uic.ERROR)
            raise
        return

    @dispatcher.message_handler(commands=["info"])
    async def send_info(message: types.Message):
        await message.answer("```\n" + pformat(message.to_python()) + "```", parse_mode="markdown")

    @dispatcher.message_handler(commands=["mark"])
    async def add_mark_handler(message: types.Message):
        if message.reply_to_message is None:
            await message.reply(uic.REPLY_NOT_FOUND)
            return

        with database, database.cursor() as cur:
            succsces = add_mark(message.from_user.id, message.reply_to_message, database, cur)

        if succsces:
            await message.reply(uic.ADDED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(commands=["unmark"])
    async def unmark_handler(message: types.Message):
        if message.reply_to_message is None:
            await message.reply(uic.REPLY_NOT_FOUND)
            return

        with database, database.cursor() as cur:
            succsces = del_mark(message.from_user.id, message.reply_to_message, database, cur)

        if succsces:
            await message.reply(uic.DELETED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(commands=["marks"])
    async def marks_handler(message: types.Message):
        with database, database.cursor() as cur:
            keyboard = get_marks(message.from_user.id, 1, cur)
        await message.reply(uic.MARKS_CMD, reply_markup=keyboard)

    @dispatcher.message_handler(commands=["get"])
    async def del_handler(message: types.Message):
        # processing command /del caption
        command, args = message.get_full_command()
        args = re.sub(r"\\\s", "@@", args)
        args = args.split()
        args = [re.sub(r"@@", " ", arg) for arg in args]

        with database, database.cursor() as cur:
            streams = get_streams_by_args(args, cur)

        if streams:
            for stream in streams:
                await message.answer_video(video=stream['file_id'], caption=stream['caption'])
        else:
            await message.reply(uic.NOT_FOUND)

    # DASHBOARD COMMANDS
    dashboard_filter = IDFilter(chat_id=CONFIGS['telegram']['dashboard'])

    @dispatcher.message_handler(dashboard_filter, commands=["vipinfo"])
    async def send_info(message: types.Message):
        await message.answer("```\n" + pformat(message.to_python()) + "```", parse_mode="markdown")

    @dispatcher.message_handler(dashboard_filter, commands=["viphelp"])
    async def help_handler(message: types.Message):
        # processing command /help
        await message.reply(uic.VIPHELP_CMD)

    @dispatcher.message_handler(dashboard_filter, commands=["add"])
    async def add_handler(message: types.Message):
        # processing command /add streamer data [, part]
        # get streamers from db
        # and
        # construct keyboard
        command, args = message.get_full_command()
        args = re.sub(r"\\\s", "@@", args)
        args = args.split()
        args = [re.sub(r"@@", " ", arg) for arg in args]

        with database, database.cursor() as cur:
            succsces = add_stream(args, message.reply_to_message, database, cur)

        if succsces:
            parts_before, parts_after = succsces
            await message.reply(uic.added_with_parts(parts_before, parts_after), parse_mode="html")
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["addv"])
    async def addv_handler(message: types.Message):
        # processing command /add streamer data [, part]
        # get streamers from db
        # and
        # construct keyboard
        command, args = message.get_full_command()
        args = re.sub(r"\\\s", "@@", args)
        args = args.split()
        args = [re.sub(r"@@", " ", arg) for arg in args]

        with database, database.cursor() as cur:
            succsces = add_video(args, message.reply_to_message, database, cur)

        if succsces:
            await message.reply(uic.ADDED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["addv2"])
    async def addv2_handler(message: types.Message):
        # processing command /add streamer data [, part]
        # get streamers from db
        # and
        # construct keyboard
        command, args = message.get_full_command()
        args = re.sub(r"\\\s", "@@", args)
        args = args.split()
        args = [re.sub(r"@@", " ", arg) for arg in args]

        with database, database.cursor() as cur:
            succsces = add_video_2(args, message.reply_to_message, database, cur)

        if succsces:
            await message.reply(uic.ADDED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["addv3"])
    async def addv3_handler(message: types.Message):
        # processing command /add streamer data [, part]
        # get streamers from db
        # and
        # construct keyboard
        command, args = message.get_full_command()
        args = re.sub(r"\\\s", "@@", args)
        args = args.split()
        args = [re.sub(r"@@", " ", arg) for arg in args]

        with database, database.cursor() as cur:
            succsces = add_video_3(args, message.reply_to_message, database, cur)

        if succsces:
            await message.reply(uic.ADDED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["del"])
    async def del_handler(message: types.Message):
        # processing command /del caption
        command, caption = message.get_full_command()

        with database, database.cursor() as cur:
            succsces = del_stream(caption, database, cur)

        if succsces:
            await message.reply(uic.DELETED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["delv"])
    async def delv_handler(message: types.Message):
        # processing command /del caption
        # get streamers from db
        # and
        # construct keyboard
        command, caption = message.get_full_command()
        with database, database.cursor() as cur:
            succsces = del_video(caption, database, cur)

        if succsces:
            await message.reply(uic.DELETED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["delv2"])
    async def delv2_handler(message: types.Message):
        # processing command /del caption
        # get streamers from db
        # and
        # construct keyboard
        command, caption = message.get_full_command()
        with database, database.cursor() as cur:
            succsces = del_video_2(caption, database, cur)

        if succsces:
            await message.reply(uic.DELETED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["delv3"])
    async def delv3_handler(message: types.Message):
        # processing command /del caption
        # get streamers from db
        # and
        # construct keyboard
        command, caption = message.get_full_command()
        with database, database.cursor() as cur:
            succsces = del_video_3(caption, database, cur)

        if succsces:
            await message.reply(uic.DELETED)
        else:
            await message.reply(uic.WRONG)

    @dispatcher.message_handler(dashboard_filter, commands=["rep"])
    async def rep_handler(message: types.Message):
        # processing command /del caption
        # get streamers from db
        # and
        # construct keyboard
        command, args = message.get_full_command()
        args = args.split()
        chat_id = args[0]
        rep_msg = ' '.join(args[1:])

        try:
            await bot.send_message(chat_id, rep_msg)
        except BotBlocked:
            await message.answer("Bot blocked by user(")
        except ChatNotFound:
            await message.answer("Invalid ID")
        except UserDeactivated:
            await message.answer("User is deactivated")
        except Exception:
            await message.reply(uic.ERROR)
            raise
        else:
            await message.reply(uic.SENDED)

    @dispatcher.message_handler(dashboard_filter, commands=["broadcast"])
    async def broadcast_handler(message: types.Message):
        # processing command /del caption
        # get streamers from db
        # and
        # construct keyboard
        command, text = message.get_full_command()

        await message.reply(f"Start broadcast...")
        result = await broadcast_text(bot, text, database)
        await message.reply(result)

    @dispatcher.message_handler(dashboard_filter, commands=["cooldowns"])
    async def cooldowns_handler(message: types.Message):
        # processing command /del caption
        # get streamers from db
        # and
        # construct keyboard
        result = uic.WRONG
        try:
            result = uic.COOLDOWN + "\n" + md.hpre(get_cooldowns())
        finally:
            await message.reply(result, parse_mode="html")

    @dispatcher.message_handler(dashboard_filter, commands=["fixnotifs"])
    async def fixnotifs_handler(message: types.Message):
        # processing command /del caption
        # get streamers from db
        # and
        # construct keyboard


        result = uic.ERROR

        await message.reply(f"Start fixing...")
        with database, database.cursor() as cur:
            olds, twinks = await correct_chats(database, cur)
            result = f"Chat fixed succesfull! Deleted:\nOld notifs - {olds}\nTwinks - {twinks}"
        await message.reply(result)

    @dispatcher.message_handler()
    async def unknow_cmd(message: types.Message):
        await message.answer(uic.UNKNOW_CMD)

    # CALLBACK
    @dispatcher.callback_query_handler()
    async def button_handler(callback_query: types.CallbackQuery):
        args = callback_query.data.split("@")
        if args[0] == 'pass':
            return

        if args[0] == 'notification':
            # args[1] - is on notif
            # args[2] - platform
            # args[3] - streamer
            with database, database.cursor() as cur:
                if not bool(int(args[1])):
                    add_chat(callback_query.message.chat.id, args[2], args[3], database, cur)
                else:
                    del_chat(callback_query.message.chat.id, args[2], args[3], database, cur)

                keyboard = get_notif_keyboard(callback_query.message.chat.id, 1, cur)
            try:
                await callback_query.message.edit_text(uic.NOTIFICATIONS_CMD, reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if args[0] == 'notifset':  # args[1] = page
            with database, database.cursor() as cur:
                keyboard = get_notif_keyboard(callback_query.message.chat.id, args[1], cur)
            await callback_query.message.edit_text(uic.NOTIFICATIONS_CMD, reply_markup=keyboard)
            return

        if args[0] == 'videos':  # args[1] = page
            with database, database.cursor() as cur:
                keyboard = get_videos_keyboard(args[1], cur)

            try:
                await callback_query.message.edit_text(uic.VIDEOS, reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if args[0] == 'video':  # args[1] = id
            await callback_query.message.chat.do('upload_video')

            with database, database.cursor() as cur:
                video = get_video(args[1], cur)
            if video:
                await callback_query.message.answer_video(video=video['file_id'], caption=video['caption'])
            else:
                await callback_query.message.answer(uic.NOT_FOUND)
            return

        if args[0] == 'videos2':  # args[1] = page
            with database, database.cursor() as cur:
                keyboard = get_videos_2_keyboard(args[1], cur)

            try:
                await callback_query.message.edit_text(uic.VIDEOS2, reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if args[0] == 'video2':  # args[1] = id
            await callback_query.message.chat.do('upload_video')

            with database, database.cursor() as cur:
                video = get_video_2(args[1], cur)
            if video:
                await callback_query.message.answer_video(video=video['file_id'], caption=video['caption'])
            else:
                await callback_query.message.answer(uic.NOT_FOUND)
            return

        if args[0] == 'videos3':  # args[1] = page
            with database, database.cursor() as cur:
                keyboard = get_videos_3_keyboard(args[1], cur)

            try:
                await callback_query.message.edit_text(uic.VIDEOS3, reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if args[0] == 'video3':  # args[1] = id
            await callback_query.message.chat.do('upload_video')

            with database, database.cursor() as cur:
                video = get_video_3(args[1], cur)
            if video:
                await callback_query.message.answer_video(video=video['file_id'], caption=video['caption'])
            else:
                await callback_query.message.answer(uic.NOT_FOUND)
            return

        if args[0] == 'find':  # args[1] = expr; args[2] = page
            await callback_query.answer(uic.WAIT, show_alert=False)

            with database, database.cursor() as cur:
                keyboard = get_finder_keyboard(args[1], args[2], cur)

            try:
                if keyboard:
                    await callback_query.message.edit_text(uic.FINDED, reply_markup=keyboard)
                else:
                    await callback_query.message.edit_text(uic.NOT_FOUND)

            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if args[0] == 'last':
            with database, database.cursor() as cur:
                keyboard = get_last_stream(args, cur)
            try:
                await callback_query.message.edit_text(uic.LATESTS, reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)
            return

        if args[0] == 'marks':
            await callback_query.answer(uic.WAIT, show_alert=False)

            with database, database.cursor() as cur:
                keyboard = get_marks(args[1], args[2], cur)  # args 1: user_id, args 2: page

            try:
                await callback_query.message.edit_text(uic.MARKS_CMD, reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.WRONG, show_alert=False)
            return

        if len(args) < 5:
            with database, database.cursor() as cur:
                keyboard = get_keyboard(args, cur)
            try:
                await callback_query.message.edit_text(uic.PICK_MSG[len(args) - 1], reply_markup=keyboard)
            except MessageNotModified:
                await callback_query.answer(uic.NOTHING_NEW, show_alert=False)

        else:
            await callback_query.message.chat.do('upload_video')

            with database, database.cursor() as cur:
                video = get_stream(args, cur)
            if video:
                await callback_query.message.answer_video(video=video['file_id'], caption=video['caption'])
            else:
                await callback_query.message.answer(uic.NOT_FOUND)

    demons = []

    async def on_startup(_):
        global alive
        alive = True
        LOGGER.info("Starting demons...")
        demons.append(
            asyncio.create_task(streams_demon(bot, database))
        )

        LOGGER.info("Listening...")

    async def on_shutdown(_):
        LOGGER.info("Shutdown... Please wait!")
        global alive
        alive = False
        for demon in demons:
            demon.cancel()

    start_polling(
        dispatcher,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown
    )


# start
if __name__ == "__main__":
    start()
