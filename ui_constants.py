NO_CONFIG_MESSAGE = """
  Please create config.ini:
-------------------------------------------------------------------------------
  [data-base]
  host=localhost
  port=
  login=sqllogin
  password=sqlpassword
  name=my_db

  [streamlink]
  streamers = streamers.json
  plugins = streamlink_plugins/

  [telegram]
  token = 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
  dashboard = -1

  [logging]
  #logging levels:

  # CRITICAL    50
  # ERROR       40
  # WARNING     30
  # INFO        20 DEFFAULT
  # DEBUG       10
  # NOTSET      0
  level=20
"""

YES = "🟢"
NO = "🔴"
BACK = "⬆️ Back"
PREV = "⬅️"
NEXT = "➡️"
STOP = "⛔️"
REFRESH = "🔄"

ADDED = "Succsesful added!"
DELETED = "Succsesful deleted!"

ERROR = "Get some error("
WRONG = "Wrong command("
NOT_FOUND = "Not founded("
NOTHING_NEW = "Nothing is new."
WAIT = "Please wait..."
FINDED = "Finded!"
FIND_NO_ARGS = "Please write '/find some text' to seek streams.\nMinimal length of text 3!\nMaximal length of text 30!"

START_CMD = "Pick the streamer!"
HELP_CMD = """
/start - to get keyboard with streams
/help - to get list of commands
/notifications - to set notifications about stream
/find some text - to seek streams by text
"""
NOTIFICATIONS_CMD = "Set the notifications"
UNKNOW_CMD = "Unknow command =/\nEnter /help to get list of commands"

PICK_MSG = [
    START_CMD,
    "Pick the year!",
    "Pick the month!",
    "Pick the stream!"
]

LATESTS = "Latests..."
VIDEOS = "Видео с ютуба - Dawg"
VIDEOS2 = "Видео с ютуба - Alison"

BOTTOM_KEYBOARD = "/start"

def build_stream_text(streamer):
    return f"👁 Стример {streamer['name']} запустил свою трансляцию, ссылка: https://{streamer['platform']}/{streamer['id']}"
