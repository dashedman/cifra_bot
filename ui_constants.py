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
UNKNOW_CMD = "Unknow command =/\nEnter /start to get keyboard"

PICK_MSG = [
    START_CMD,
    "Pick the year!",
    "Pick the month!",
    "Pick the stream!"
]

LAST_STREAM = "Last Stream..."

BOTTOM_KEYBOARD = "/start"
