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
from aiogram import Bot, Dispatcher, executor, types


#configs
if not os.path.exists("config.ini"):
    print("""
    Please create config.ini:
    
    ['System']
    domen = 'domen.com:443'
    host = '0.0.0.0'
    port = 443
    ['Telegram']
    token = 'bot123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'
    admin = -1
    """)
    exit()

CONFIGS = ConfigParser()
CONFIGS.read("config.ini")


#logining
file_log = logging.FileHandler("botlogs.log", mode = "w")
console_out = logging.StreamHandler()

logging.basicConfig(
    handlers=(file_log, console_out),
    format='[%(asctime)s | %(levelname)s] %(name)s: %(message)s',
    datefmt='%a %b %d %H:%M:%S %Y',
    level=logging.INFO)
LOGGER = logging.getLogger("bot")

#main function
def main():
    bot = Bot(token=CONFIGS['Telegram']['token'])
    dispatcher = Dispatcher(bot)

    #bot handlers
    @dispatcher.message_handler(commands=['start', 'help'])
    async def send_welcome(message: types.Message):
        """
        This handler will be called when user sends `/start` or `/help` command
        """
        await message.reply("Hi!\nI'm EchoBot!\nPowered by aiogram.")
#start
if __name__ == "__main__":
    main()
