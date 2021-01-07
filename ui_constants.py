NO_CONFIG_MESSAGE = """
  Please create config.ini:
-------------------------------------------------------------------------------
  [data-base]
  host=localhost
  port=
  login=sqllogin
  password=sqlpassword
  name=my_db

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

ADDED = "Stream succsesful added!"
DELETED = "Stream succsesful deleted!"

ERROR = "Get some error("
WRONG = "Wrong command("
NOT_FOUND = "Target is not founded("
NOTHING_NEW = "Nothing is new."

START_CMD = "Pick the streamer!"
HELP_CMD = """
/start - to get keyboard with streams
/help - to get list of commands
/notifications - to set notifications about stream
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

BOTTOM_KEYBOARD = "/start"

def build_stream_text(streamer):
    return f"👁 Стример {streamer['name']} запустил свою трансляцию, ссылка: https://{streamer['platform']}/{streamer['id']}"
